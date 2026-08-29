import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.directional_data import (  # noqa: E402
    DECISION_IMPLEMENTATION_BUNDLE_SHA256,
    DEVELOPMENT_REVISION,
    QUALIFICATION_SET_ID,
    DevelopmentRelease,
    DirectionalDataError,
    ValidatedPatch,
    _validate_remediation_implementation,
    load_directional_contracts,
    validate_development_review,
    validate_qualification_release_metadata,
)
from rondo_eval.publication_critic.identity import (  # noqa: E402
    canonical_json_bytes,
    sha256_file,
)
from rondo_eval.publication_critic.successor_build import (  # noqa: E402
    ACCEPTED_IMPLEMENTATION_BUNDLE_SHA256,
    ACCEPTED_IMPLEMENTATION_COMMIT,
)
from rondo_eval.publication_critic.successor_task import (  # noqa: E402
    DIMENSION_CLASSES,
    HARD_DIMENSIONS,
    STRUCTURED_OUTPUT_SCHEMA,
)


class PublicationCriticDirectionalDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.contracts = load_directional_contracts(REPO_ROOT)
        cls.development_root = REPO_ROOT / "training/publication-critic-v10"
        cls.qualification_root = (
            REPO_ROOT / "training/publication-critic-qualification-v1"
        )

    def test_design_binds_both_accepted_semantic_layers(self) -> None:
        accepted = self.contracts.design["accepted_task"]
        decision = self.contracts.design["decision_implementation"]
        self.assertEqual(
            accepted["accepted_implementation_commit"],
            ACCEPTED_IMPLEMENTATION_COMMIT,
        )
        self.assertEqual(
            accepted["accepted_implementation_bundle_sha256"],
            ACCEPTED_IMPLEMENTATION_BUNDLE_SHA256,
        )
        self.assertEqual(
            decision["bundle_sha256"],
            DECISION_IMPLEMENTATION_BUNDLE_SHA256,
        )
        self.assertEqual(
            self.contracts.design["development_release"]["physical_splits"],
            ["train", "validation"],
        )
        self.assertEqual(
            self.contracts.design["development_release"]["test_entrypoint"],
            "absent",
        )

    def test_development_consumer_has_no_test_entrypoint(self) -> None:
        release = DevelopmentRelease.open(
            self.development_root,
            repo_root=REPO_ROOT,
        )
        train_candidates, train_pairs = release.load_train()
        validation_candidates, validation_pairs = release.load_validation()
        self.assertEqual(release.manifest["dataset_revision"], DEVELOPMENT_REVISION)
        self.assertEqual(
            (len(train_candidates), len(train_pairs)),
            (162, 72),
        )
        self.assertEqual(
            (len(validation_candidates), len(validation_pairs)),
            (27, 12),
        )
        self.assertFalse(hasattr(release, "load_test"))
        self.assertEqual(set(release.manifest["splits"]), {"train", "validation"})
        self.assertFalse((self.development_root / "splits/test").exists())

    def test_validation_selector_binds_release_bytes_labels_and_row_order(self) -> None:
        release = DevelopmentRelease.open(
            self.development_root,
            repo_root=REPO_ROOT,
        )
        candidates, _ = release.load_validation()
        candidate_ids = tuple(row["candidate_id"] for row in candidates)
        config = release.select_and_freeze_validation_decision_config(
            validation_candidate_ids=candidate_ids,
            validation_output=self._structured_output(len(candidates)),
            candidate_head_margins=[self._margins()],
            model_artifact_sha256="1" * 64,
        )
        self.assertEqual(
            config["development_data"],
            {
                "revision": release.manifest["dataset_revision"],
                "manifest_sha256": sha256_file(self.development_root / "manifest.json"),
                "validation_candidates_sha256": release.manifest["splits"][
                    "validation"
                ]["candidates"]["sha256"],
            },
        )
        self.assertEqual(config["selection"]["validation_rows"], len(candidates))
        with self.assertRaisesRegex(
            DirectionalDataError,
            "candidate order",
        ):
            release.select_and_freeze_validation_decision_config(
                validation_candidate_ids=tuple(reversed(candidate_ids)),
                validation_output=self._structured_output(len(candidates)),
                candidate_head_margins=[self._margins()],
                model_artifact_sha256="1" * 64,
            )
        with self.assertRaisesRegex(ValueError, "1..1024"):
            release.select_and_freeze_validation_decision_config(
                validation_candidate_ids=candidate_ids,
                validation_output=self._structured_output(len(candidates)),
                candidate_head_margins=[],
                model_artifact_sha256="1" * 64,
            )

    def test_v9_test_is_only_a_sealed_metadata_binding(self) -> None:
        base = self.contracts.design["base_release"]
        manifest = self._load_json(REPO_ROOT / base["root"] / "manifest.json")
        auxiliary = base["sealed_auxiliary_holdout"]
        self.assertEqual(
            manifest["splits"]["test"]["candidates"]["sha256"],
            auxiliary["candidates_sha256"],
        )
        self.assertEqual(
            manifest["splits"]["test"]["pairs"]["sha256"],
            auxiliary["pairs_sha256"],
        )
        development = self._load_json(self.development_root / "manifest.json")
        self.assertEqual(
            development["holdout_policy"]["v9_auxiliary"],
            auxiliary,
        )
        self.assertEqual(
            development["holdout_policy"]["test_entrypoint"],
            "absent",
        )

    def test_shortcut_diagnostics_and_reviews_are_frozen(self) -> None:
        diagnostics = self._load_json(
            self.development_root / "shortcut-diagnostics.json"
        )
        self.assertEqual(diagnostics["commentary_cue_hits"], 0)
        self.assertEqual(diagnostics["exact_duplicates"], 0)
        self.assertEqual(diagnostics["cross_group_near_duplicates"], 0)
        self.assertLessEqual(diagnostics["scope_length_auc"]["train"], 0.72)
        self.assertLessEqual(diagnostics["scope_length_auc"]["validation"], 0.72)
        records = self._load_json(self.development_root / "patch-records.json")
        self.assertEqual(
            set(records),
            {"hard-boundaries", "continuity-context", "soft-combinations"},
        )
        self.assertTrue(
            all(record["verdict"] == "accept" for record in records.values())
        )

    def test_qualification_set_is_sealed_and_metadata_only(self) -> None:
        manifest = validate_qualification_release_metadata(
            self.qualification_root,
            contracts=self.contracts,
        )
        self.assertEqual(manifest["set_id"], QUALIFICATION_SET_ID)
        self.assertEqual(
            manifest["access"],
            "sealed_until_work_package_4; never training, validation, or decision selection",
        )
        self.assertEqual(manifest["files"]["candidates"]["rows"], 200)
        self.assertEqual(manifest["files"]["pairs"]["rows"], 100)
        self.assertEqual(manifest["files"]["family_lineage"]["rows"], 50)
        self.assertEqual(manifest["source"]["verdict"], "accept")

    def test_development_consumer_rejects_a_rogue_test_directory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "development"
            shutil.copytree(self.development_root, copied)
            (copied / "splits/test").mkdir()
            with self.assertRaisesRegex(
                DirectionalDataError,
                "contains a test split",
            ):
                DevelopmentRelease.open(copied, repo_root=REPO_ROOT)

    def test_qualification_metadata_rejects_frozen_contract_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "qualification"
            shutil.copytree(self.qualification_root, copied)
            with (copied / "design-lock.json").open("ab") as handle:
                handle.write(b"\n")
            with self.assertRaisesRegex(
                DirectionalDataError,
                "frozen directional design hash",
            ):
                validate_qualification_release_metadata(
                    copied,
                    contracts=self.contracts,
                )

    def test_qualification_metadata_rejects_wrong_formal_counts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            copied = Path(temporary) / "qualification"
            shutil.copytree(self.qualification_root, copied)
            manifest_path = copied / "manifest.json"
            manifest = self._load_json(manifest_path)
            manifest["files"]["candidates"]["rows"] = 199
            manifest_path.write_bytes(canonical_json_bytes(manifest))
            identity_path = copied / "release-identity.json"
            identity = self._load_json(identity_path)
            identity["manifest_sha256"] = sha256_file(manifest_path)
            identity_path.write_bytes(canonical_json_bytes(identity))
            with self.assertRaisesRegex(
                DirectionalDataError,
                "qualification manifest.files.candidates.rows",
            ):
                validate_qualification_release_metadata(
                    copied,
                    contracts=self.contracts,
                )

    def test_development_review_must_bind_patch_and_close_findings(self) -> None:
        patch = ValidatedPatch(
            module_id="soft-combinations",
            owner_role="plan098-module-owner-soft-combinations",
            source_sha256="1" * 64,
            replacements=(),
            tag_counts={},
        )
        review = {
            "schema": "rondo-publication-critic-directional-development-review@v1",
            "module_id": patch.module_id,
            "reviewer_role": "plan098-blind-reviewer-soft-combinations",
            "patch_sha256": patch.source_sha256,
            "verdict": "revise",
            "findings": ["open"],
            "checklist": {
                "base_binding": True,
                "immutable_labels_and_relations": True,
                "honest_counterexamples": True,
                "scope_counterexamples": True,
                "natural_multi_defects": True,
                "continuity_basis": True,
                "language_quality": True,
                "no_hidden_metadata": True,
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "review.json"
            path.write_bytes(canonical_json_bytes(review))
            with self.assertRaisesRegex(
                DirectionalDataError,
                "findings are not closed",
            ):
                validate_development_review(
                    path,
                    patch,
                    contracts=self.contracts,
                )
            review["verdict"] = "accept"
            review["findings"] = []
            review["patch_sha256"] = "2" * 64
            path.write_bytes(canonical_json_bytes(review))
            with self.assertRaisesRegex(
                DirectionalDataError,
                "patch hash",
            ):
                validate_development_review(
                    path,
                    patch,
                    contracts=self.contracts,
                )

    def test_directional_runtime_component_drift_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = Path("eval/rondo_eval/publication_critic/directional_data.py")
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(REPO_ROOT / relative, destination)
            identity = copy.deepcopy(
                self.contracts.design["remediation_implementation"]
            )
            _validate_remediation_implementation(identity, root)
            with destination.open("ab") as handle:
                handle.write(b"\n")
            with self.assertRaisesRegex(
                DirectionalDataError,
                "directional remediation component",
            ):
                _validate_remediation_implementation(identity, root)

    @staticmethod
    def _load_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def _margins() -> dict[str, dict[str, float]]:
        return {
            **{
                dimension: {"pass_over_fail_margin": 0.2}
                for dimension in HARD_DIMENSIONS
                if dimension != "conditional_continuity"
            },
            "conditional_continuity": {
                "pass_over_fail_margin": 0.2,
                "na_over_applicable_margin": 0.5,
            },
        }

    @staticmethod
    def _structured_output(batch_size: int) -> dict:
        return {
            "schema": STRUCTURED_OUTPUT_SCHEMA,
            "backbone_forward_count": 1,
            "batch_size": batch_size,
            "heads": {
                dimension: {
                    "classes": list(DIMENSION_CLASSES[dimension]),
                    "logits": [
                        (
                            [1.0, 0.0, 0.0]
                            if dimension == "conditional_continuity"
                            else [1.0, 0.0]
                        )
                        for _ in range(batch_size)
                    ],
                }
                for dimension in HARD_DIMENSIONS
            },
        }


if __name__ == "__main__":
    unittest.main()
