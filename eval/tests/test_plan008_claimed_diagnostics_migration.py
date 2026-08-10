from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.migrations import plan008_claimed_diagnostics as migration  # noqa: E402


class Plan008ClaimedDiagnosticsMigrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source, self.ledger, self.evidence = self._fixture()
        self.source_patch = mock.patch.object(
            migration, "_SOURCE_SHA256", self._sha(self.source)
        )
        self.ledger_patch = mock.patch.object(
            migration, "_LEDGER_SHA256", self._sha(self.ledger)
        )
        self.evidence_patch = mock.patch.object(migration, "_EVIDENCE", self.evidence)
        self.source_patch.start()
        self.ledger_patch.start()
        self.evidence_patch.start()

    def tearDown(self) -> None:
        self.evidence_patch.stop()
        self.ledger_patch.stop()
        self.source_patch.stop()
        self.temp.cleanup()

    def test_preview_is_read_only_and_reports_three_pending_corrections(self) -> None:
        ledger_path = self.root / "eval-data/budgets/p1-fix-git-20260810.json"
        before = ledger_path.read_bytes()
        prepared = migration.prepare_migration(
            self.root, self.root, source_bytes=self.source
        )
        output = migration.preview(prepared)
        self.assertEqual([item["status"] for item in output["runs"]], ["pending"] * 3)
        self.assertEqual(ledger_path.read_bytes(), before)
        self.assertFalse((self.root / "eval/results/runs.jsonl").exists())
        self.assertFalse((self.root / "eval-data/runs").exists())

    def test_apply_is_atomic_idempotent_and_does_not_change_retained_evidence(self) -> None:
        ledger_path = self.root / "eval-data/budgets/p1-fix-git-20260810.json"
        work_root = self.root / "eval-data/work"
        before_ledger = ledger_path.read_bytes()
        before_work = self._tree_hash(work_root)

        applied = migration.apply_migration(
            self.root, self.root, source_bytes=self.source
        )
        self.assertEqual([item.status for item in applied], ["already_applied"] * 3)
        rows = [
            json.loads(line)
            for line in (self.root / "eval/results/runs.jsonl").read_text().splitlines()
        ]
        self.assertEqual([row["outcome"] for row in rows], ["infra_failed"] * 3)
        self.assertEqual([row["tasks"][0]["attribution"] for row in rows], ["infra"] * 3)
        self.assertEqual([row["metrics"] for row in rows], [None] * 3)
        self.assertEqual(
            [row["config"]["legacy_migration"] for row in rows],
            [migration.MIGRATION_ID] * 3,
        )
        migration.apply_migration(self.root, self.root, source_bytes=self.source)
        self.assertEqual(len((self.root / "eval/results/runs.jsonl").read_text().splitlines()), 3)
        self.assertEqual(ledger_path.read_bytes(), before_ledger)
        self.assertEqual(self._tree_hash(work_root), before_work)

    def test_changed_retained_result_blocks_without_publication(self) -> None:
        run_id = next(iter(self.evidence))
        job_result = next(
            (self.root / "eval-data/work" / run_id / "staging/jobs").glob("*/result.json")
        )
        job_result.write_text("{}\n", encoding="utf-8")
        with self.assertRaisesRegex(migration.MigrationError, "digest differs"):
            migration.apply_migration(self.root, self.root, source_bytes=self.source)
        self.assertFalse((self.root / "eval/results/runs.jsonl").exists())

    def _fixture(self):
        run_ids = tuple(migration._EVIDENCE)
        records = []
        evidence = {}
        ledger_runs = {}
        for number, run_id in enumerate(run_ids, start=1):
            record = {
                "schema_version": 1,
                "run_id": run_id,
                "created_at": f"2026-08-09T18:3{number}:00Z",
                "track": "tb",
                "side": "codex",
                "git_commit": "a" * 40,
                "git_dirty": False,
                "binary_sha256": "b" * 64,
                "upstream_codex": {
                    "tag": "rust-v0.147.0",
                    "commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
                    "workspace_lock_normalization": "135 workspace packages: 0.0.0 -> 0.147.0",
                },
                "config": {"model": "gpt-5.6-luna"},
                "outcome": "agent_failed",
                "summary": {"success_rate": 0.0, "infra_failed": 0},
                "tasks": [
                    {
                        "task_id": "terminal-bench/fix-git",
                        "outcome": "fail",
                        "attribution": "agent",
                        "duration_s": 2.0,
                    }
                ],
                "metrics": None,
                "cost": {"estimated_usd": 0.0, "actual_usd": 0.0},
                "artifacts": f"eval-data/runs/{run_id}",
                "notes": "provisional",
            }
            row = json.dumps(record, sort_keys=True, separators=(",", ":")).encode()
            records.append(row)
            jobs = self.root / "eval-data/work" / run_id / "staging/jobs/job"
            trial = jobs / "trial"
            trial.mkdir(parents=True)
            job_result = {
                "stats": {"n_completed_trials": 1, "n_errored_trials": 1}
            }
            trial_result = {
                "task_name": "terminal-bench/fix-git",
                "started_at": "2026-08-09T18:31:00Z",
                "finished_at": "2026-08-09T18:31:02Z",
                "exception_info": {
                    "exception_type": "FixtureInfraError",
                    "exception_message": "fixture infrastructure marker",
                },
            }
            job_bytes = (json.dumps(job_result, sort_keys=True) + "\n").encode()
            trial_bytes = (json.dumps(trial_result, sort_keys=True) + "\n").encode()
            (jobs / "result.json").write_bytes(job_bytes)
            (trial / "result.json").write_bytes(trial_bytes)
            (trial / "config.json").write_text(
                json.dumps(
                    {
                        "agent": {
                            "kwargs": {
                                "binary_sha256": "b" * 64,
                                "binary_source_commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            evidence[run_id] = migration._EvidenceSpec(
                row_sha256=self._sha(row),
                job_sha256=self._sha(job_bytes),
                trial_sha256=self._sha(trial_bytes),
                exception_type="FixtureInfraError",
                message_marker="infrastructure marker",
            )
            ledger_runs[run_id] = {
                "cap_usd": "5.000000",
                "spent_usd": "0.000000",
                "stopped": False,
                "stop_reason": None,
                "requests": {},
            }
        source = b"\n".join(records) + b"\n"
        ledger = (
            json.dumps(
                {
                    "schema_version": 1,
                    "batch_id": "p1-fix-git-20260810",
                    "total_cap_usd": "20.000000",
                    "max_runs": 4,
                    "default_run_cap_usd": "5.000000",
                    "runs": ledger_runs,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode()
        ledger_path = self.root / "eval-data/budgets/p1-fix-git-20260810.json"
        ledger_path.parent.mkdir(parents=True)
        ledger_path.write_bytes(ledger)
        return source, ledger, evidence

    @staticmethod
    def _sha(contents: bytes) -> str:
        return hashlib.sha256(contents).hexdigest()

    @staticmethod
    def _tree_hash(root: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(root.rglob("*")):
            if path.is_file():
                digest.update(path.relative_to(root).as_posix().encode())
                digest.update(path.read_bytes())
        return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
