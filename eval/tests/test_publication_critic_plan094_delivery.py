from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.full_model_training.contract import (  # noqa: E402
    FullModelTrainingError,
)
from rondo_eval.publication_critic.full_model_training.plan094_bundle import (  # noqa: E402
    REQUIRED_SOURCE_MEMBERS,
    SOURCE_PATHS,
    create_source_archive,
    extract_source_archive,
    verify_source_archive,
)
from rondo_eval.publication_critic.full_model_training.plan094_cli import (  # noqa: E402
    _record_optional,
    _require_paid_gate,
    _require_task_owned_paths,
)
from rondo_eval.publication_critic.full_model_training.plan094_contract import (  # noqa: E402
    authorize_paid_segment,
    authorize_pod_lifecycle,
    validate_budget_snapshot,
)

SCRIPT_ROOT = REPO_ROOT / "training/publication-critic-plan094"
LIFECYCLE_GUARD = SCRIPT_ROOT / "runpod-lifecycle-guard.py"
GUARD_SPEC = importlib.util.spec_from_file_location(
    "plan094_runpod_lifecycle_guard", LIFECYCLE_GUARD
)
assert GUARD_SPEC is not None and GUARD_SPEC.loader is not None
guard = importlib.util.module_from_spec(GUARD_SPEC)
GUARD_SPEC.loader.exec_module(guard)
SCRIPTS = tuple(
    SCRIPT_ROOT / name
    for name in ("runpod-bootstrap.sh", "runpod-launch.sh", "runpod-worker.sh")
)


class Plan094DeliveryTests(unittest.TestCase):
    def test_stage_b_gate_and_task_root_are_fail_closed(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan094_stage_b_approval_required"
            ):
                _require_paid_gate()
        with patch.dict(os.environ, {"RONDO_PLAN094_STAGE_B_APPROVED": "1"}):
            _require_paid_gate()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task = base / "rondo-plan094-fixture"
            task.mkdir()
            sibling = base / "rondo-plan090-history"
            sibling.mkdir()
            alias = task / "alias"
            alias.symlink_to(sibling, target_is_directory=True)
            with patch.dict(os.environ, {"RONDO_PLAN094_TASK_ROOT": str(task)}):
                _require_task_owned_paths(task / "formal/result.json")
                with self.assertRaises(FullModelTrainingError):
                    _require_task_owned_paths(alias / "result.json")
                value = {"schema": "fixture"}
                output = task / "receipts/fixture.json"
                self.assertEqual(_record_optional(value, output), value)
                with self.assertRaisesRegex(
                    FullModelTrainingError, "plan094_task_owned_path_required"
                ):
                    _record_optional(value, sibling / "result.json")

    def test_shell_entries_parse_and_reject_unapproved_launch(self) -> None:
        for script in SCRIPTS:
            subprocess.run(["bash", "-n", str(script)], check=True, timeout=10)
        self.assertEqual(
            subprocess.run(
                ["bash", str(SCRIPT_ROOT / "runpod-worker.sh")],
                check=False,
                timeout=10,
            ).returncode,
            2,
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "rondo-plan094-fixture"
            source = root / "source"
            source.mkdir(parents=True)
            result = subprocess.run(
                ["bash", str(SCRIPT_ROOT / "runpod-launch.sh"), "--", "true"],
                check=False,
                timeout=10,
                env={
                    **os.environ,
                    "RONDO_PLAN094_TASK_ROOT": str(root),
                    "RONDO_PLAN094_SOURCE_ROOT": str(source),
                    "RONDO_PLAN094_IMAGE_IDENTITY": "fixture",
                    "RONDO_PLAN094_LAUNCH_NAME": "fixture",
                    "RONDO_PLAN094_MAX_SECONDS": "60",
                },
            )
            self.assertEqual(result.returncode, 2)
        bootstrap = (SCRIPT_ROOT / "runpod-bootstrap.sh").read_text()
        self.assertLess(
            bootstrap.index(
                "unset HF_TOKEN HUGGING_FACE_HUB_TOKEN HUGGINGFACEHUB_API_TOKEN"
            ),
            bootstrap.index('existing_model="${RONDO_PLAN094_EXISTING_MODEL_ROOT:-}"'),
        )
        launcher = (SCRIPT_ROOT / "runpod-launch.sh").read_text()
        self.assertLess(
            launcher.index("authorize-segment"), launcher.index("nohup setsid")
        )
        runbook = (SCRIPT_ROOT / "runbook.md").read_text()
        self.assertIn("nohup setsid env", runbook)
        subprocess.run(
            [sys.executable, "-B", str(LIFECYCLE_GUARD), "--help"],
            check=True,
            capture_output=True,
            timeout=10,
            env={**os.environ, "PYTHONPATH": str(EVAL_ROOT)},
        )

    def test_paid_segment_is_fresh_rate_bound_and_hard_capped(self) -> None:
        now = datetime.now(timezone.utc)

        def budget(captured_at: datetime) -> dict:
            return validate_budget_snapshot(
                {
                    "schema": "rondo-publication-critic-plan094-budget-snapshot-v1",
                    "captured_at": captured_at.isoformat().replace("+00:00", "Z"),
                    "live_balance_usd": 5.4,
                    "known_unsettled_usd": 0.1,
                    "stage_b_baseline_balance_usd": 5.4,
                    "stage_b_baseline_known_unsettled_usd": 0.1,
                    "conservative_task_cost_usd": 0.2,
                    "closure_reserve_usd": 0.5,
                    "projected_segment_and_closure_usd": 2.0,
                }
            )

        started_at = now.isoformat().replace("+00:00", "Z")
        lifecycle = authorize_pod_lifecycle(
            budget(now),
            pod_id="pod-094",
            pod_name="rondo-plan094-fixture",
            task_started_at=started_at,
            maximum_lifecycle_seconds=3600,
            compute_rate_usd_per_hour=0.99,
            storage_rate_usd_per_hour=0.006,
            now=now,
        )
        self.assertEqual(lifecycle["billable_seconds_upper_bound"], 4020)
        authorization = authorize_paid_segment(
            budget(now),
            lifecycle_authorization=lifecycle,
            maximum_seconds=1800,
            compute_rate_usd_per_hour=0.99,
            storage_rate_usd_per_hour=0.006,
            now=now,
        )
        self.assertEqual(authorization["billable_seconds_upper_bound"], 2220)
        self.assertLess(
            authorization["task_cost_and_closure_upper_bound_usd"], 5.0
        )
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan094_segment_outside_pod_lifecycle"
        ):
            authorize_paid_segment(
                budget(now),
                lifecycle_authorization=lifecycle,
                maximum_seconds=3550,
                compute_rate_usd_per_hour=0.99,
                storage_rate_usd_per_hour=0.006,
                now=now,
            )
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan094_pod_lifecycle_budget_not_authorized"
        ):
            authorize_pod_lifecycle(
                budget(now),
                pod_id="pod-094",
                pod_name="rondo-plan094-fixture",
                task_started_at=started_at,
                maximum_lifecycle_seconds=18000,
                compute_rate_usd_per_hour=0.99,
                storage_rate_usd_per_hour=0.006,
                now=now,
            )
        with self.assertRaisesRegex(
            FullModelTrainingError, "plan094_segment_budget_snapshot_stale"
        ):
            authorize_paid_segment(
                budget(now - timedelta(seconds=301)),
                lifecycle_authorization=lifecycle,
                maximum_seconds=60,
                compute_rate_usd_per_hour=0.99,
                storage_rate_usd_per_hour=0.006,
                now=now,
            )

    def test_detached_lifecycle_guard_uses_absolute_trigger_and_exact_terminal(
        self,
    ) -> None:
        now = datetime.now(timezone.utc)
        budget = validate_budget_snapshot(
            {
                "schema": "rondo-publication-critic-plan094-budget-snapshot-v1",
                "captured_at": now.isoformat().replace("+00:00", "Z"),
                "live_balance_usd": 5.4,
                "known_unsettled_usd": 0.1,
                "stage_b_baseline_balance_usd": 5.4,
                "stage_b_baseline_known_unsettled_usd": 0.1,
                "conservative_task_cost_usd": 0.2,
                "closure_reserve_usd": 0.5,
                "projected_segment_and_closure_usd": 2.0,
            }
        )
        authorization = authorize_pod_lifecycle(
            budget,
            pod_id="pod-094",
            pod_name="rondo-plan094-fixture",
            task_started_at=now.isoformat().replace("+00:00", "Z"),
            maximum_lifecycle_seconds=120,
            compute_rate_usd_per_hour=0.99,
            storage_rate_usd_per_hour=0.006,
            now=now,
        )
        clock = [now]
        calls = []

        def sleeper(seconds: float) -> None:
            clock[0] += timedelta(seconds=seconds)

        def terminate(receipt, captured_at, timeout):
            calls.append((receipt["pod_id"], captured_at, timeout))
            clock[0] += timedelta(seconds=250)
            return {
                "deleted_pod": {
                    "id": receipt["pod_id"],
                    "name": receipt["pod_name"],
                },
                "pod_count": 0,
                "compute_rate_usd_per_hour": 0.0,
            }

        result = guard.enforce_lifecycle(
            authorization,
            terminator=terminate,
            now=lambda: clock[0],
            sleeper=sleeper,
        )
        confirmed = now + timedelta(seconds=370)
        self.assertEqual(clock[0], confirmed)
        self.assertEqual(calls[0][0], "pod-094")
        self.assertEqual(calls[0][1], now + timedelta(seconds=120))
        self.assertEqual(result["status"], "pod_absent_confirmed")
        self.assertEqual(
            result["confirmed_at"],
            confirmed.isoformat().replace("+00:00", "Z"),
        )

        clock[0] = now

        def terminate_too_late(receipt, _captured_at, _timeout):
            clock[0] += timedelta(seconds=361)
            return {
                "deleted_pod": {
                    "id": receipt["pod_id"],
                    "name": receipt["pod_name"],
                },
                "pod_count": 0,
                "compute_rate_usd_per_hour": 0.0,
            }

        with self.assertRaisesRegex(
            guard.LifecycleGuardError, "terminal_succeeded_late"
        ):
            guard.enforce_lifecycle(
                authorization,
                terminator=terminate_too_late,
                now=lambda: clock[0],
                sleeper=sleeper,
            )

    def test_source_archive_round_trip_is_clean_narrow_and_secret_free(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            repo = temporary / "repo"
            repo.mkdir()
            listed = subprocess.run(
                [
                    "git",
                    "ls-files",
                    "--cached",
                    "--others",
                    "--exclude-standard",
                    "--",
                    *SOURCE_PATHS,
                ],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            for relative in listed:
                source = REPO_ROOT / relative
                destination = repo / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
            subprocess.run(["git", "add", "."], cwd=repo, check=True)
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Plan094 Test",
                    "-c",
                    "user.email=plan094@example.invalid",
                    "-c",
                    "core.hooksPath=/dev/null",
                    "commit",
                    "-qm",
                    "fixture",
                ],
                cwd=repo,
                check=True,
            )
            commit = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repo,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            archive = temporary / "source.tar"
            receipt = create_source_archive(repo, archive, source_commit=commit)
            with tarfile.open(archive, mode="r:") as handle:
                members = {item.name for item in handle if item.isfile()}
            self.assertTrue(members >= REQUIRED_SOURCE_MEMBERS)
            self.assertFalse(
                any(
                    member.endswith((".bin", ".safetensors"))
                    or ".env.local" in member
                    or member.startswith("eval-data/")
                    or "runpod-create" in member
                    for member in members
                )
            )
            extracted = temporary / "extracted"
            self.assertEqual(
                extract_source_archive(
                    archive,
                    extracted,
                    expected_sha256=receipt["archive_sha256"],
                    expected_commit=commit,
                ),
                receipt,
            )
            self.assertEqual(
                verify_source_archive(
                    archive, extracted, exact_tree=True, expected_commit=commit
                ),
                receipt,
            )


if __name__ == "__main__":
    unittest.main()
