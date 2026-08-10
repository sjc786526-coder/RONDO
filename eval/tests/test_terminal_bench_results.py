from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from unittest.mock import patch


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.config import RepoPaths  # noqa: E402
from rondo_eval.artifacts import ArtifactWriter  # noqa: E402
from rondo_eval import artifacts as artifacts_module  # noqa: E402
from rondo_eval.contracts import BinaryManifest, ProviderProjection, RunOutcome, RunSpec, Side  # noqa: E402
from rondo_eval.docker_supervisor import DockerSupervisionError  # noqa: E402
from rondo_eval.terminal_bench.live import (  # noqa: E402
    BudgetedTerminalBenchResult,
    load_guardian_evidence_bundle,
)
from rondo_eval.terminal_bench import __main__ as terminal_bench_main  # noqa: E402
from rondo_eval.terminal_bench.pair import (  # noqa: E402
    PairMode,
    PairSequenceLedger,
    RunPublicationContext,
    load_pair_identity,
)
from rondo_eval.terminal_bench.results import (  # noqa: E402
    HarborResultError,
    UPSTREAM_CODEX,
    parse_single_task_result,
    publish_terminal_bench_failure,
    publish_terminal_bench_result,
)
from rondo_eval.terminal_bench.runner import (  # noqa: E402
    HostHarborResult,
    TerminalBenchRunError,
)


class TerminalBenchResultTests(unittest.TestCase):
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

    @staticmethod
    def _publication(
        *, side: Side = Side.CODEX, exit_code: int = 0
    ) -> RunPublicationContext:
        return RunPublicationContext(
            pair_id="p1-fix-git-pair-v4",
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
        )

    @staticmethod
    def _write_metadata(
        path: Path, *roles: str, provenance: str = "declared"
    ) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "requests": [
                        {
                            "role": role,
                            "role_provenance": provenance,
                            "declared_role": role if provenance == "declared" else None,
                            "inferred_role": role,
                            "contract_match": True,
                            "usage_valid": True,
                        }
                        for role in roles
                    ],
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
        provider = ProviderProjection(
            provider_id="openai",
            api="responses",
            base_url="https://api.openai.com/v1",
            api_key_env="OPENAI_API_KEY",
            main_model="gpt-5.6-luna",
            guardian_model="gpt-5.6-luna",
            guardian_effort="low",
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
            budget_snapshot={"runs": {run_id: {"spent_usd": "0.012345"}}},
            metadata_ready=True,
            evidence=(),
            redaction_secrets=("never-persist", "temporary-token"),
        )

    def _write_guardian_bundle(self, review_id: str = "review-1") -> str:
        bundle = self.trial / "agent" / "guardian-evidence" / review_id
        bundle.mkdir(parents=True)
        (bundle / "E_final.json").write_text(
            json.dumps(
                {
                    "instructions": "frozen guardian policy",
                    "input": [{"role": "user", "content": "approval evidence"}],
                    "tools": [],
                }
            ),
            encoding="utf-8",
        )
        (bundle / "meta.json").write_text(
            json.dumps(
                {
                    "review_id": review_id,
                    "guardian_source_baseline": "rust-v0.147.0",
                    "guardian_source_commit": UPSTREAM_CODEX["commit"],
                    "evidence": "e_final",
                    "decision": "approved",
                    "terminal_status": "approved",
                    "failure_reason": None,
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
            ),
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
            {"runs": {run_id: {"spent_usd": "0.000000"}}},
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
        self._write_metadata(metadata, "main")
        (self.trial / "agent").mkdir()
        (self.trial / "agent" / "codex.txt").write_text(
            '{"type":"turn.completed"}\n', encoding="utf-8"
        )
        (self.job / "job.log").write_text(
            "Authorization: Bearer must-not-be-archived\n", encoding="utf-8"
        )
        parsed = parse_single_task_result(self.jobs, host_returncode=0)
        target = publish_terminal_bench_result(
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

        target = publish_terminal_bench_failure(
            paths,
            writer=writer,
            run_id=run_id,
            side=Side.CODEX,
            git_commit="e" * 40,
            eval_harness_commit="f" * 40,
            manifest=live_result.prepared.spec.binary,
            budget_snapshot=live_result.budget_snapshot,
            metadata_path=self.root / "missing-api-metadata.json",
            outcome=RunOutcome.INFRA_FAILED,
            failure_stage="docker",
            publication=self._publication(exit_code=70),
            secrets=("never-persist",),
        )

        self.assertTrue((target / "run-failure.json").is_file())
        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertEqual(record["outcome"], "infra_failed")
        self.assertEqual(record["config"]["failure_stage"], "docker")
        self.assertEqual(
            record["cost"], {"estimated_usd": 0.012345, "actual_usd": None}
        )

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

    def test_completed_rondo_without_guardian_request_does_not_invent_e_final(self) -> None:
        run_id = "20260810-010000004-tb-rondo-r1"
        live_result = self._live_result(run_id)
        object.__setattr__(live_result.prepared.spec, "side", Side.RONDO)
        metadata = self.root / "work" / "api-metadata.json"
        self._write_metadata(metadata, "main")
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

        summary = json.loads((target / "run-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(summary["summary"]["api_request_roles"], {"main": 1, "guardian": 0})
        self.assertEqual(summary["summary"]["evidence"], [])
        self.assertEqual(summary["summary"]["s2_request_evidence_binding"], "not_triggered")

    def test_completed_rondo_guardian_request_requires_e_final(self) -> None:
        run_id = "20260810-010000006-tb-rondo-r1"
        live_result = self._live_result(run_id)
        object.__setattr__(live_result.prepared.spec, "side", Side.RONDO)
        metadata = self.root / "work" / "api-metadata.json"
        self._write_metadata(metadata, "main", "guardian")
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
        relative = self._write_guardian_bundle()
        observation, _e_final, _meta = load_guardian_evidence_bundle(self.jobs, relative)
        live_result = self._live_result(run_id)
        object.__setattr__(live_result.prepared.spec, "side", Side.RONDO)
        object.__setattr__(live_result, "evidence", (observation,))
        metadata = self.root / "work" / "api-metadata.json"
        self._write_metadata(metadata, "main", "guardian")
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
        archived_meta = json.loads(
            (target / "guardian-evidence/0001/meta.json").read_text(encoding="utf-8")
        )
        self.assertEqual(archived_meta["review_id"], "review-1")
        summary = json.loads((target / "run-summary.json").read_text(encoding="utf-8"))
        self.assertEqual(
            summary["summary"]["evidence"][0]["guardian_source_commit"],
            UPSTREAM_CODEX["commit"],
        )
        self.assertEqual(summary["summary"]["s2_request_evidence_binding"], "unbound")

    def test_guardian_meta_source_drift_is_rejected(self) -> None:
        relative = self._write_guardian_bundle()
        meta_path = self.trial / "agent/guardian-evidence/review-1/meta.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["guardian_source_commit"] = "0" * 40
        meta_path.write_text(json.dumps(meta), encoding="utf-8")

        with self.assertRaises(TerminalBenchRunError):
            load_guardian_evidence_bundle(self.jobs, relative)

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
        identity = load_pair_identity()
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
            )
            sequence.stage_paid_publication(
                run_id=run_id,
                eval_harness_commit=harness_commit,
                container_metrics={
                    "container_id": "a" * 64,
                    "cpu_usage_seconds": 1.0,
                    "peak_memory_bytes": 4096,
                },
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
        with patch.object(
            terminal_bench_main.RepoPaths, "discover", return_value=paths
        ), patch.object(
            terminal_bench_main, "load_pair_identity", return_value=identity
        ), patch.object(
            terminal_bench_main, "validate_results_worktree", return_value=self.root
        ), patch.object(
            terminal_bench_main, "load_runtime_config"
        ) as load_config, patch.object(
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
            load_config,
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
            pair_id="p1-fix-git-pair-v4",
            lock_sha256="9" * 64,
        )
        pair_identity.mode.return_value = SimpleNamespace(
            batch_id=terminal_bench_main.P1_BATCH_ID
        )
        pair_identity.slot_for.return_value = SimpleNamespace(
            paid_run_id=run_id,
            slot=2,
            round=1,
        )
        sequence = mock.MagicMock()
        sequence.__enter__.return_value = sequence
        with patch.object(terminal_bench_main.RepoPaths, "discover", return_value=paths), patch.object(
            terminal_bench_main, "load_pair_identity", return_value=pair_identity
        ), patch.object(
            terminal_bench_main, "validate_harbor_installation"
        ), patch.object(
            terminal_bench_main, "load_runtime_config", return_value=object()
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
                    terminal_bench_main.P1_BATCH_ID,
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
        )
        sequence.finish.assert_called_once_with(
            run_id=run_id,
            completed=False,
            eval_harness_commit="f" * 40,
        )
        safe_print.assert_called_once()
        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertEqual(record["outcome"], "infra_failed")
        self.assertEqual(record["config"]["failure_stage"], "docker")
        budget = json.loads(
            (self.root / "eval-data/budgets/p1-fix-git-20260810.json").read_text()
        )
        self.assertIn(run_id, budget["runs"])


if __name__ == "__main__":
    unittest.main()
