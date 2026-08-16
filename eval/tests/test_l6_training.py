from __future__ import annotations

import copy
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from rondo_eval.local_approval import l6_training


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent


def _dependency_identity(recipe: dict, *, status: str) -> dict:
    pins = {}
    for line in (
        REPO_ROOT / "training/local-approval-l6/dependencies-candidate-v1.txt"
    ).read_text().splitlines():
        if line and not line.startswith("#"):
            name, version = line.split("==", 1)
            pins[name] = version
    return {
        "schema_version": 1,
        "status": status,
        "packages": pins,
        "python_version": "3.11.13",
        "cuda_version": "12.8",
        "container_image": recipe["container"]["image"],
    }


class ProjectionTests(unittest.TestCase):
    def test_frozen_train_projects_exactly_470_records(self) -> None:
        rows, raw = l6_training.build_training_projection(REPO_ROOT)
        self.assertEqual(len(rows), 470)
        self.assertEqual(l6_training._sha256(raw), l6_training.TRAIN_PROJECTION_SHA256)
        self.assertEqual(len({row["source_sample_id"] for row in rows}), 470)
        self.assertTrue(all(row["messages"][0]["role"] == "system" for row in rows))
        self.assertTrue(all(json.loads(row["completion"])["outcome"] in {"allow", "deny"} for row in rows))

    def test_non_train_source_row_is_rejected(self) -> None:
        rows, _ = l6_training._load_jsonl(REPO_ROOT / l6_training.TRAIN_RELATIVE_PATH)
        changed = copy.deepcopy(rows[0])
        changed["split"] = "validation"
        with self.assertRaisesRegex(l6_training.L6TrainingError, "source_row_binding_invalid"):
            l6_training.project_source_row(changed)


class BundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.base = Path(cls.temporary.name) / "bundle"
        l6_training.prepare_bundle(REPO_ROOT, cls.base)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def _copy(self, name: str) -> Path:
        target = Path(self.temporary.name) / name
        shutil.copytree(self.base, target)
        return target

    def test_bundle_is_exact_train_only_allowlist(self) -> None:
        result = l6_training.verify_bundle(self.base)
        manifest = json.loads((self.base / "bundle-manifest.json").read_text())
        self.assertEqual(result["train_records"], 470)
        self.assertEqual(manifest["source"]["validation_records"], 0)
        self.assertEqual(manifest["source"]["holdout_records"], 0)
        body_files = [name for name, facts in manifest["files"].items() if facts["contains_train_body"]]
        self.assertEqual(body_files, ["data/train-projection.jsonl"])

    def test_validation_holdout_unknown_and_unlisted_body_are_rejected(self) -> None:
        cases = {
            "validation": "data/validation.jsonl",
            "holdout": "data/holdout.jsonl",
            "unknown": "unknown.bin",
            "unlisted": "data/extra.jsonl",
        }
        for name, relative in cases.items():
            with self.subTest(name=name):
                bundle = self._copy(f"case-{name}")
                path = bundle / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"unlisted-body\n")
                with self.assertRaises(l6_training.L6TrainingError):
                    l6_training.verify_bundle(bundle)

    def test_symlink_is_rejected(self) -> None:
        bundle = self._copy("case-symlink")
        os.symlink("train-projection.jsonl", bundle / "data" / "extra-link")
        with self.assertRaisesRegex(l6_training.L6TrainingError, "bundle_non_regular_entry"):
            l6_training.verify_bundle(bundle)

    def test_coherently_rehashed_but_wrong_projection_is_rejected(self) -> None:
        bundle = self._copy("case-wrong-projection")
        path = bundle / "data" / "train-projection.jsonl"
        rows, _ = l6_training._load_jsonl(path)
        rows[0]["completion"] = json.dumps(
            {"outcome": "deny", "rationale": "Changed fixture.", "risk_tags": []},
            separators=(",", ":"),
            sort_keys=True,
        )
        identity = {key: rows[0][key] for key in rows[0] if key not in {"schema_version", "projection_sha256"}}
        rows[0]["projection_sha256"] = l6_training._canonical_sha256(identity)
        raw = l6_training._jsonl_bytes(rows)
        path.write_bytes(raw)
        manifest_path = bundle / "bundle-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["projection"]["sha256"] = l6_training._sha256(raw)
        manifest["files"]["data/train-projection.jsonl"]["sha256"] = l6_training._sha256(raw)
        manifest["files"]["data/train-projection.jsonl"]["bytes"] = len(raw)
        manifest_path.write_bytes(l6_training._pretty_bytes(manifest))
        with self.assertRaisesRegex(l6_training.L6TrainingError, "bundle_projection_hash_mismatch"):
            l6_training.verify_bundle(bundle)

    def test_coherently_rehashed_unknown_allowlist_entry_is_rejected(self) -> None:
        bundle = self._copy("case-wrong-allowlist")
        unknown_raw = b"coherently-listed-but-not-authorized\n"
        (bundle / "unknown.bin").write_bytes(unknown_raw)
        allowlist_path = bundle / "contracts/bundle-allowlist-v1.json"
        allowlist = json.loads(allowlist_path.read_text())
        allowlist["files"].append(
            {"bundle_path": "unknown.bin", "contains_train_body": False}
        )
        allowlist_raw = l6_training._pretty_bytes(allowlist)
        allowlist_path.write_bytes(allowlist_raw)
        manifest_path = bundle / "bundle-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["contracts/bundle-allowlist-v1.json"] = {
            "bytes": len(allowlist_raw),
            "contains_train_body": False,
            "sha256": l6_training._sha256(allowlist_raw),
        }
        manifest["files"]["unknown.bin"] = {
            "bytes": len(unknown_raw),
            "contains_train_body": False,
            "sha256": l6_training._sha256(unknown_raw),
        }
        manifest_path.write_bytes(l6_training._pretty_bytes(manifest))
        with self.assertRaisesRegex(
            l6_training.L6TrainingError, "bundle_allowlist_hash_mismatch"
        ):
            l6_training.verify_bundle(bundle)

    def test_coherently_rehashed_artifact_allowlist_is_rejected(self) -> None:
        bundle = self._copy("case-wrong-artifact-allowlist")
        path = bundle / "contracts/artifact-export-allowlist-v1.json"
        allowlist = json.loads(path.read_text())
        allowlist["allowed_root_files"].append("unexpected.json")
        raw = l6_training._pretty_bytes(allowlist)
        path.write_bytes(raw)
        manifest_path = bundle / "bundle-manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["files"]["contracts/artifact-export-allowlist-v1.json"].update(
            {"bytes": len(raw), "sha256": l6_training._sha256(raw)}
        )
        manifest_path.write_bytes(l6_training._pretty_bytes(manifest))
        with self.assertRaisesRegex(
            l6_training.L6TrainingError, "artifact_allowlist_invalid"
        ):
            l6_training.verify_bundle(bundle)


class CompletionOnlyTests(unittest.TestCase):
    def test_prompt_is_masked_and_completion_is_trainable(self) -> None:
        projection, _ = l6_training.build_training_projection(REPO_ROOT)
        row = l6_training.tokenize_completion_only(l6_training.FixtureTokenizer(), projection[0])
        self.assertTrue(all(label == -100 for label in row.labels[: row.prompt_tokens]))
        self.assertTrue(all(label != -100 for label in row.labels[row.prompt_tokens :]))
        self.assertGreater(row.completion_tokens, 0)
        self.assertFalse(all(label == -100 for label in row.labels))

    def test_non_prefix_template_is_rejected(self) -> None:
        class BadTokenizer:
            def apply_chat_template(self, messages, *, tokenize, add_generation_prompt):
                return [1, 2, 3] if add_generation_prompt else [1, 9, 3, 4]

        projection, _ = l6_training.build_training_projection(REPO_ROOT)
        with self.assertRaisesRegex(l6_training.L6TrainingError, "completion_boundary_not_prefix_safe"):
            l6_training.tokenize_completion_only(BadTokenizer(), projection[0])

    def test_mock_dry_run_is_explicitly_not_optimizer_evidence(self) -> None:
        result = l6_training.mock_dry_run(REPO_ROOT)
        self.assertTrue(result["mock_only"])
        self.assertFalse(result["real_model_loaded"])
        self.assertEqual(result["optimizer_steps"], 0)
        self.assertTrue(result["prompt_labels_all_masked"])
        self.assertTrue(result["completion_labels_present"])


class CandidateContractTests(unittest.TestCase):
    def test_candidate_image_and_torch_pin_match(self) -> None:
        recipe = json.loads((REPO_ROOT / l6_training.RECIPE_RELATIVE_PATH).read_text())
        dependencies = (REPO_ROOT / "training/local-approval-l6/dependencies-candidate-v1.txt").read_text()
        self.assertEqual(recipe["container"]["preinstalled_torch"], "2.8.0")
        self.assertIn("torch280", recipe["container"]["image"])
        self.assertIn("torch==2.8.0", dependencies)
        self.assertTrue(recipe["data"]["completion_only"])
        self.assertFalse(recipe["data"]["truncation"])

    def test_entrypoint_appends_resume_after_mode_arguments(self) -> None:
        script = (
            REPO_ROOT
            / "training/local-approval-l6/runpod-stage2-entrypoint.sh"
        ).read_text()
        mode_case = script.index('case "$RONDO_L6_RUN_KIND" in')
        mode_end = script.index("\nesac", mode_case)
        resume = script.index('if [ -n "${RONDO_L6_RESUME_CHECKPOINT:-}" ]')
        train = script.index('python3 "$RONDO_L6_BUNDLE/bin/l6_training.py" train')
        self.assertLess(mode_end, resume)
        self.assertLess(resume, train)

    def test_smoke_forces_one_step_without_mutating_candidate(self) -> None:
        candidate = json.loads((REPO_ROOT / l6_training.RECIPE_RELATIVE_PATH).read_text())
        original = copy.deepcopy(candidate)
        recipe, _, identity, identity_sha = l6_training.resolve_run_contract(
            candidate,
            run_kind="smoke",
            final_recipe_path=None,
            dependency_identity_path=None,
        )
        self.assertEqual(recipe["optimizer"]["max_steps"], 1)
        self.assertEqual(recipe["optimizer"]["num_train_epochs"], 1)
        self.assertEqual(recipe["candidate_status"], "stage2_optimizer_smoke_only")
        self.assertEqual(candidate, original)
        self.assertIsNone(identity)
        self.assertIsNone(identity_sha)

    def test_formal_requires_separately_frozen_recipe_and_dependencies(self) -> None:
        candidate = json.loads((REPO_ROOT / l6_training.RECIPE_RELATIVE_PATH).read_text())
        with self.assertRaisesRegex(l6_training.L6TrainingError, "formal_frozen_contract_required"):
            l6_training.resolve_run_contract(
                candidate,
                run_kind="formal",
                final_recipe_path=None,
                dependency_identity_path=None,
            )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recipe = copy.deepcopy(candidate)
            recipe["candidate_status"] = "stage2_final_frozen"
            recipe_path = root / "recipe.json"
            recipe_path.write_bytes(l6_training._pretty_bytes(recipe))
            identity_path = root / "dependencies.json"
            identity_path.write_bytes(
                l6_training._pretty_bytes(
                    _dependency_identity(recipe, status="stage2_final_frozen")
                )
            )
            resolved, _, identity, identity_sha = l6_training.resolve_run_contract(
                candidate,
                run_kind="formal",
                final_recipe_path=recipe_path,
                dependency_identity_path=identity_path,
            )
            self.assertEqual(resolved["candidate_status"], "stage2_final_frozen")
            self.assertEqual(set(identity["packages"]), l6_training.DIRECT_DEPENDENCIES)
            self.assertRegex(identity_sha, r"^[0-9a-f]{64}$")

            recipe["optimizer"]["max_steps"] = 1
            recipe_path.write_bytes(l6_training._pretty_bytes(recipe))
            with self.assertRaisesRegex(l6_training.L6TrainingError, "formal_recipe_invalid"):
                l6_training.resolve_run_contract(
                    candidate,
                    run_kind="formal",
                    final_recipe_path=recipe_path,
                    dependency_identity_path=identity_path,
                )

    def test_formal_rejects_incomplete_dependencies_packing_and_quantization_drift(self) -> None:
        candidate = json.loads((REPO_ROOT / l6_training.RECIPE_RELATIVE_PATH).read_text())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            recipe = copy.deepcopy(candidate)
            recipe["candidate_status"] = "stage2_final_frozen"
            recipe_path = root / "recipe.json"
            identity_path = root / "dependencies.json"
            identity = _dependency_identity(recipe, status="stage2_final_frozen")
            identity["packages"].pop("safetensors")
            recipe_path.write_bytes(l6_training._pretty_bytes(recipe))
            identity_path.write_bytes(l6_training._pretty_bytes(identity))
            with self.assertRaisesRegex(
                l6_training.L6TrainingError, "formal_dependency_identity_invalid"
            ):
                l6_training.resolve_run_contract(
                    candidate,
                    run_kind="formal",
                    final_recipe_path=recipe_path,
                    dependency_identity_path=identity_path,
                )
            identity_path.write_bytes(
                l6_training._pretty_bytes(
                    _dependency_identity(recipe, status="stage2_final_frozen")
                )
            )
            for changed in ("packing", "quantization", "unlisted_optimizer"):
                changed_recipe = copy.deepcopy(recipe)
                if changed == "packing":
                    changed_recipe["data"]["packing"] = True
                elif changed == "quantization":
                    changed_recipe["quantization"]["method"] = "different"
                else:
                    changed_recipe["optimizer"]["seed"] = 7
                recipe_path.write_bytes(l6_training._pretty_bytes(changed_recipe))
                with self.assertRaisesRegex(
                    l6_training.L6TrainingError, "formal_recipe_invalid"
                ):
                    l6_training.resolve_run_contract(
                        candidate,
                        run_kind="formal",
                        final_recipe_path=recipe_path,
                        dependency_identity_path=identity_path,
                    )


class RunOutputTests(unittest.TestCase):
    def test_resume_is_scoped_and_bound_to_exact_run_contract(self) -> None:
        recipe_raw = b'{"recipe":"fixed"}\n'
        dependency_raw = b'{"dependencies":"fixed"}\n'
        contract = {
            "schema_version": 1,
            "version": "rondo_local_approval_l6_run_contract_v1",
            "run_id": "run-1",
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "formal"
            self.assertIsNone(
                l6_training._prepare_training_output(
                    output,
                    expected_contract=contract,
                    recipe_raw=recipe_raw,
                    dependency_identity_raw=dependency_raw,
                    resume_from_checkpoint=None,
                )
            )
            with self.assertRaisesRegex(
                l6_training.L6TrainingError, "training_output_already_exists"
            ):
                l6_training._prepare_training_output(
                    output,
                    expected_contract=contract,
                    recipe_raw=recipe_raw,
                    dependency_identity_raw=dependency_raw,
                    resume_from_checkpoint=None,
                )
            checkpoint = output / "checkpoints/checkpoint-25"
            checkpoint.mkdir(parents=True)
            resumed = l6_training._prepare_training_output(
                output,
                expected_contract=contract,
                recipe_raw=recipe_raw,
                dependency_identity_raw=dependency_raw,
                resume_from_checkpoint=checkpoint,
            )
            self.assertEqual(resumed, str(checkpoint))
            changed = dict(contract, run_id="run-2")
            with self.assertRaisesRegex(
                l6_training.L6TrainingError, "resume_run_contract_mismatch"
            ):
                l6_training._prepare_training_output(
                    output,
                    expected_contract=changed,
                    recipe_raw=recipe_raw,
                    dependency_identity_raw=dependency_raw,
                    resume_from_checkpoint=checkpoint,
                )
            outside = Path(temporary) / "checkpoint-25"
            outside.mkdir()
            with self.assertRaisesRegex(
                l6_training.L6TrainingError, "resume_checkpoint_outside_output"
            ):
                l6_training._prepare_training_output(
                    output,
                    expected_contract=contract,
                    recipe_raw=recipe_raw,
                    dependency_identity_raw=dependency_raw,
                    resume_from_checkpoint=outside,
                )
            os.symlink("checkpoint-25", output / "checkpoints/checkpoint-26")
            with self.assertRaisesRegex(
                l6_training.L6TrainingError, "resume_checkpoint_invalid"
            ):
                l6_training._prepare_training_output(
                    output,
                    expected_contract=contract,
                    recipe_raw=recipe_raw,
                    dependency_identity_raw=dependency_raw,
                    resume_from_checkpoint=output / "checkpoints/checkpoint-26",
                )


class ReceiptAndArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary = tempfile.TemporaryDirectory()
        cls.bundle = Path(cls.temporary.name) / "bundle"
        l6_training.prepare_bundle(REPO_ROOT, cls.bundle)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temporary.cleanup()

    def _completed_fixture(self, name: str) -> Path:
        output = Path(self.temporary.name) / name
        bundle = l6_training.verify_bundle(self.bundle)
        recipe = json.loads(
            (self.bundle / "contracts/recipe-candidate-v1.json").read_text()
        )
        recipe["candidate_status"] = "stage2_optimizer_smoke_only"
        recipe["optimizer"]["max_steps"] = 1
        recipe["optimizer"]["num_train_epochs"] = 1
        recipe_raw = l6_training._pretty_bytes(recipe)
        dependency = _dependency_identity(recipe, status="stage2_smoke_observed")
        dependency_raw = l6_training._pretty_bytes(dependency)
        run_contract = l6_training._run_contract(
            run_id="smoke-1",
            run_kind="smoke",
            hardware_name="fixture-gpu",
            bundle=bundle,
            recipe_raw=recipe_raw,
            dependency_identity_raw=dependency_raw,
        )
        l6_training._prepare_training_output(
            output,
            expected_contract=run_contract,
            recipe_raw=recipe_raw,
            dependency_identity_raw=dependency_raw,
            resume_from_checkpoint=None,
        )
        (output / "adapter-final").mkdir()
        (output / "adapter-final/adapter_model.safetensors").write_bytes(b"adapter")
        (output / "checkpoints/checkpoint-1").mkdir(parents=True)
        (output / "checkpoints/checkpoint-1/trainer_state.json").write_text("{}\n")
        adapter = l6_training._hash_tree(output / "adapter-final")
        checkpoints = l6_training._hash_tree(output / "checkpoints")
        model_contract = json.loads(
            (self.bundle / "contracts/model-contract-v1.json").read_text()
        )
        pending = {
            "schema_version": 1,
            "version": "rondo_local_approval_l6_training_pending_v1",
            "status": "pending_adapter_reload_and_finalize",
            "run_kind": "smoke",
            "base": model_contract,
            "train": {
                "records": 470,
                "source_train_jsonl_sha256": l6_training.TRAIN_SHA256,
                "source_dataset_manifest_sha256": l6_training.DATASET_MANIFEST_SHA256,
                "projection_sha256": l6_training.TRAIN_PROJECTION_SHA256,
                "completion_only": True,
            },
            "token_census": {"records": 470, "exact": True},
            "recipe_sha256": l6_training._sha256(recipe_raw),
            "dependencies": {
                "identity": dependency,
                "identity_sha256": l6_training._sha256(dependency_raw),
            },
            "provider": {"name": "runpod", "job_id": "pod-1", "run_id": "smoke-1"},
            "hardware": {"name": "fixture-gpu", "cuda": "12.8"},
            "metrics": {
                "trainer_metrics": {"train_loss": 1.25},
                "global_step": 1,
                "actual_epochs": 0.01,
                "train_loss": 1.25,
            },
            "output_paths": {"adapter": "adapter-final", "checkpoints": "checkpoints"},
            "artifacts": {"adapter": adapter, "checkpoints": checkpoints},
            "bundle_manifest_sha256": bundle["bundle_manifest_sha256"],
        }
        pending_raw = l6_training._pretty_bytes(pending)
        l6_training._write_exclusive(output / "training-pending.json", pending_raw)
        self.assertFalse((output / "training-receipt.json").exists())
        reload_receipt = {
            "schema_version": 1,
            "version": "rondo_local_approval_l6_adapter_reload_receipt_v1",
            "status": "adapter_reloaded",
            "separate_command": True,
            "pending_receipt_sha256": l6_training._sha256(pending_raw),
            "recipe_sha256": l6_training._sha256(recipe_raw),
            "dependency_identity_sha256": l6_training._sha256(dependency_raw),
            "loader_class": recipe["model"]["loader_class"],
            "attention_implementation": recipe["model"]["attention_implementation"],
            "adapter_tree_sha256": adapter["tree_sha256"],
        }
        l6_training._write_exclusive(
            output / "adapter-reload-receipt.json",
            l6_training._pretty_bytes(reload_receipt),
        )
        return output

    def test_finalize_is_strict_and_artifacts_verify_file_by_file(self) -> None:
        output = self._completed_fixture("complete")
        self.assertEqual(
            os.stat(output / "adapter-reload-receipt.json").st_mode & 0o777,
            0o600,
        )
        result = l6_training.finalize_training_receipt(
            self.bundle,
            output,
            actual_runpod_cost_usd="0.17",
            persistence_kind="local_download",
            persistence_revision="sha256:fixture",
        )
        self.assertEqual(result["status"], "completed")
        receipt = json.loads((output / "training-receipt.json").read_text())
        schema = json.loads(
            (self.bundle / "contracts/training-receipt-v1.schema.json").read_text()
        )
        self.assertEqual(set(receipt), set(schema["required"]))
        self.assertEqual(receipt["metrics"]["global_step"], 1)
        self.assertEqual(receipt["cost"]["actual_usd"], "0.17")
        verified = l6_training.verify_artifact_manifest(self.bundle, output)
        self.assertEqual(verified["status"], "verified")
        (output / "adapter-final/adapter_model.safetensors").write_bytes(b"tampered")
        with self.assertRaisesRegex(
            l6_training.L6TrainingError, "artifact_manifest_verification_failed"
        ):
            l6_training.verify_artifact_manifest(self.bundle, output)

    def test_export_rejects_projection_or_per_sample_output(self) -> None:
        output = self._completed_fixture("forbidden")
        forbidden = output / "metrics/train-projection.jsonl"
        forbidden.parent.mkdir()
        forbidden.write_text("{}\n")
        with self.assertRaisesRegex(
            l6_training.L6TrainingError, "artifact_forbidden_path"
        ):
            l6_training.finalize_training_receipt(
                self.bundle,
                output,
                actual_runpod_cost_usd="0",
                persistence_kind="pod_volume",
                persistence_revision="volume-fixture",
            )
        self.assertFalse((output / "training-receipt.json").exists())


if __name__ == "__main__":
    unittest.main()
