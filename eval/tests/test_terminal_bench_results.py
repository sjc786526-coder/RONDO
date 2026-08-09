from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.config import RepoPaths  # noqa: E402
from rondo_eval.contracts import BinaryManifest, ProviderProjection, RunOutcome, RunSpec, Side  # noqa: E402
from rondo_eval.terminal_bench.live import BudgetedTerminalBenchResult  # noqa: E402
from rondo_eval.terminal_bench.results import (  # noqa: E402
    HarborResultError,
    UPSTREAM_CODEX,
    parse_single_task_result,
    publish_terminal_bench_result,
)
from rondo_eval.terminal_bench.runner import HostHarborResult  # noqa: E402


class TerminalBenchResultTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.jobs = self.root / "work" / "staging" / "jobs"
        self.job = self.jobs / "2026-08-10__01-00-00"
        self.trial = self.job / "fix-git__abc"
        self.trial.mkdir(parents=True)
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
        (self.job / "result.json").write_text(json.dumps(self.job_result), encoding="utf-8")
        (self.trial / "result.json").write_text(json.dumps(self.trial_result), encoding="utf-8")
        (self.job / "job.log").write_text("safe log\n", encoding="utf-8")
        (self.job / "config.json").write_text("{}\n", encoding="utf-8")

    def _live_result(self, run_id: str) -> BudgetedTerminalBenchResult:
        binary = BinaryManifest(
            path=str(self.root / "codex"),
            sha256="a" * 64,
            source_commit=UPSTREAM_CODEX["commit"],
            source_dirty=False,
            rust_toolchain="rustc 1.95.0",
            build_command=("supervised", "build"),
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

    def test_completed_requires_job_trial_and_reward_not_just_host_zero(self) -> None:
        parsed = parse_single_task_result(self.jobs, host_returncode=0)
        self.assertEqual(parsed.outcome, RunOutcome.COMPLETED)
        self.assertEqual(parsed.task_outcome, "pass")
        self.assertEqual(parsed.duration_seconds, 5.0)
        self.assertEqual((parsed.input_tokens, parsed.cached_tokens, parsed.output_tokens), (100, 20, 10))

    def test_errored_trial_is_agent_failed_and_missing_reward_is_zero(self) -> None:
        self.job_result["stats"]["n_completed_trials"] = 0
        self.job_result["stats"]["n_errored_trials"] = 1
        self.trial_result["exception_info"] = {"type": "agent_error"}
        self.trial_result["verifier_result"] = None
        self._write_results()
        parsed = parse_single_task_result(self.jobs, host_returncode=0)
        self.assertEqual((parsed.outcome, parsed.reward), (RunOutcome.AGENT_FAILED, 0.0))

    def test_ambiguous_or_malformed_results_fail_closed(self) -> None:
        (self.jobs / "second-job").mkdir()
        with self.assertRaises(HarborResultError):
            parse_single_task_result(self.jobs, host_returncode=0)
        (self.jobs / "second-job").rmdir()
        self.trial_result["task_name"] = "some-other-task"
        self._write_results()
        with self.assertRaises(HarborResultError):
            parse_single_task_result(self.jobs, host_returncode=0)

    def test_publication_copies_private_tree_and_appends_strict_index(self) -> None:
        run_id = "20260810-010000001-tb-codex-r1"
        metadata = self.root / "work" / "api-metadata.json"
        metadata.write_text('{"schema_version":1,"requests":[{"safe":true}]}\n', encoding="utf-8")
        parsed = parse_single_task_result(self.jobs, host_returncode=0)
        target = publish_terminal_bench_result(
            RepoPaths(self.root, self.root),
            results_worktree_root=self.root,
            run_id=run_id,
            side=Side.CODEX,
            git_commit="e" * 40,
            live_result=self._live_result(run_id),
            parsed=parsed,
            metadata_path=metadata,
        )
        self.assertTrue((target / "harbor/jobs/2026-08-10__01-00-00/job.log").is_file())
        self.assertTrue((target / "api-metadata.json").is_file())
        record = json.loads((self.root / "eval/results/runs.jsonl").read_text())
        self.assertEqual(record["upstream_codex"], UPSTREAM_CODEX)
        self.assertEqual(record["outcome"], "completed")
        self.assertEqual(record["cost"], {"estimated_usd": 0.012345, "actual_usd": 0.012345})


if __name__ == "__main__":
    unittest.main()
