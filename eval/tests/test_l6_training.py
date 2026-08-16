from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rondo_eval.local_approval import l6_training


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent

_CONVERSION_TOOL_PATH = (
    REPO_ROOT / "training/local-approval-l6/conversion_tooling.py"
)
_CONVERSION_TOOL_SPEC = importlib.util.spec_from_file_location(
    "plan037_conversion_tooling", _CONVERSION_TOOL_PATH
)
assert _CONVERSION_TOOL_SPEC is not None and _CONVERSION_TOOL_SPEC.loader is not None
conversion_tooling = importlib.util.module_from_spec(_CONVERSION_TOOL_SPEC)
_CONVERSION_TOOL_SPEC.loader.exec_module(conversion_tooling)


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
        self.assertIsInstance(recipe["lora"]["target_modules"], str)
        self.assertEqual(
            recipe["lora"]["target_modules"],
            l6_training.LORA_TARGET_MODULE_PATTERN,
        )
        self.assertNotIn("lora.target_modules", recipe["smoke_adjustable_once"])

    def test_lora_target_regex_matches_only_runtime_language_modules(self) -> None:
        pattern = re.compile(l6_training.LORA_TARGET_MODULE_PATTERN)
        positives = (
            "model.language_model.layers.0.self_attn.q_proj",
            "model.language_model.layers.17.self_attn.o_proj",
            "model.language_model.layers.35.mlp.gate_proj",
            "model.language_model.layers.35.mlp.down_proj",
        )
        negatives = (
            "language_model.model.layers.0.self_attn.q_proj",
            "model.language_model.layers.0.self_attn.rotary_emb",
            "model.language_model.layers.0.self_attn.q_proj.weight",
            "model.vision_tower.layers.0.self_attn.q_proj",
            "model.multi_modal_projector.linear",
            "lm_head",
        )
        self.assertTrue(all(pattern.fullmatch(name) for name in positives))
        self.assertTrue(all(pattern.fullmatch(name) is None for name in negatives))

    def test_runtime_lora_injection_scope_is_fail_closed(self) -> None:
        class Parameter:
            def __init__(self, requires_grad: bool) -> None:
                self.requires_grad = requires_grad

        class Model:
            def __init__(self, targeted, trainable) -> None:
                self.targeted_module_names = targeted
                self._trainable = trainable

            def named_parameters(self):
                return [(name, Parameter(True)) for name in self._trainable]

        q_proj = "model.language_model.layers.0.self_attn.q_proj"
        down_proj = "model.language_model.layers.1.mlp.down_proj"
        valid = Model(
            [q_proj, down_proj],
            [
                f"base_model.model.{q_proj}.lora_A.default.weight",
                f"base_model.model.{q_proj}.lora_B.default.weight",
                f"base_model.model.{down_proj}.lora_A.default.weight",
                f"base_model.model.{down_proj}.lora_B.default.weight",
            ],
        )
        result = l6_training.validate_lora_injection(
            valid, l6_training.LORA_TARGET_MODULE_PATTERN
        )
        self.assertEqual(result["targeted_modules"], 2)
        self.assertEqual(result["trainable_parameters"], 4)
        self.assertEqual(result["vision_projector_lm_head_hits"], 0)

        invalid_models = (
            Model([q_proj, "model.vision_tower.layers.0.self_attn.q_proj"], []),
            Model([q_proj], [f"base_model.model.{q_proj}.weight"]),
            Model([q_proj], ["base_model.model.lm_head.lora_A.default.weight"]),
            Model([q_proj, down_proj], [f"base_model.model.{q_proj}.lora_A.default.weight"]),
        )
        for model in invalid_models:
            with self.subTest(targeted=model.targeted_module_names):
                with self.assertRaises(l6_training.L6TrainingError):
                    l6_training.validate_lora_injection(
                        model, l6_training.LORA_TARGET_MODULE_PATTERN
                    )
        with self.assertRaisesRegex(
            l6_training.L6TrainingError, "lora_target_pattern_invalid"
        ):
            l6_training.validate_lora_injection(valid, "q_proj")

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

    def test_runbook_recovery_refreshes_ssh_and_finishes_pending_receipt(self) -> None:
        runbook = (
            REPO_ROOT / "training/local-approval-l6/stage2-runbook.md"
        ).read_text()
        recovery_start = runbook.index("If that one recovery restart is needed")
        recovery_end = runbook.index(
            "The controller continues polling spend during recovery", recovery_start
        )
        recovery = runbook[recovery_start:recovery_end]
        download = runbook[runbook.index("## I. SCP recovery") :]

        self.assertNotIn("runpodctl pod ssh info", runbook)
        self.assertIn('runpodctl ssh info "$TASK_POD_ID"', recovery)
        self.assertIn("TASK_SSH_HOST", recovery)
        self.assertIn("TASK_SSH_PORT", recovery)
        self.assertIn('ssh -o IdentitiesOnly=yes -i "$TASK_SSH_KEY"', recovery)
        self.assertIn('root@"$TASK_SSH_HOST"', recovery)
        self.assertIn("TASK_POD_ID='<TASK_POD_ID_FROM_CONTROLLER>'", recovery)
        self.assertIn('-P "$TASK_SSH_PORT"', download)
        self.assertIn('root@"$TASK_SSH_HOST"', download)

        completed = recovery.index("training-receipt.json")
        pending = recovery.index("training-pending.json", completed)
        reload_adapter = recovery.index("reload-adapter", pending)
        finalize = recovery.index("finalize-receipt", reload_adapter)
        verify = recovery.index("verify-artifacts", finalize)
        missing = recovery.index("recovery_missing_pending_or_completed_receipt")
        self.assertLess(completed, pending)
        self.assertLess(pending, reload_adapter)
        self.assertLess(reload_adapter, finalize)
        self.assertLess(finalize, verify)
        self.assertLess(finalize, missing)
        self.assertLess(missing, verify)
        self.assertLess(
            recovery_start + verify,
            runbook.index("scp -r", runbook.index("## I. SCP recovery")),
        )
        self.assertNotIn("runpod-stage2-entrypoint.sh", recovery)
        self.assertNotRegex(recovery, r'l6_training\.py"\s+train\b')
        self.assertIn('export HF_HOME="$TASK_ROOT/hf-home"', recovery)
        self.assertNotIn("hf-cache", recovery)
        self.assertIn("recovery_missing_pending_or_completed_receipt", recovery)

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

    def test_finalize_recovers_exact_orphan_manifest_before_completed_receipt(self) -> None:
        output = self._completed_fixture("orphan-manifest")
        original_write = l6_training._write_exclusive

        def interrupt_completed_receipt(path: Path, raw: bytes, *, mode: int = 0o600) -> None:
            if path.name == "training-receipt.json":
                raise RuntimeError("fixture-controller-interruption")
            original_write(path, raw, mode=mode)

        with mock.patch.object(
            l6_training, "_write_exclusive", side_effect=interrupt_completed_receipt
        ):
            with self.assertRaisesRegex(RuntimeError, "fixture-controller-interruption"):
                l6_training.finalize_training_receipt(
                    self.bundle,
                    output,
                    actual_runpod_cost_usd="0.17",
                    persistence_kind="local_download",
                    persistence_revision="sha256:fixture",
                )
        self.assertTrue((output / "artifact-manifest.json").is_file())
        self.assertFalse((output / "training-receipt.json").exists())

        result = l6_training.finalize_training_receipt(
            self.bundle,
            output,
            actual_runpod_cost_usd="0.17",
            persistence_kind="local_download",
            persistence_revision="sha256:fixture",
        )
        self.assertEqual(result["status"], "completed")
        self.assertEqual(
            l6_training.verify_artifact_manifest(self.bundle, output)["status"],
            "verified",
        )

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


class ConversionToolContractTests(unittest.TestCase):
    def test_contract_is_body_free_and_binds_b10333_tools_and_both_routes(self) -> None:
        contract_path = (
            REPO_ROOT
            / "training/local-approval-l6/conversion-tool-contract-v1.json"
        )
        contract, _raw = conversion_tooling._load_contract(contract_path)
        self.assertEqual(contract["llama_cpp_source"]["release"], "b10333")
        self.assertEqual(
            contract["llama_cpp_source"]["commit"],
            "08659901c43b51de735740f1cf61bb82fbe0c4e4",
        )
        self.assertEqual(
            contract["llama_cpp_source"]["top_level_files"]
            ["convert_hf_to_gguf.py"]["sha256"],
            "e38975e1c68d98ac1664dfd530616eb35c72294382a4dd873d4746b23f27779f",
        )
        self.assertEqual(
            contract["llama_cpp_source"]["top_level_files"]
            ["convert_lora_to_gguf.py"]["sha256"],
            "3c5f109f3d7a5ef530ea388d8e994512df6f544ce1aa8b2e39be446223637b93",
        )
        self.assertEqual(
            contract["quantizer_runtime"]["regular_files"]["llama-quantize"]
            ["sha256"],
            "6ea852917cc1ef724faf1cb612c2ca50c5963321acc86af51a91224d15aa7e3a",
        )
        self.assertEqual(
            contract["local_inference_runtime"]["llama_server_sha256"],
            "97a6b083ea34fea7e4e4440a0ddb734e1a2f6b775f4b31ef68ba5f998a9eeabd",
        )
        merge_path = REPO_ROOT / "training/local-approval-l6/merge_adapter.py"
        self.assertEqual(
            contract["merge_builder"],
            {
                "package_path": "bin/merge_adapter.py",
                "sha256": conversion_tooling._sha256(merge_path.read_bytes()),
                "size_bytes": merge_path.stat().st_size,
            },
        )
        self.assertEqual(
            set(contract["output_allowlists"]),
            {"adapter_on_off", "paired_gguf"},
        )
        self.assertTrue(
            all(
                "conversion-operations.json" in allowlist
                for allowlist in contract["output_allowlists"].values()
            )
        )
        self.assertTrue(
            all(value is False for value in contract["boundaries"].values())
        )
        serialized = json.dumps(contract, sort_keys=True).lower()
        self.assertNotIn("validation.jsonl", serialized)
        self.assertNotIn("train-projection", serialized)

    def test_actual_ignored_b10333_sources_match_contract_when_installed(self) -> None:
        common_root = REPO_ROOT.parents[2]
        source_root = (
            common_root / "eval-data/sources/llama.cpp-b10333-08659901"
        )
        quantizer_root = common_root / "eval-data/tools/llama-b10333"
        if not source_root.is_dir() or not quantizer_root.is_dir():
            self.skipTest("ignored b10333 tooling is not installed")
        result = conversion_tooling.verify_sources(
            REPO_ROOT
            / "training/local-approval-l6/conversion-tool-contract-v1.json",
            source_root,
            quantizer_root,
        )
        self.assertEqual(result["status"], "verified")

    def test_conversion_operations_cover_each_route_and_actual_tool(self) -> None:
        common = {
            "tool_bundle": "/workspace/rondo-l6/conversion-tool-bundle",
            "deployment": "/workspace/rondo-l6/deployments/attempt-01",
            "base_snapshot": "/workspace/rondo-l6/hf-home/hub/base",
            "formal_output": "/workspace/rondo-l6/runs/attempt-01/formal",
            "conversion_python": "/workspace/rondo-l6/conversion-venv/bin/python",
            "training_python": "/workspace/rondo-l6/venv/bin/python",
        }
        adapter = conversion_tooling._steps_for_operations(
            "adapter_on_off", **common
        )
        paired = conversion_tooling._steps_for_operations("paired_gguf", **common)
        self.assertEqual(
            [step["name"] for step in adapter],
            ["base_hf_to_f16", "base_quantize_q4_k_m", "adapter_to_f16"],
        )
        self.assertEqual(
            [step["name"] for step in paired],
            [
                "base_hf_to_f16",
                "base_quantize_q4_k_m",
                "merge_adapter_into_base",
                "finetuned_hf_to_f16",
                "finetuned_quantize_q4_k_m",
            ],
        )
        self.assertEqual(paired[2]["tool"], "merge_adapter")
        self.assertEqual(
            paired[2]["argv"][1],
            "/workspace/rondo-l6/deployments/attempt-01/tooling/merge_adapter.py",
        )

    def test_tool_bundle_manifest_rejects_unknown_or_changed_body(self) -> None:
        contract_source = (
            REPO_ROOT
            / "training/local-approval-l6/conversion-tool-contract-v1.json"
        )
        common_root = REPO_ROOT.parents[2]
        source_root = (
            common_root / "eval-data/sources/llama.cpp-b10333-08659901"
        )
        quantizer_root = common_root / "eval-data/tools/llama-b10333"
        if not source_root.is_dir() or not quantizer_root.is_dir():
            self.skipTest("ignored b10333 tooling is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            bundle = Path(temporary) / "bundle"
            conversion_tooling.prepare_package(
                contract_source,
                source_root,
                quantizer_root,
                bundle,
            )
            self.assertEqual(
                conversion_tooling.verify_package(bundle)["status"], "verified"
            )
            (bundle / "unknown.bin").write_bytes(b"unknown")
            manifest_path = bundle / conversion_tooling.MANIFEST_NAME
            manifest = json.loads(manifest_path.read_text())
            manifest["files"] = conversion_tooling._package_entries(bundle)
            manifest_path.write_bytes(conversion_tooling._pretty_bytes(manifest))
            with self.assertRaisesRegex(
                conversion_tooling.ConversionToolError,
                "tool_bundle_allowlist_mismatch",
            ):
                conversion_tooling.verify_package(bundle)

    def test_verify_output_streams_exact_route_and_training_binding(self) -> None:
        contract_path = (
            REPO_ROOT
            / "training/local-approval-l6/conversion-tool-contract-v1.json"
        )
        contract_raw = contract_path.read_bytes()
        contract = json.loads(contract_raw)
        common_root = REPO_ROOT.parents[2]
        source_root = common_root / "eval-data/sources/llama.cpp-b10333-08659901"
        quantizer_root = common_root / "eval-data/tools/llama-b10333"
        if not source_root.is_dir() or not quantizer_root.is_dir():
            self.skipTest("ignored b10333 tooling is not installed")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            bundle = root / "tool-bundle"
            conversion_tooling.prepare_package(
                contract_path, source_root, quantizer_root, bundle
            )
            output = root / "deployment"
            output.mkdir()
            training_path = root / "training-receipt.json"
            model_contract = json.loads(
                (REPO_ROOT / "training/local-approval-l6/model-contract-v1.json")
                .read_text()
            )
            dependency_identity = {
                "schema_version": 1,
                "status": "stage2_final_frozen",
                "packages": {
                    name: "fixture"
                    for name in (
                        "torch",
                        "transformers",
                        "peft",
                        "trl",
                        "accelerate",
                        "bitsandbytes",
                        "safetensors",
                    )
                },
                "python_version": "3.11.13",
                "cuda_version": "12.8",
                "container_image": contract["conversion_environment"]
                ["container_image"],
            }
            adapter_files = {
                "adapter_model.safetensors": {
                    "bytes": 7,
                    "sha256": "d" * 64,
                }
            }
            adapter_tree = conversion_tooling._sha256(
                conversion_tooling._canonical_bytes(adapter_files)
            )
            training = {
                "schema_version": 1,
                "version": "rondo_local_approval_l6_training_receipt_v1",
                "status": "completed",
                "run_kind": "formal",
                "base": model_contract,
                "train": {
                    "records": 470,
                    "source_train_jsonl_sha256": conversion_tooling.TRAIN_SHA256,
                    "source_dataset_manifest_sha256": (
                        conversion_tooling.DATASET_MANIFEST_SHA256
                    ),
                    "projection_sha256": (
                        conversion_tooling.TRAIN_PROJECTION_SHA256
                    ),
                    "completion_only": True,
                },
                "token_census": {
                    "status": "complete",
                    "exact": True,
                    "records": 470,
                    "projection_sha256": (
                        conversion_tooling.TRAIN_PROJECTION_SHA256
                    ),
                    "truncation": False,
                    "packing": False,
                    "tokenizer": {
                        "repo": contract["formal_training"]["tokenizer_repo"],
                        "revision": contract["formal_training"]
                        ["tokenizer_revision"],
                        "chat_template_sha256": contract["formal_training"]
                        ["chat_template_sha256"],
                    },
                    "sequence_tokens": {"limit": 4096, "over_limit": 0},
                    "completion_only": {
                        "records_with_all_prompt_labels_masked": 470,
                        "records_with_unmasked_completion": 470,
                    },
                },
                "recipe_sha256": "a" * 64,
                "dependencies": {
                    "identity": dependency_identity,
                    "identity_sha256": conversion_tooling._sha256(
                        conversion_tooling._pretty_bytes(dependency_identity)
                    ),
                },
                "cost": {"provider": "runpod", "actual_usd": "0.25"},
                "provider": {
                    "name": "runpod",
                    "job_id": "fixture",
                    "run_id": "formal-fixture",
                },
                "persistence": {
                    "kind": "local_download",
                    "revision": "sha256:fixture",
                },
                "reload_receipt_sha256": "b" * 64,
                "hardware": {"name": "A40", "cuda": "12.8"},
                "metrics": {
                    "global_step": 2,
                    "actual_epochs": 1.0,
                    "train_loss": 1.0,
                },
                "output_paths": {
                    "adapter": "adapter-final",
                    "checkpoints": "checkpoints",
                },
                "artifacts": {
                    "adapter": {
                        "files": adapter_files,
                        "tree_sha256": adapter_tree,
                    },
                    "checkpoints": {"files": {}, "tree_sha256": "c" * 64},
                },
                "bundle_manifest_sha256": "e" * 64,
            }
            training_raw = conversion_tooling._pretty_bytes(training)
            training_path.write_bytes(training_raw)
            route = "adapter_on_off"
            body_paths = set(contract["output_allowlists"][route]) - {
                "conversion-files-manifest.json",
                "conversion-receipt.json",
                "conversion-operations.json",
            }
            for relative_name in body_paths:
                path = output / relative_name
                path.parent.mkdir(parents=True, exist_ok=True)
                tool_source = {
                    "tooling/convert_hf_to_gguf.py": (
                        bundle / "tools/llama.cpp/convert_hf_to_gguf.py"
                    ),
                    "tooling/convert_lora_to_gguf.py": (
                        bundle / "tools/llama.cpp/convert_lora_to_gguf.py"
                    ),
                    "tooling/llama-quantize": (
                        bundle / "tools/llama-b10333-cpu/llama-quantize"
                    ),
                }.get(relative_name)
                if tool_source is not None:
                    shutil.copy2(tool_source, path)
                elif relative_name == "conversion-dependency-identity.json":
                    dependency = {
                        "schema_version": 1,
                        "version": (
                            "rondo_local_approval_l6_conversion_dependency_identity_v1"
                        ),
                        "packages": conversion_tooling._dependency_pins(
                            bundle / "contracts/conversion-dependencies-v1.txt"
                        ),
                        "python": "3.11.13",
                        "torch": "2.8.0+cu128",
                        "cuda": "12.8",
                        "container_image": contract["conversion_environment"]
                        ["container_image"],
                        "route": route,
                    }
                    path.write_bytes(conversion_tooling._pretty_bytes(dependency))
                else:
                    path.write_bytes(f"fixture:{relative_name}\n".encode())
            conversion_tooling.write_operations(
                contract_path,
                bundle,
                output,
                training_path,
                route=route,
                base_snapshot=root / "base-snapshot",
                formal_output=root / "formal",
                conversion_python=root / "conversion-venv/bin/python",
                training_python=root / "venv/bin/python",
            )
            body_paths.add("conversion-operations.json")
            files = {
                name: conversion_tooling._stream_identity(output / name)
                for name in sorted(body_paths)
            }
            manifest = {
                "schema_version": 1,
                "version": "rondo_local_approval_l6_conversion_files_v1",
                "route": route,
                "files": files,
            }
            manifest_raw = conversion_tooling._pretty_bytes(manifest)
            (output / "conversion-files-manifest.json").write_bytes(manifest_raw)
            receipt = {
                "schema_version": 1,
                "version": "rondo_local_approval_l6_conversion_receipt_v1",
                "status": "completed",
                "route": route,
                "base_model": contract["base_model"],
                "quantization": "Q4_K_M",
                "source_adapter_tree_sha256": adapter_tree,
                "training_receipt_sha256": conversion_tooling._sha256(training_raw),
                "conversion_contract_sha256": conversion_tooling._sha256(contract_raw),
                "tool_bundle_manifest_sha256": conversion_tooling.verify_package(
                    bundle
                )["manifest_sha256"],
                "dependency_identity_sha256": files[
                    "conversion-dependency-identity.json"
                ]["sha256"],
                "operations_sha256": files["conversion-operations.json"][
                    "sha256"
                ],
                "files_manifest_sha256": conversion_tooling._sha256(manifest_raw),
                "deployed_outputs": {
                    name: files[name]
                    for name in sorted(files)
                    if name.endswith(".gguf")
                },
                "temporary_f16_and_merged_hf_removed": True,
            }
            (output / "conversion-receipt.json").write_bytes(
                conversion_tooling._pretty_bytes(receipt)
            )

            def rewrite_envelopes() -> None:
                refreshed = {
                    name: conversion_tooling._stream_identity(output / name)
                    for name in sorted(body_paths)
                }
                refreshed_manifest = {
                    "schema_version": 1,
                    "version": "rondo_local_approval_l6_conversion_files_v1",
                    "route": route,
                    "files": refreshed,
                }
                refreshed_manifest_raw = conversion_tooling._pretty_bytes(
                    refreshed_manifest
                )
                (output / "conversion-files-manifest.json").write_bytes(
                    refreshed_manifest_raw
                )
                receipt["dependency_identity_sha256"] = refreshed[
                    "conversion-dependency-identity.json"
                ]["sha256"]
                receipt["operations_sha256"] = refreshed[
                    "conversion-operations.json"
                ]["sha256"]
                receipt["files_manifest_sha256"] = conversion_tooling._sha256(
                    refreshed_manifest_raw
                )
                receipt["deployed_outputs"] = {
                    name: refreshed[name]
                    for name in sorted(refreshed)
                    if name.endswith(".gguf")
                }
                (output / "conversion-receipt.json").write_bytes(
                    conversion_tooling._pretty_bytes(receipt)
                )

            self.assertEqual(
                conversion_tooling.verify_output(
                    contract_path, output, training_path, bundle
                )["route"],
                route,
            )
            receipt["tool_bundle_manifest_sha256"] = "f" * 64
            (output / "conversion-receipt.json").write_bytes(
                conversion_tooling._pretty_bytes(receipt)
            )
            with self.assertRaisesRegex(
                conversion_tooling.ConversionToolError,
                "deployment_receipt_mismatch",
            ):
                conversion_tooling.verify_output(
                    contract_path, output, training_path, bundle
                )
            receipt["tool_bundle_manifest_sha256"] = (
                conversion_tooling.verify_package(bundle)["manifest_sha256"]
            )
            (output / "conversion-receipt.json").write_bytes(
                conversion_tooling._pretty_bytes(receipt)
            )

            malformed_training = copy.deepcopy(training)
            malformed_training["provider"] = ["not", "a", "mapping"]
            training_path.write_bytes(
                conversion_tooling._pretty_bytes(malformed_training)
            )
            with self.assertRaisesRegex(
                conversion_tooling.ConversionToolError,
                "formal_training_receipt_invalid",
            ):
                conversion_tooling.verify_output(
                    contract_path, output, training_path, bundle
                )
            training_path.write_bytes(training_raw)

            (output / "unknown.bin").write_bytes(b"unknown")
            with self.assertRaisesRegex(
                conversion_tooling.ConversionToolError,
                "deployment_output_allowlist_mismatch",
            ):
                conversion_tooling.verify_output(
                    contract_path, output, training_path, bundle
                )
            (output / "unknown.bin").unlink()
            (output / "base-q4_k_m.gguf").write_bytes(b"tampered")
            with self.assertRaisesRegex(
                conversion_tooling.ConversionToolError,
                "deployment_files_manifest_mismatch",
            ):
                conversion_tooling.verify_output(
                    contract_path, output, training_path, bundle
                )

            dependency_path = output / "conversion-dependency-identity.json"
            dependency_raw = dependency_path.read_bytes()
            dependency = json.loads(dependency_raw)
            dependency["packages"]["numpy"] = "9.9.9"
            dependency_path.write_bytes(conversion_tooling._pretty_bytes(dependency))
            rewrite_envelopes()
            with self.assertRaisesRegex(
                conversion_tooling.ConversionToolError,
                "conversion_dependency_identity_invalid",
            ):
                conversion_tooling.verify_output(
                    contract_path, output, training_path, bundle
                )
            dependency_path.write_bytes(dependency_raw)
            rewrite_envelopes()

            operations_path = output / "conversion-operations.json"
            operations_raw = operations_path.read_bytes()
            operations = json.loads(operations_raw)
            operations["steps"][0]["argv"][-1] = "/coherently-rehashed-wrong-base"
            operations_path.write_bytes(conversion_tooling._pretty_bytes(operations))
            rewrite_envelopes()
            with self.assertRaisesRegex(
                conversion_tooling.ConversionToolError,
                "conversion_operations_invalid",
            ):
                conversion_tooling.verify_output(
                    contract_path, output, training_path, bundle
                )
            operations_path.write_bytes(operations_raw)
            rewrite_envelopes()

            (output / "base-q4_k_m.gguf").write_bytes(
                b"fixture:base-q4_k_m.gguf\n"
            )
            training["run_kind"] = "smoke"
            training_path.write_bytes(conversion_tooling._pretty_bytes(training))
            with self.assertRaisesRegex(
                conversion_tooling.ConversionToolError,
                "formal_training_receipt_invalid",
            ):
                conversion_tooling.verify_output(
                    contract_path, output, training_path, bundle
                )

    def test_runbook_keeps_deployment_outside_formal_and_verifies_both_downloads(self) -> None:
        runbook = (
            REPO_ROOT / "training/local-approval-l6/stage2-runbook.md"
        ).read_text()
        finalize = runbook.index("finalize-receipt", runbook.index("## H."))
        local_training_verify = runbook.index(
            "--bundle \"$TASK_BUNDLE\" --output \"$TASK_LOCAL_RECOVERY\""
        )
        deployment = runbook.index(
            'TASK_DEPLOYMENT="$TASK_ROOT/deployments/$TASK_ATTEMPT_ID"'
        )
        local_deployment_verify = runbook.index(
            '--output "$TASK_LOCAL_DEPLOYMENT"'
        )
        pod_delete = runbook.index(
            'runpodctl pod delete "$TASK_POD_ID"', runbook.index("## J.")
        )
        local_pair = runbook.index("l6_b10333_pair prepare-evidence")
        self.assertLess(finalize, local_training_verify)
        self.assertLess(local_training_verify, deployment)
        self.assertLess(deployment, local_deployment_verify)
        self.assertLess(local_deployment_verify, pod_delete)
        self.assertLess(pod_delete, local_pair)
        self.assertNotIn('TASK_DEPLOYMENT="$TASK_FORMAL_OUTPUT', runbook)
        self.assertNotIn('TASK_FORMAL_OUTPUT/conversion', runbook)
        self.assertGreaterEqual(runbook.count("verify-output"), 2)
        self.assertGreaterEqual(runbook.count('--tool-bundle'), 3)
        self.assertIn("conversion_tooling.py\" write-operations", runbook)
        self.assertIn('"$TASK_DEPLOYMENT/tooling/merge_adapter.py"', runbook)
        self.assertNotIn("merge_and_unload", runbook)
        self.assertIn(
            'converter = target / "deployment/conversion-operations.json"',
            runbook,
        )
        self.assertNotIn("HF_MODEL_REPO=", runbook)
        self.assertNotIn("--commit-message 'Plan 037 L6 verified artifacts'", runbook)
        self.assertIn("l6_b10333_pair smoke", runbook)
        self.assertIn("l6_b10333_pair run", runbook)
        self.assertIn("cross_eval verify-import", runbook)
        self.assertIn("side_output_count == 390", runbook)
        self.assertGreaterEqual(
            runbook.count("df -B1 --output=avail /mnt/c"), 3
        )
        self.assertIn(
            'TASK_RUNNING_CONTAINERS="$(docker container ls -q)"', runbook
        )
        self.assertIn("rondo-cargo-build.lock", runbook)
        self.assertGreaterEqual(runbook.count("command -v flock"), 2)
        self.assertGreaterEqual(runbook.count('test ! -L "$TASK_BUILD_LOCK"'), 2)
        self.assertGreaterEqual(runbook.count('test -O "$TASK_BUILD_LOCK"'), 2)
        self.assertIn("flock -n 9", runbook)
        self.assertIn("flock -u 9", runbook)
        self.assertIn("pgrep -x cargo", runbook)
        self.assertGreaterEqual(runbook.count("pgrep -x llama-server"), 2)


if __name__ == "__main__":
    unittest.main()
