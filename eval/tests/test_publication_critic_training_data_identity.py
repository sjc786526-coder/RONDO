from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.contract import load_fixed_input_contract  # noqa: E402
from rondo_eval.publication_critic.identity import (  # noqa: E402
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from rondo_eval.publication_critic.training_data import (  # noqa: E402
    DatasetConsumer,
    TrainingDataError,
    build_freeze_manifest,
    build_memberships,
    verify_freeze_manifest,
)
from rondo_eval.publication_critic.training_data import input_identity as identity_module  # noqa: E402
from rondo_eval.publication_critic.training_data.input_identity import (  # noqa: E402
    TOKENIZER_ONLY_FILES,
    Plan054TrainingInput,
    load_plan054_training_input,
    verify_plan054_tokenizer_snapshot,
)


TEACHER_IDENTITY = {
    "model": "gpt-5.6-sol",
    "reasoning_effort": "xhigh",
    "role": "identity unit test",
    "prompt_sha256": "a" * 64,
    "date": "2026-08-23",
    "session_identity": "identity-test-session",
}


class PublicationCriticTrainingIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        fixture = json.loads(
            (REPO_ROOT / "eval/fixtures/publication-critic-v1/packets.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )
        cls.base_packet = fixture["packet"]
        cls.verified_input = load_plan054_training_input(REPO_ROOT)

    def test_plan054_identity_is_derived_from_the_verified_v4_freeze(self) -> None:
        design_lock = json.loads(
            (
                REPO_ROOT
                / "eval/templates/publication-critic/training-data-design-lock-v1.json"
            ).read_text(encoding="utf-8")
        )
        fixed = load_fixed_input_contract(REPO_ROOT)
        self.assertEqual(
            dict(self.verified_input.input_identity),
            design_lock["input_identity"],
        )
        self.assertEqual(self.verified_input.rubric, fixed.rubric)
        self.assertEqual(
            set(self.verified_input.tokenizer_file_sha256),
            set(TOKENIZER_ONLY_FILES),
        )

    def test_default_consumer_physically_retains_only_train_rows(self) -> None:
        packets, supervision, pairs, membership = self._rows()
        consumer = DatasetConsumer.from_rows(
            packets,
            supervision,
            pairs,
            membership,
            repo_root=REPO_ROOT,
        )
        self.assertEqual(len(consumer.packets), 2)
        self.assertEqual(len(consumer.supervision), 2)
        self.assertEqual(len(consumer.pairs), 1)
        self.assertEqual(
            {row["proposed_split"] for row in consumer.supervision.values()},
            {"train"},
        )
        self.assertEqual(len(consumer.stage("C2")["pairs"]), 1)
        with self.assertRaisesRegex(TrainingDataError, "explicit evaluation mode"):
            consumer.evaluation_split("unseen_test")

        evaluation_consumer = DatasetConsumer.from_rows(
            packets,
            supervision,
            pairs,
            membership,
            repo_root=REPO_ROOT,
            allow_evaluation=True,
        )
        self.assertEqual(len(evaluation_consumer.packets), 6)
        self.assertEqual(len(evaluation_consumer.supervision), 6)
        self.assertEqual(len(evaluation_consumer.pairs), 3)
        self.assertEqual(len(evaluation_consumer.evaluation_split("validation")), 2)
        self.assertEqual(len(evaluation_consumer.evaluation_split("unseen_test")), 2)

    def test_model_inputs_have_no_free_rubric_parameter(self) -> None:
        packets, supervision, pairs, membership = self._rows()
        consumer = DatasetConsumer.from_rows(
            packets,
            supervision,
            pairs,
            membership,
            repo_root=REPO_ROOT,
        )
        rendered = consumer.model_inputs("C1")
        self.assertEqual(len(rendered), 2)
        self.assertIn(
            self.verified_input.rubric,
            rendered[0]["messages"][0]["content"],
        )
        with self.assertRaises(TypeError):
            consumer.model_inputs("C1", "WRONG RUBRIC")  # type: ignore[call-arg]

    def test_frozen_consumer_always_derives_expected_input_identity(self) -> None:
        packets, supervision, pairs, membership = self._rows()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, rows in (
                ("packets.jsonl", packets),
                ("supervision.jsonl", supervision),
                ("pairs.jsonl", pairs),
            ):
                root.joinpath(name).write_text(
                    "".join(
                        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                        for row in rows
                    ),
                    encoding="utf-8",
                )
            root.joinpath("membership.json").write_text(
                json.dumps(membership, sort_keys=True),
                encoding="utf-8",
            )
            relative_paths = [
                "packets.jsonl",
                "supervision.jsonl",
                "pairs.jsonl",
                "membership.json",
            ]
            manifest = build_freeze_manifest(
                root,
                relative_paths,
                dataset_revision="identity-test-v1",
                input_identity=self.verified_input.input_identity,
                design_lock_sha256="b" * 64,
                generation_commit="c" * 40,
                contracts={"identity": "plan054-v4"},
                statistics={"candidates": 6},
            )
            root.joinpath("manifest.json").write_text(
                json.dumps(manifest, sort_keys=True),
                encoding="utf-8",
            )
            consumer = DatasetConsumer.from_frozen_directory(
                root,
                repo_root=REPO_ROOT,
            )
            self.assertEqual(len(consumer.supervision), 2)
            verify_freeze_manifest(
                root,
                manifest,
                expected_input_identity=self.verified_input.input_identity,
            )
            with self.assertRaises(TypeError):
                verify_freeze_manifest(root, manifest)  # type: ignore[call-arg]

            manifest["input_identity"] = {"caller_selected": "wrong"}
            core = {
                key: value
                for key, value in manifest.items()
                if key != "content_sha256"
            }
            manifest["content_sha256"] = sha256_bytes(canonical_json_bytes(core))
            root.joinpath("manifest.json").write_text(
                json.dumps(manifest, sort_keys=True),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(TrainingDataError, "input identity drifted"):
                DatasetConsumer.from_frozen_directory(root, repo_root=REPO_ROOT)

    def test_tokenizer_snapshot_hashes_only_the_seven_locked_assets(self) -> None:
        revision = "tokenizer-revision-for-test"
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "model-cache"
            blobs = cache / "blobs"
            snapshot = cache / "snapshots" / revision
            blobs.mkdir(parents=True)
            snapshot.mkdir(parents=True)
            expected: dict[str, str] = {}
            for index, relative in enumerate(TOKENIZER_ONLY_FILES):
                blob = blobs / relative
                blob.write_bytes(f"locked-tokenizer-{index}".encode("ascii"))
                snapshot.joinpath(relative).symlink_to(
                    Path("../../blobs") / relative
                )
                expected[relative] = sha256_file(blob)
            snapshot.joinpath("model.safetensors").write_bytes(b"must-not-be-read")
            verified = self._tokenizer_identity(revision, expected)
            with (
                mock.patch.object(
                    identity_module,
                    "load_plan054_training_input",
                    return_value=verified,
                ),
                mock.patch.object(
                    identity_module,
                    "sha256_file",
                    wraps=sha256_file,
                ) as digest,
            ):
                observed = verify_plan054_tokenizer_snapshot(
                    snapshot,
                    repo_root=REPO_ROOT,
                )
            self.assertIs(observed, verified)
            hashed_names = [call.args[0].name for call in digest.call_args_list]
            self.assertCountEqual(hashed_names, TOKENIZER_ONLY_FILES)
            self.assertNotIn("model.safetensors", hashed_names)

    def test_tokenizer_snapshot_rejects_root_symlink_and_asset_drift(self) -> None:
        revision = "tokenizer-revision-for-test"
        expected = {
            relative: sha256_bytes(f"locked-{relative}".encode("ascii"))
            for relative in TOKENIZER_ONLY_FILES
        }
        verified = self._tokenizer_identity(revision, expected)
        with tempfile.TemporaryDirectory() as directory:
            cache = Path(directory) / "model-cache"
            snapshot = cache / "snapshots" / revision
            snapshot.mkdir(parents=True)
            for relative in TOKENIZER_ONLY_FILES:
                snapshot.joinpath(relative).write_bytes(
                    f"locked-{relative}".encode("ascii")
                )
            alias_root = Path(directory) / "alias"
            alias_root.mkdir()
            alias = alias_root / revision
            alias.symlink_to(snapshot, target_is_directory=True)
            with mock.patch.object(
                identity_module,
                "load_plan054_training_input",
                return_value=verified,
            ):
                with self.assertRaisesRegex(TrainingDataError, "root must not be a symlink"):
                    verify_plan054_tokenizer_snapshot(alias, repo_root=REPO_ROOT)

                snapshot.joinpath("vocab.json").write_bytes(b"drifted")
                with self.assertRaisesRegex(TrainingDataError, "identity drifted: vocab.json"):
                    verify_plan054_tokenizer_snapshot(snapshot, repo_root=REPO_ROOT)

    @staticmethod
    def _tokenizer_identity(
        revision: str,
        expected: dict[str, str],
    ) -> Plan054TrainingInput:
        return Plan054TrainingInput(
            input_identity={"tokenizer_revision": revision},
            rubric="fixed rubric",
            tokenizer_file_sha256=expected,
        )

    def _rows(self) -> tuple[list[dict], list[dict], list[dict], dict]:
        packets: list[dict] = []
        supervision: list[dict] = []
        pairs: list[dict] = []
        for split in ("train", "validation", "unseen_test"):
            scenario = f"scenario-{split}"
            preferred = f"candidate-{split}-pass"
            dispreferred = f"candidate-{split}-rewrite"
            for candidate_id, label in (
                (preferred, "PASS"),
                (dispreferred, "REWRITE"),
            ):
                packet = copy.deepcopy(self.base_packet)
                packet["candidate"]["summary"] = (
                    f"{split} completed with a consistent result."
                    if label == "PASS"
                    else f"{split} completed and also did not complete."
                )
                packets.append(
                    {
                        "schema_version": 1,
                        "candidate_id": candidate_id,
                        "packet": packet,
                    }
                )
                defects = [] if label == "PASS" else ["internal_consistency"]
                supervision.append(
                    {
                        "schema_version": 1,
                        "candidate_id": candidate_id,
                        "scenario_id": scenario,
                        "source_group": f"source-{split}",
                        "scenario_group": scenario,
                        "template_group": f"template-{split}",
                        "proposed_split": split,
                        "binary_label": label,
                        "publication_class": "new_event_completed",
                        "completion_state": "completed",
                        "hard_focus": None if label == "PASS" else "internal_consistency",
                        "defects": defects,
                        "slices": [
                            "identity_test",
                            "continuity_not_applicable",
                            "evidence_not_applicable",
                        ],
                        "actor_role": "root",
                        "style": "formal",
                        "length_bucket": "short",
                        "unicode": False,
                        "generator_identity": TEACHER_IDENTITY,
                        "reviewer_identity": TEACHER_IDENTITY,
                        "review_status": "accept",
                    }
                )
            pairs.append(
                {
                    "schema_version": 1,
                    "pair_id": f"pair-{split}",
                    "kind": "boundary",
                    "scenario_id": scenario,
                    "preferred_candidate_id": preferred,
                    "dispreferred_candidate_id": dispreferred,
                    "target_dimension": "internal_consistency",
                    "soft_preference": None,
                    "review_status": "accept",
                }
            )
        membership = build_memberships(
            supervision,
            pairs,
            dataset_revision="identity-test-v1",
        )
        return packets, supervision, pairs, membership


if __name__ == "__main__":
    unittest.main()
