from __future__ import annotations

import copy
import json
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.full_model_training.contract import (  # noqa: E402
    FullModelTrainingError,
)
from rondo_eval.publication_critic.full_model_training.plan081_artifacts import (  # noqa: E402
    Plan081ArtifactStore,
)
from rondo_eval.publication_critic.full_model_training.plan081_observation import (  # noqa: E402
    TRAINING_OBSERVATION_SCHEMA,
)
from rondo_eval.publication_critic.full_model_training.plan090_artifacts import (  # noqa: E402
    Plan090ArtifactStore,
)
from rondo_eval.publication_critic.full_model_training.plan090_adapter import (  # noqa: E402
    verify_safetensors_storage_dtype,
)
from rondo_eval.publication_critic.full_model_training.plan090_bundle import (  # noqa: E402
    REQUIRED_SOURCE_MEMBERS,
    SOURCE_PATHS,
    create_source_archive,
    extract_source_archive,
    verify_source_archive,
)
from rondo_eval.publication_critic.full_model_training.plan090_cli import (  # noqa: E402
    PROCESS_RECEIPT_SCHEMA,
    _record_optional_receipt,
    _require_new_process,
    _require_task_owned_paths,
    validate_process_receipt,
)

SCRIPT_ROOT = REPO_ROOT / "training/publication-critic-plan090"
SCRIPTS = tuple(
    SCRIPT_ROOT / name
    for name in ("runpod-bootstrap.sh", "runpod-launch.sh", "runpod-worker.sh")
)


class Plan090DeliveryTests(unittest.TestCase):
    def test_checkpoint_storage_dtype_is_observed_from_safetensors_header(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            header = json.dumps(
                {
                    "model.weight": {
                        "dtype": "BF16",
                        "shape": [1],
                        "data_offsets": [0, 2],
                    }
                },
                separators=(",", ":"),
            ).encode()
            path = root / "model.safetensors"
            path.write_bytes(struct.pack("<Q", len(header)) + header + b"\0\0")
            self.assertEqual(
                verify_safetensors_storage_dtype(
                    root, expected_dtype="bfloat16", expected_tensor_count=1
                )["storage_dtypes"],
                ["BF16"],
            )
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan090_checkpoint_storage_dtype_invalid"
            ):
                verify_safetensors_storage_dtype(
                    root, expected_dtype="float32", expected_tensor_count=1
                )

    def test_optional_receipt_is_written_only_inside_task_root(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task = base / "task"
            task.mkdir()
            value = {"schema": "fixture", "status": "verified"}
            with patch.dict(os.environ, {"RONDO_PLAN090_TASK_ROOT": str(task)}):
                output = task / "receipts" / "fixture.json"
                self.assertEqual(_record_optional_receipt(value, output), value)
                self.assertEqual(json.loads(output.read_text()), value)
                with self.assertRaisesRegex(
                    FullModelTrainingError, "plan090_task_owned_path_required"
                ):
                    _record_optional_receipt(value, base / "outside.json")

    def test_training_observation_schema_is_scoped_to_plan090_store(self) -> None:
        value = {"schema": TRAINING_OBSERVATION_SCHEMA}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan081_observation_schema_invalid"
            ):
                Plan081ArtifactStore(root / "plan081").write_observation(
                    "training", value
                )
            receipt = Plan090ArtifactStore(root / "plan090").write_observation(
                "training", value
            )
            self.assertEqual(receipt["observation_id"], "training")

    def test_shell_entries_parse_and_reject_non_task_namespace(self) -> None:
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
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            result = subprocess.run(
                ["bash", str(SCRIPT_ROOT / "runpod-launch.sh"), "--", "true"],
                check=False,
                timeout=10,
                env={
                    **os.environ,
                    "RONDO_PLAN090_TASK_ROOT": str(root),
                    "RONDO_PLAN090_SOURCE_ROOT": str(source),
                    "RONDO_PLAN090_IMAGE_IDENTITY": "fixture",
                    "RONDO_PLAN090_LAUNCH_NAME": "fixture",
                    "RONDO_PLAN090_MAX_SECONDS": "60",
                },
            )
            self.assertEqual(result.returncode, 2)

    def test_task_write_guard_rejects_sibling_and_symlink_alias(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            task = base / "rondo-plan090-task"
            task.mkdir()
            sibling = base / "rondo-plan087-history"
            sibling.mkdir()
            alias = task / "alias"
            alias.symlink_to(sibling, target_is_directory=True)
            with patch.dict(os.environ, {"RONDO_PLAN090_TASK_ROOT": str(task)}):
                _require_task_owned_paths(task / "formal/result.json")
                for forbidden in (
                    sibling / "result.json",
                    task / "../rondo-plan087-history/result.json",
                    alias / "result.json",
                ):
                    with self.assertRaises(FullModelTrainingError):
                        _require_task_owned_paths(forbidden)
            self.assertEqual(list(sibling.iterdir()), [])

    def test_process_receipt_rejects_fake_completion_or_wrong_lineage(self) -> None:
        receipt = {
            "schema": PROCESS_RECEIPT_SCHEMA,
            "process_identity": {
                "instance_id": "1" * 32,
                "hostname": "fixture",
                "pid": 1,
            },
            "source_process_id": None,
            "status": "started",
            "global_step": 0,
            "run_id": "bf16-seed-20260901",
            "freeze_sha256": "2" * 64,
            "runtime_identity_sha256": "3" * 64,
            "source": {"commit": "4" * 40},
        }
        self.assertEqual(validate_process_receipt(receipt), receipt)
        for key, value in (("status", "completed"), ("global_step", 1)):
            drifted = copy.deepcopy(receipt)
            drifted[key] = value
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan090_process_receipt_invalid"
            ):
                validate_process_receipt(drifted)

        source = receipt["process_identity"]
        _require_new_process(
            source,
            {"instance_id": "5" * 32, "hostname": "fixture", "pid": 2},
        )
        for current in (
            {"instance_id": "5" * 32, "hostname": "other-pod", "pid": 2},
            {"instance_id": "5" * 32, "hostname": "fixture", "pid": 1},
        ):
            with self.assertRaisesRegex(
                FullModelTrainingError, "plan090_recovery_process_not_new"
            ):
                _require_new_process(source, current)

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
                    "user.name=Plan090 Test",
                    "-c",
                    "user.email=plan090@example.invalid",
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
