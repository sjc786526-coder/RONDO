import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.full_model_training import checkpoint  # noqa: E402
from rondo_eval.publication_critic.full_model_training.bundle import (  # noqa: E402
    create_deterministic_archive,
    extract_verified_archive,
    verify_bundle,
)
from rondo_eval.publication_critic.full_model_training.contract import (  # noqa: E402
    FullModelTrainingError,
    read_json,
)
from rondo_eval.publication_critic.full_model_training.plan066_artifacts import (  # noqa: E402
    run_validation,
    save_stage_candidate,
    verify_stage_candidate,
)
from rondo_eval.publication_critic.full_model_training.plan066_bundle import (  # noqa: E402
    _source_commit,
    prepare_plan066_bundle,
)
from rondo_eval.publication_critic.full_model_training.plan066_finalize import (  # noqa: E402
    PLAN060_BASELINE_BALANCE_USD,
    validate_plan066_provider_facts,
)
from rondo_eval.publication_critic.full_model_training.plan066_contract import (  # noqa: E402
    validate_plan066_recipe,
    validate_plan066_resume_receipt,
)
from rondo_eval.publication_critic.full_model_training import plan066_contract  # noqa: E402
from rondo_eval.publication_critic.full_model_training.plan066_data import (  # noqa: E402
    ValidationDataset,
    build_plan066_export,
    datasets_from_values,
)


class Plan066DataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.export = build_plan066_export(REPO_ROOT)

    def test_export_is_exact_train_validation_without_unseen(self):
        self.assertEqual(len(self.export["train"]["supervision"]), 128)
        self.assertEqual(len(self.export["train"]["pairs"]), 58)
        self.assertEqual(len(self.export["validation"]["supervision"]), 55)
        self.assertEqual(len(self.export["validation"]["pairs"]), 26)
        self.assertEqual(len(self.export["commissioning"]["supervision"]), 6)
        self.assertEqual(self.export["holdout"]["unseen_test_rows_exported"], 0)
        splits = {
            row["proposed_split"]
            for group in ("train", "validation")
            for row in self.export[group]["supervision"]
        }
        self.assertEqual(splits, {"train", "validation"})

    def test_formal_membership_is_not_smoke_membership(self):
        stages = self.export["train"]["membership"]["stages"]
        self.assertEqual(len(stages["C1"]["candidate_ids"]), 128)
        self.assertEqual(len(stages["C2"]["pair_ids"]), 50)
        self.assertEqual(len(stages["C3"]["pair_ids"]), 58)
        self.assertNotEqual(
            stages,
            self.export["commissioning"]["membership"]["stages"],
        )

    def test_loader_rejects_holdout_boundary_drift(self):
        with tempfile.TemporaryDirectory() as directory:
            bundle = Path(directory) / "bundle"
            with mock.patch(
                "rondo_eval.publication_critic.full_model_training.plan066_bundle._source_commit",
                return_value="a" * 40,
            ):
                prepare_plan066_bundle(REPO_ROOT, bundle)
            portable = read_json(bundle / "contracts/plan066-input-v1.json")
            changed = copy.deepcopy(self.export)
            changed["holdout"]["unseen_test_rows_exported"] = 1
            with self.assertRaisesRegex(FullModelTrainingError, "plan066_holdout_boundary_invalid"):
                datasets_from_values(
                    changed,
                    portable=portable,
                    rubric_path=bundle / "eval/templates/publication-critic/qualification-rubric-v1.md",
                    export_sha256="a" * 64,
                )

    def test_bundle_archive_round_trip_and_strict_tamper_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = root / "bundle"
            with mock.patch(
                "rondo_eval.publication_critic.full_model_training.plan066_bundle._source_commit",
                return_value="a" * 40,
            ):
                receipt = prepare_plan066_bundle(REPO_ROOT, bundle)
            self.assertEqual(receipt["train_candidate_count"], 128)
            self.assertEqual(receipt["validation_candidate_count"], 55)
            self.assertEqual(receipt["unseen_test_rows"], 0)
            archive = root / "bundle.tar"
            archive_receipt = create_deterministic_archive(bundle, archive)
            extracted = root / "extracted"
            extract_verified_archive(
                archive,
                extracted,
                expected_sha256=archive_receipt["archive_sha256"],
            )
            self.assertEqual(verify_bundle(extracted)["train_pair_count"], 58)
            data_path = extracted / "data/plan066-v8-train-validation.json"
            data_path.write_bytes(data_path.read_bytes() + b"\n")
            with self.assertRaisesRegex(FullModelTrainingError, "plan066_bundle_file_identity_mismatch"):
                verify_bundle(extracted)

    def test_source_commit_rejects_dirty_training_source(self):
        dirty = SimpleNamespace(stdout="?? training/publication-critic-plan066/new\n")
        with mock.patch("subprocess.run", return_value=dirty):
            with self.assertRaisesRegex(FullModelTrainingError, "plan066_source_tree_dirty"):
                _source_commit(REPO_ROOT)


class Plan066ContractTests(unittest.TestCase):
    def test_recipe_freezes_formal_and_holdout_counts(self):
        recipe = read_json(REPO_ROOT / "training/publication-critic-plan066/recipe-v1.json")
        validated = validate_plan066_recipe(recipe, require_frozen=True)
        self.assertEqual(validated["formal_data"]["binary_candidates"], 128)
        self.assertFalse(validated["validation"]["gradient_access"])
        self.assertFalse(validated["unseen_test"]["run"])

    def test_checkpoint_accepts_v7_smoke_and_v8_formal_only(self):
        base = {
            "stage": "C3",
            "global_step": 3,
            "stage_update": 1,
            "completed_stages": ["C1", "C2", "C3"],
            "data_cursor": {
                "stage_fully_consumed": True,
                "binary_candidate_ids": [f"c-{index}" for index in range(6)],
                "pair_ids": ["p-0", "p-1"],
            },
        }
        checkpoint._validate_progress(base)
        formal = copy.deepcopy(base)
        formal["data_cursor"]["binary_candidate_ids"] = [f"c-{index}" for index in range(128)]
        formal["data_cursor"]["pair_ids"] = [f"p-{index}" for index in range(58)]
        checkpoint._validate_progress(formal)
        formal["data_cursor"]["pair_ids"].pop()
        with self.assertRaisesRegex(FullModelTrainingError, "checkpoint_progress_invalid"):
            checkpoint._validate_progress(formal)

    def test_resume_validator_requires_distinct_process_identities(self):
        start_process = {
            "instance_id": "start-instance",
            "pid": 101,
            "parent_pid": 10,
            "started_at": "2026-08-24T10:00:00Z",
        }
        resume_process = {
            "instance_id": "resume-instance",
            "pid": 202,
            "parent_pid": 20,
            "started_at": "2026-08-24T10:01:00Z",
        }
        receipt = {
            "schema": "rondo-publication-critic-plan066-formal-pending-v1",
            "status": "pending_billing_and_resource_cleanup",
            "created_at": "2026-08-24T10:02:00Z",
            "identity": {},
            "start_process": start_process,
            "resume_process": resume_process,
            "new_os_process_confirmed": True,
            "restored_from_global_step": 3,
            "continued_global_step": 4,
            "continued_stage": {},
            "coverage": {},
            "restored_optimizer_state": {},
            "restored_optimizer_runtime": {},
            "checkpoint": {"process": start_process},
            "timing": {},
            "formal_start_receipt_sha256": "a" * 64,
            "billing": None,
            "remote_resource_terminal_state": None,
            "qualification_conclusion": None,
            "continued_data": {},
        }
        with (
            mock.patch.object(plan066_contract, "valid_full_parameter_coverage", return_value=True),
            mock.patch.object(plan066_contract, "valid_stage_receipt", return_value=True),
            mock.patch.object(plan066_contract, "valid_checkpoint_receipt", return_value=True),
            mock.patch.object(
                plan066_contract,
                "resume_receipt_evidence_matches_coverage",
                return_value=True,
            ),
            mock.patch.object(plan066_contract, "_finite_timing", return_value=True),
            mock.patch.object(plan066_contract, "_valid_continued_data", return_value=True),
        ):
            validate_plan066_resume_receipt(receipt, formal=True)
            mutations = {
                "same_pid": {**resume_process, "pid": start_process["pid"]},
                "same_instance": {
                    **resume_process,
                    "instance_id": start_process["instance_id"],
                },
                "malformed": {**resume_process, "pid": True},
            }
            for name, changed_process in mutations.items():
                changed = copy.deepcopy(receipt)
                changed["resume_process"] = changed_process
                with self.subTest(name=name), self.assertRaisesRegex(
                    FullModelTrainingError, "plan066_resume_receipt_invalid"
                ):
                    validate_plan066_resume_receipt(changed, formal=True)

    def test_provider_facts_bind_continuous_budget_terminal_compute_and_candidates(self):
        identity = {
            "selected_gpu": "NVIDIA H100 PCIe",
            "winner_lock_sha256": "a" * 64,
            "winner_lock": {
                "evidence": {"network_volume_id": "hi3iaz8rsr"},
            },
        }
        candidates = [
            {"stage": stage, "candidate_manifest_sha256": character * 64}
            for stage, character in zip(("C1", "C2", "C3"), "bcd")
        ]
        captured_balance = 10.0
        delta = PLAN060_BASELINE_BALANCE_USD - captured_balance
        facts = {
            "schema": "rondo-publication-critic-plan066-provider-terminal-facts-v1",
            "captured_at": "2026-08-24T12:00:00Z",
            "provider": {
                "name": "RunPod",
                "pod_id": "oe6gbptvq5yhja",
                "pod_name": "rondo-plan060-pcie-replacement-01",
                "gpu_id": "NVIDIA H100 PCIe",
                "gpu_count": 1,
                "data_center_id": "US-KS-2",
                "cuda_version": "13.0",
                "gpu_hourly_rate_usd": 2.89,
                "winner_lock_sha256": "a" * 64,
            },
            "billing": {
                "provider_bill_settled": True,
                "continuous_baseline_balance_usd": PLAN060_BASELINE_BALANCE_USD,
                "captured_balance_usd": captured_balance,
                "balance_delta_cost_usd": delta,
                "actual_plan060_plan066_cost_usd": delta,
                "conservative_continuous_cost_usd": delta,
                "account_current_spend_per_hr_usd": 0.017,
            },
            "resources": {
                "legacy_pod_deleted": True,
                "loser_volume_deleted": True,
                "compute_pod_terminal_state": "TERMINATED",
                "task_compute_cost_usd_per_hr": 0,
                "winner_volume": {
                    "id": "hi3iaz8rsr",
                    "terminal_state": "retained_candidate_assets",
                    "continuing_storage_cost_usd_per_hr": 0.017,
                },
                "candidate_retention": {
                    item["stage"]: {
                        "candidate_manifest_sha256": item["candidate_manifest_sha256"],
                        "location": "winner_volume",
                        "verified": True,
                    }
                    for item in candidates
                },
                "full_checkpoint_terminal_state": "deleted",
            },
            "conclusion": {
                "recommendation": "GO_RECOMMENDED",
                "reason_codes": ["formal_chain_complete"],
            },
        }
        validated = validate_plan066_provider_facts(
            facts,
            identity=identity,
            candidate_receipts=candidates,
            hard_cap_usd=23.0,
        )
        self.assertEqual(validated["resources"]["compute_pod_terminal_state"], "TERMINATED")
        changed = copy.deepcopy(facts)
        changed["resources"]["candidate_retention"]["C3"]["candidate_manifest_sha256"] = "e" * 64
        with self.assertRaisesRegex(FullModelTrainingError, "plan066_provider_facts_invalid"):
            validate_plan066_provider_facts(
                changed,
                identity=identity,
                candidate_receipts=candidates,
                hard_cap_usd=23.0,
            )

        console_facts = copy.deepcopy(facts)
        console_facts["schema"] = (
            "rondo-publication-critic-plan066-provider-terminal-facts-v2"
        )
        console_facts["billing"] = {
            "provider_bill_settled": True,
            "authoritative_cost_source": "provider_console_task_period_total",
            "provider_console_breakdown": {
                "date": "2026-08-24",
                "total_usd": 10.476,
                "cloud_gpu_usd": 10.207,
                "storage_usd": 0.269,
                "other_usd": 0.0,
            },
            "captured_balance_usd": 11.839365383,
            "account_balance_context_only": True,
            "actual_plan060_plan066_cost_usd": 10.476,
            "conservative_continuous_cost_usd": 10.476,
            "account_current_spend_per_hr_usd": 0.006,
        }
        validated = validate_plan066_provider_facts(
            console_facts,
            identity=identity,
            candidate_receipts=candidates,
            hard_cap_usd=23.0,
        )
        self.assertEqual(
            validated["billing"]["authoritative_cost_source"],
            "provider_console_task_period_total",
        )
        changed = copy.deepcopy(console_facts)
        changed["billing"]["captured_balance_usd"] = 0.0
        validate_plan066_provider_facts(
            changed,
            identity=identity,
            candidate_receipts=candidates,
            hard_cap_usd=23.0,
        )
        changed = copy.deepcopy(console_facts)
        changed["billing"]["provider_console_breakdown"]["storage_usd"] = 0.268
        with self.assertRaisesRegex(FullModelTrainingError, "plan066_provider_facts_invalid"):
            validate_plan066_provider_facts(
                changed,
                identity=identity,
                candidate_receipts=candidates,
                hard_cap_usd=23.0,
            )
        changed = copy.deepcopy(console_facts)
        changed["billing"]["provider_console_breakdown"].update(
            {"total_usd": 23.001, "cloud_gpu_usd": 22.732}
        )
        changed["billing"]["actual_plan060_plan066_cost_usd"] = 23.001
        changed["billing"]["conservative_continuous_cost_usd"] = 23.001
        with self.assertRaisesRegex(FullModelTrainingError, "plan066_provider_facts_invalid"):
            validate_plan066_provider_facts(
                changed,
                identity=identity,
                candidate_receipts=candidates,
                hard_cap_usd=23.0,
            )
        changed = copy.deepcopy(console_facts)
        changed["billing"]["conservative_continuous_cost_usd"] = 11.7559990136
        with self.assertRaisesRegex(FullModelTrainingError, "plan066_provider_facts_invalid"):
            validate_plan066_provider_facts(
                changed,
                identity=identity,
                candidate_receipts=candidates,
                hard_cap_usd=23.0,
            )
        changed = copy.deepcopy(facts)
        changed["provider"]["pod_id"] = "other-pod"
        with self.assertRaisesRegex(FullModelTrainingError, "plan066_provider_facts_invalid"):
            validate_plan066_provider_facts(
                changed,
                identity=identity,
                candidate_receipts=candidates,
                hard_cap_usd=23.0,
            )


class _FakeTensor:
    def __init__(self, value, *, shape=()):
        self.value = value
        self.shape = shape

    def to(self, _device):
        return self

    def sum(self):
        return _FakeTensor(self.value)

    def item(self):
        return self.value

    def float(self):
        return self

    def all(self):
        return self

    def __getitem__(self, item):
        if isinstance(item, tuple):
            return _FakeTensor([self.value[0][0]], shape=(1,))
        if isinstance(self.value, list):
            return _FakeTensor(self.value[item])
        raise IndexError(item)


class _InferenceMode:
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _FakeTorch:
    class cuda:
        @staticmethod
        def synchronize(_device):
            return None

    @staticmethod
    def inference_mode():
        return _InferenceMode()

    @staticmethod
    def isfinite(_value):
        return _FakeTensor(True)


class _FakeParameter:
    grad = None


class _FakeModel:
    def __init__(self):
        self.training = True
        self._calls = 0
        self._parameters = [_FakeParameter()]

    def parameters(self):
        return iter(self._parameters)

    def eval(self):
        self.training = False

    def train(self):
        self.training = True

    def __call__(self, **_batch):
        self._calls += 1
        score = [-1.0, 1.0, 2.0, 0.5][self._calls - 1]
        return SimpleNamespace(logits=_FakeTensor([[score]], shape=(1, 1)))


class _FakeTokenizer:
    padding_side = "right"

    def pad(self, _value, **_kwargs):
        return {
            "input_ids": _FakeTensor(2),
            "attention_mask": _FakeTensor(2),
        }


class _FakeOptimizer:
    def __init__(self):
        self.state = {}
        self.param_groups = [{"lr": 4e-4}]

    def zero_grad(self, *, set_to_none):
        if not set_to_none:
            raise AssertionError


class Plan066ArtifactTests(unittest.TestCase):
    def test_validation_uses_inference_and_preserves_training_state(self):
        ids = ["a", "b", "c", "d"]
        dataset = ValidationDataset(
            input_identity={},
            rubric="rubric",
            packets={candidate_id: {"packet": {}} for candidate_id in ids},
            supervision={
                candidate_id: {
                    "candidate_id": candidate_id,
                    "binary_label": "PASS" if candidate_id in {"b", "c"} else "REWRITE",
                }
                for candidate_id in ids
            },
            pairs={
                "boundary": {
                    "kind": "boundary",
                    "preferred_candidate_id": "b",
                    "dispreferred_candidate_id": "a",
                },
                "within": {
                    "kind": "within_pass",
                    "preferred_candidate_id": "c",
                    "dispreferred_candidate_id": "d",
                },
            },
        )
        context = SimpleNamespace(
            torch=_FakeTorch(),
            model=_FakeModel(),
            optimizer=_FakeOptimizer(),
            scheduler=SimpleNamespace(state_dict=lambda: {"last_epoch": 3}),
            exact_tokenizer=SimpleNamespace(tokenizer=_FakeTokenizer()),
            device="cuda:0",
        )
        tokenized = {candidate_id: SimpleNamespace(input_ids=(1, 2)) for candidate_id in ids}
        with mock.patch(
            "rondo_eval.publication_critic.full_model_training.objective._torch",
            return_value=_FakeTorch(),
        ):
            receipt = run_validation(context, dataset, tokenized, stage="C1")
        self.assertTrue(context.model.training)
        self.assertEqual(context.model._calls, 4)
        self.assertTrue(receipt["optimizer_state_unchanged"])
        self.assertTrue(receipt["all_parameter_grads_none"])

    def test_candidate_manifest_detects_tampering(self):
        class Model:
            @staticmethod
            def save_pretrained(root, **_kwargs):
                header = json.dumps(
                    {
                        "weight": {
                            "dtype": "F32",
                            "shape": [1],
                            "data_offsets": [0, 4],
                        }
                    },
                    separators=(",", ":"),
                ).encode("utf-8")
                padding = (-len(header)) % 8
                header += b" " * padding
                (root / "model.safetensors").write_bytes(
                    len(header).to_bytes(8, "little") + header + b"\0\0\0\0"
                )
                (root / "config.json").write_text("{}", encoding="utf-8")

        class Tokenizer:
            @staticmethod
            def save_pretrained(root):
                (root / "tokenizer_config.json").write_text("{}", encoding="utf-8")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "candidate"
            identity = {"run": "formal"}
            receipt = save_stage_candidate(
                root,
                model=Model(),
                tokenizer=Tokenizer(),
                stage="C1",
                global_step=1,
                identity=identity,
            )
            self.assertEqual(receipt["status"], "verified")
            (root / "config.json").write_text('{"changed":true}', encoding="utf-8")
            with self.assertRaisesRegex(FullModelTrainingError, "plan066_candidate_tree_mismatch"):
                verify_stage_candidate(root, identity=identity)


if __name__ == "__main__":
    unittest.main()
