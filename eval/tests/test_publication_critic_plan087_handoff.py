from __future__ import annotations

import os
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rondo_eval.publication_critic.full_model_training.contract import (
    FullModelTrainingError,
)
from rondo_eval.publication_critic.full_model_training.plan087_bundle import (
    REQUIRED_SOURCE_MEMBERS,
    SOURCE_PATHS,
    create_source_archive,
    extract_source_archive,
    verify_source_archive,
)
from rondo_eval.publication_critic.full_model_training.plan087_cli import (
    _require_task_owned_paths,
)
from rondo_eval.publication_critic.full_model_training.plan087_handoff import (
    MAX_FILE_BYTES,
    create_small_handoff_manifest,
    stage_small_handoff,
    verify_small_handoff,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


class Plan087HandoffTests(unittest.TestCase):
    def test_small_handoff_stages_and_verifies_exact_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "rondo-plan087-fixture"
            (root / "formal-search/results").mkdir(parents=True)
            (root / "formal-search/manifests").mkdir(parents=True)
            (root / "logs").mkdir()
            (root / "formal-search/results/route.json").write_text(
                '{"route":"a"}\n', encoding="utf-8"
            )
            (root / "formal-search/manifests/selected-checkpoint.json").write_text(
                '{"sha256":"abc"}\n', encoding="utf-8"
            )
            (root / "logs/search.log").write_text("bounded log\n", encoding="utf-8")
            manifest = create_small_handoff_manifest(
                root,
                [
                    ("route_result", "formal-search/results/route.json"),
                    (
                        "checkpoint_manifest",
                        "formal-search/manifests/selected-checkpoint.json",
                    ),
                    ("log", "logs/search.log"),
                ],
            )
            staging = root / "handoff-staging"
            stage_small_handoff(root, manifest, staging)
            observed = verify_small_handoff(
                staging, staging / "handoff-manifest.json", exact_tree=True
            )
            self.assertEqual(observed, manifest)
            (staging / "extra.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan087_handoff_exact_tree_invalid"
            ):
                verify_small_handoff(
                    staging, staging / "handoff-manifest.json", exact_tree=True
                )

    def test_handoff_rejects_weight_symlink_and_oversize(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "formal-search/results").mkdir(parents=True)
            (root / "logs").mkdir()
            weight = root / "formal-search/results/model.safetensors"
            weight.write_bytes(b"not-a-real-weight")
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan087_handoff_member_invalid"
            ):
                create_small_handoff_manifest(
                    root, [("route_result", "formal-search/results/model.safetensors")]
                )

            source = root / "formal-search/results/result.json"
            source.write_text("{}\n", encoding="utf-8")
            (root / "logs/link.json").symlink_to(source)
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan087_handoff_symlink_rejected"
            ):
                create_small_handoff_manifest(root, [("receipt", "logs/link.json")])

            oversized = root / "logs/oversized.log"
            with oversized.open("wb") as handle:
                handle.truncate(MAX_FILE_BYTES + 1)
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan087_handoff_file_too_large"
            ):
                create_small_handoff_manifest(root, [("log", "logs/oversized.log")])

    def test_task_write_guard_rejects_sibling_parent_and_symlink_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task = base / "rondo-plan087-task"
            task.mkdir()
            sibling = base / "rondo-plan082-history"
            sibling.mkdir()
            alias = task / "alias"
            alias.symlink_to(sibling, target_is_directory=True)
            with patch.dict(os.environ, {"RONDO_PLAN087_TASK_ROOT": str(task)}):
                _require_task_owned_paths(task / "results/result.json")
                for forbidden in (
                    sibling / "result.json",
                    task / "../rondo-plan082-history/result.json",
                    alias / "result.json",
                ):
                    with self.assertRaises(FullModelTrainingError):
                        _require_task_owned_paths(forbidden)
            self.assertEqual(list(sibling.iterdir()), [])

    def test_source_archive_round_trip_is_committed_narrow_and_secret_free(
        self,
    ) -> None:
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
                    "user.name=Plan087 Test",
                    "-c",
                    "user.email=plan087@example.invalid",
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
            self.assertEqual(receipt["commit"], commit)
            with tarfile.open(archive, mode="r:") as handle:
                members = {item.name for item in handle if item.isfile()}
            self.assertTrue(members >= REQUIRED_SOURCE_MEMBERS)
            self.assertFalse(
                any(
                    member.endswith(".safetensors")
                    or member.endswith(".bin")
                    or ".env.local" in member
                    or member.startswith("eval-data/")
                    for member in members
                )
            )
            extracted = temporary / "extracted"
            extracted_receipt = extract_source_archive(
                archive,
                extracted,
                expected_sha256=receipt["archive_sha256"],
                expected_commit=commit,
            )
            self.assertEqual(extracted_receipt, receipt)
            self.assertEqual(
                verify_source_archive(
                    archive, extracted, exact_tree=True, expected_commit=commit
                ),
                receipt,
            )

            tracked = repo / "training/publication-critic-plan087/README.md"
            tracked.write_text(tracked.read_text(encoding="utf-8") + "dirty\n")
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan087_source_tree_dirty"
            ):
                create_source_archive(
                    repo, temporary / "dirty.tar", source_commit=commit
                )
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan087_source_commit_mismatch"
            ):
                create_source_archive(
                    repo, temporary / "wrong.tar", source_commit="0" * 40
                )


if __name__ == "__main__":
    unittest.main()
