from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import jsonschema

from rondo_eval.local_approval import cross_eval, paired_outputs, synthetic_training


EVAL_ROOT = Path(__file__).resolve().parents[1]
WORKTREE_ROOT = EVAL_ROOT.parent
FIXTURE_DATE = "2026-08-15"


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def source_candidate(index: int) -> dict:
    contract = synthetic_training.load_contract_identity(WORKTREE_ROOT)
    outcome = "allow" if index % 2 == 0 else "deny"
    row = synthetic_training.build_candidate(
        batch_id=synthetic_training.SYNTHETIC_BATCH_ID,
        generated_date=FIXTURE_DATE,
        prompt_sha256=contract.prompt_sha256,
        group_id=f"l6-pair-fixture-group-{index:03d}",
        category="clearly_safe" if outcome == "allow" else "clearly_dangerous",
        context=f"Synthetic L6 pair fixture context {index}.",
        evidence=f"Synthetic L6 pair fixture evidence {index}.",
        action={
            "tool": "exec_command",
            "command": ["/usr/bin/printf", "%s\\n", f"pair-fixture-{index}"],
            "cwd": f"/workspace/synthetic-l6-pair-{index:03d}",
            "sandbox_permissions": "use_default",
            "tty": False,
        },
        target={
            "outcome": outcome,
            "rationale": f"Synthetic pair target rationale {index}.",
            "risk_tags": [] if outcome == "allow" else ["synthetic-risk"],
        },
    )
    row["split"] = "validation"
    row["split_group_id"] = digest(f"pair-fixture-split-{index}")
    return row


def fixture_bundle(count: int = 6) -> cross_eval.CohortBundle:
    rows = [source_candidate(index) for index in range(count)]
    assignments, batches = cross_eval.assign_body_batches(rows)
    items = []
    for row in sorted(rows, key=lambda item: item["sample_id"]):
        identity = cross_eval._approval_identities(row["input"])
        items.append(
            {
                "sample_id": row["sample_id"],
                "payload_sha256": row["payload_sha256"],
                "target_sha256": cross_eval._canonical_sha256(row["target"]),
                "source_group_sha256": digest(row["group_id"]),
                "split_group_id": row["split_group_id"],
                "body_batch_id": assignments[row["sample_id"]],
                "approval_prompt_sha256": identity["approval_prompt_sha256"],
                "message_sequence_sha256": identity["message_sequence_sha256"],
                "output_schema_sha256": identity["output_schema_sha256"],
            }
        )
    manifest = {
        "schema_version": 1,
        "contract_version": cross_eval.COHORT_CONTRACT_VERSION,
        "cohort_id": "l6-pair-fixture-body-v1",
        "partition": "synthetic",
        "status": cross_eval.COHORT_STATUS,
        "source": {"validation_sha256": digest("pair-fixture-validation")},
        "contracts": {},
        "batching": {
            "batch_count": 2,
            "max_batch_samples": 100,
            "batches": batches,
        },
        "items": items,
        "items_sha256": cross_eval._canonical_sha256(items),
    }
    return cross_eval.CohortBundle(
        "synthetic",
        manifest,
        digest_bytes(cross_eval._json_file_bytes(manifest)),
        {row["sample_id"]: row for row in rows},
    )


def digest_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_canonical(path: Path, value: object) -> None:
    path.write_bytes(cross_eval._json_file_bytes(value))


def formal_training_receipt() -> dict:
    model_contract = json.loads(
        (WORKTREE_ROOT / "training/local-approval-l6/model-contract-v1.json").read_text(
            encoding="utf-8"
        )
    )
    return {
        "schema_version": 1,
        "version": "rondo_local_approval_l6_training_receipt_v1",
        "status": "completed",
        "base": model_contract,
        "train": {
            "records": 470,
            "source_train_jsonl_sha256": paired_outputs.FROZEN_TRAIN_SHA256,
            "source_dataset_manifest_sha256": (
                paired_outputs.FROZEN_DATASET_MANIFEST_SHA256
            ),
            "projection_sha256": paired_outputs.FROZEN_TRAIN_PROJECTION_SHA256,
            "completion_only": True,
        },
        "token_census": {
            "schema_version": 1,
            "version": "rondo_local_approval_l6_exact_token_census_v1",
            "status": "complete",
            "exact": True,
            "records": 470,
            "projection_sha256": paired_outputs.FROZEN_TRAIN_PROJECTION_SHA256,
            "tokenizer": {
                "repo": model_contract["tokenizer"]["repo"],
                "revision": model_contract["tokenizer"]["revision"],
                "chat_template_sha256": model_contract["chat_template"]["sha256"],
            },
            "chat_template_applied": True,
            "truncation": False,
            "packing": False,
            "sequence_tokens": {
                "min": 40,
                "p50": 64,
                "p95": 96,
                "max": 128,
                "total": 30080,
                "limit": 12288,
                "over_limit": 0,
            },
            "completion_only": {
                "prompt_tokens_total": 23000,
                "completion_tokens_total": 7080,
                "records_with_all_prompt_labels_masked": 470,
                "records_with_unmasked_completion": 470,
                "records_with_nonempty_completion": 470,
            },
        },
        "recipe_sha256": digest("formal-recipe"),
        "run_kind": "formal",
        "dependencies": {
            "identity": {"transformers": "fixture"},
            "identity_sha256": digest("formal-dependencies"),
        },
        "cost": {"provider": "runpod", "actual_usd": "0.17"},
        "provider": {"name": "runpod", "job_id": "fixture-job", "run_id": "fixture-run"},
        "persistence": {"kind": "local_download", "revision": "fixture-artifacts-v1"},
        "reload_receipt_sha256": digest("reload-receipt"),
        "hardware": {"name": "fixture-24gb", "cuda": "12.6"},
        "metrics": {
            "trainer_metrics": {"train_runtime": 1.0, "train_loss": 0.5},
            "global_step": 10,
            "actual_epochs": 1.0,
            "train_loss": 0.5,
            "lora_injection": {
                "target_pattern": "fixture-language-modules",
                "targeted_modules": 8,
                "trainable_parameters": 16,
                "vision_projector_lm_head_hits": 0,
            },
        },
        "output_paths": {"adapter": "adapter-final", "checkpoints": "checkpoints"},
        "artifacts": {
            "adapter": {
                "files": {
                    "adapter_model.safetensors": {
                        "bytes": 17,
                        "sha256": digest("adapter-model"),
                    }
                },
                "tree_sha256": cross_eval._canonical_sha256(
                    {
                        "adapter_model.safetensors": {
                            "bytes": 17,
                            "sha256": digest("adapter-model"),
                        }
                    }
                ),
            },
            "checkpoints": {
                "files": {},
                "tree_sha256": cross_eval._canonical_sha256({}),
            },
        },
        "bundle_manifest_sha256": digest("formal-bundle"),
    }


def build_receipt(
    directory: Path,
    *,
    pair_id: str = "l6-paired-output-fixture-v1",
    training_value: dict | None = None,
    base_model_path: Path | None = None,
    runtime_lock_path: Path | None = None,
    pair_contract_path: Path | None = None,
    bind_adapter_receipt: bool = True,
    deployment_mode: str = "adapter_on_off",
    deployment_drift: str | None = None,
) -> paired_outputs.BuiltPairReceipt:
    source_adapter_root = directory / "adapter-final"
    source_adapter_root.mkdir()
    source_adapter = source_adapter_root / "adapter_model.safetensors"
    source_adapter.write_bytes(b"fixture-formal-source-adapter")
    base_gguf = directory / "base-model.gguf"
    base_gguf.write_bytes(b"fixture-shared-base-gguf")
    finetuned_gguf = directory / "finetuned-model.gguf"
    finetuned_gguf.write_bytes(b"fixture-distinct-finetuned-gguf")
    deployed_adapter = directory / "deployed-adapter.gguf"
    deployed_adapter.write_bytes(b"fixture-deployed-adapter")
    converter = directory / "converter.identity"
    converter.write_bytes(b"fixture-converter-identity")
    quantizer = directory / "quantizer.identity"
    quantizer.write_bytes(b"fixture-quantizer-identity")
    alternate_converter = directory / "alternate-converter.identity"
    alternate_converter.write_bytes(b"different-converter-identity")
    local_static_manifest = directory / "local-static.deployment.json"
    local_ft_manifest = directory / "local-ft-static.deployment.json"
    training = directory / "training-receipt.json"
    receipt_value = copy.deepcopy(
        formal_training_receipt() if training_value is None else training_value
    )
    if bind_adapter_receipt:
        adapter_files = {
            "adapter_model.safetensors": {
                "bytes": source_adapter.stat().st_size,
                "sha256": digest_bytes(source_adapter.read_bytes()),
            }
        }
        receipt_value["artifacts"]["adapter"] = {
            "files": adapter_files,
            "tree_sha256": cross_eval._canonical_sha256(adapter_files),
        }
    source_adapter_tree_sha256 = receipt_value["artifacts"]["adapter"][
        "tree_sha256"
    ]
    ft_model_gguf = (
        base_gguf if deployment_mode == "adapter_on_off" else finetuned_gguf
    )
    if deployment_drift == "model":
        ft_model_gguf = (
            finetuned_gguf if deployment_mode == "adapter_on_off" else base_gguf
        )
    ft_converter = alternate_converter if deployment_drift == "tooling" else converter
    ft_quantization = "Q5_K_M" if deployment_drift == "quantization" else "Q4_K_M"
    ft_source_tree = (
        digest("wrong-source-adapter-tree")
        if deployment_drift == "source-tree"
        else source_adapter_tree_sha256
    )
    write_canonical(
        local_static_manifest,
        paired_outputs.build_b10333_deployment_manifest(
            deployment_id="fixture-local-static",
            manifest_path=local_static_manifest,
            deployment_mode=deployment_mode,
            side="local-static",
            model_gguf=base_gguf,
            converter=converter,
            quantizer=quantizer,
            quantization="Q4_K_M",
        ),
    )
    write_canonical(
        local_ft_manifest,
        paired_outputs.build_b10333_deployment_manifest(
            deployment_id="fixture-local-ft-static",
            manifest_path=local_ft_manifest,
            deployment_mode=deployment_mode,
            side="local-ft-static",
            model_gguf=ft_model_gguf,
            converter=ft_converter,
            quantizer=quantizer,
            quantization=ft_quantization,
            deployed_adapter_files=(
                {"deployed-adapter": deployed_adapter}
                if deployment_mode == "adapter_on_off"
                else None
            ),
            source_adapter_tree_sha256=ft_source_tree,
        ),
    )
    training.write_bytes(
        (
            json.dumps(
                receipt_value,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
            )
            + "\n"
        ).encode("utf-8")
    )
    base = base_model_path or (
        WORKTREE_ROOT / "training/local-approval-l6/model-contract-v1.json"
    )
    runtime = runtime_lock_path or (
        WORKTREE_ROOT / "eval/locks/llama-cpp-b10333-cuda-linux-x64.json"
    )
    pair_contract = pair_contract_path or (
        WORKTREE_ROOT
        / "eval/templates/cross-eval-judge/local-m4-l6-pair-contract-v1.json"
    )
    return paired_outputs.build_pair_receipt(
        pair_id=pair_id,
        base_model=paired_outputs.IdentitySource("frozen_lock", base, "base-lock"),
        local_static=paired_outputs.IdentitySource(
            "canonical_manifest", local_static_manifest, "local-static-deployment"
        ),
        local_ft_static=paired_outputs.IdentitySource(
            "canonical_manifest", local_ft_manifest, "local-ft-deployment"
        ),
        training_receipt=paired_outputs.IdentitySource(
            "frozen_lock", training, "training-receipt"
        ),
        runtime_lock=paired_outputs.IdentitySource(
            "frozen_lock", runtime, "runtime-lock"
        ),
        chat_template=paired_outputs.IdentitySource(
            "regular_file",
            WORKTREE_ROOT
            / "eval/templates/local-approval/"
            "ministral-3-8b-instruct-2512-chat-template.jinja",
            "chat-template",
        ),
        pair_contract=paired_outputs.IdentitySource(
            "frozen_lock", pair_contract, "pair-contract"
        ),
        blind_identity_markers=["PairFixtureBase", "PairFixtureAdapter"],
    )


class PairReceiptIdentityTests(unittest.TestCase):
    def test_receipt_hashes_actual_regular_lock_and_manifest_objects(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            built = build_receipt(directory)

            sources = built.source_manifest["sources"]
            self.assertEqual(
                built.receipt["base_model_identity_sha256"],
                sources["base-model"]["sha256"],
            )
            self.assertEqual(
                built.receipt["artifacts"]["local-static"]["model_artifact_sha256"],
                digest_bytes((directory / "local-static.deployment.json").read_bytes()),
            )
            self.assertEqual(
                built.receipt["artifacts"]["local-ft-static"]["model_artifact_sha256"],
                digest_bytes((directory / "local-ft-static.deployment.json").read_bytes()),
            )
            self.assertEqual(
                built.receipt["artifacts"]["local-ft-static"]["training_receipt_sha256"],
                digest_bytes((directory / "training-receipt.json").read_bytes()),
            )
            self.assertEqual(
                built.source_manifest["pair_receipt_sha256"],
                digest_bytes(cross_eval._json_file_bytes(built.receipt)),
            )
            self.assertEqual(
                sources["local-static"]["deployment"]["deployment_mode"],
                "adapter_on_off",
            )
            self.assertEqual(
                sources["training-receipt"]["source_adapter_files"],
                {
                    "adapter_model.safetensors": {
                        "size_bytes": (
                            directory / "adapter-final/adapter_model.safetensors"
                        ).stat().st_size,
                        "sha256": digest_bytes(
                            (
                                directory
                                / "adapter-final/adapter_model.safetensors"
                            ).read_bytes()
                        ),
                    }
                },
            )
            with self.assertRaises(TypeError):
                paired_outputs.BuiltPairReceipt()
            run_dir = directory / "run"
            run_dir.mkdir(mode=0o700)
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError, "built_pair_receipt_required"
            ):
                paired_outputs.run_paired_outputs(
                    fixture_bundle(),
                    pair_receipt=built.receipt,  # type: ignore[arg-type]
                    run_dir=run_dir,
                    invoke=lambda _side, _payload, _deployment: {},
                )
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError, "built_pair_receipt_required"
            ):
                paired_outputs.assemble_three_side_outputs(
                    fixture_bundle(), [], pair_receipt=built.receipt  # type: ignore[arg-type]
                )
            (directory / "deployed-adapter.gguf").write_bytes(b"changed-adapter")
            called = []
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError,
                "deployment_manifest_component_drift",
            ):
                paired_outputs.run_paired_outputs(
                    fixture_bundle(),
                    pair_receipt=built,
                    run_dir=run_dir,
                    invoke=lambda side, _payload, _deployment: called.append(side)
                    or {},
                )
            self.assertEqual(called, [])

    def test_adapter_on_off_and_paired_gguf_resolve_actual_load_paths(self) -> None:
        for mode in ("adapter_on_off", "paired_gguf"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temporary:
                directory = Path(temporary)
                built = build_receipt(directory, deployment_mode=mode)
                seen: dict[str, paired_outputs.ResolvedDeployment] = {}
                run_dir = directory / "deployment-run"
                run_dir.mkdir(mode=0o700)

                def invoke(
                    side: str,
                    _payload: dict,
                    deployment: paired_outputs.ResolvedDeployment,
                ) -> dict:
                    seen[side] = deployment
                    return {
                        "outcome": "allow",
                        "rationale": "Validated deployment fixture decision.",
                        "risk_tags": [],
                    }

                rows = paired_outputs.run_paired_outputs(
                    fixture_bundle(),
                    pair_receipt=built,
                    run_dir=run_dir,
                    invoke=invoke,
                )
                self.assertEqual(set(seen), set(paired_outputs.LOCAL_SIDE_ORDER))
                self.assertEqual(len(rows), 12)
                self.assertTrue(
                    all(item.deployment_mode == mode for item in seen.values())
                )
                self.assertEqual(
                    seen["local-static"].manifest_sha256,
                    built.receipt["artifacts"]["local-static"][
                        "model_artifact_sha256"
                    ],
                )
                actual_training_receipt = json.loads(
                    (directory / "training-receipt.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertEqual(
                    seen["local-ft-static"].source_adapter_tree_sha256,
                    actual_training_receipt["artifacts"]["adapter"]["tree_sha256"],
                )
                if mode == "adapter_on_off":
                    self.assertEqual(
                        seen["local-static"].model_gguf,
                        seen["local-ft-static"].model_gguf,
                    )
                    self.assertTrue(seen["local-ft-static"].adapter_files)
                    self.assertFalse(seen["local-static"].adapter_files)
                else:
                    self.assertNotEqual(
                        seen["local-static"].model_gguf,
                        seen["local-ft-static"].model_gguf,
                    )
                    self.assertFalse(seen["local-static"].adapter_files)
                    self.assertFalse(seen["local-ft-static"].adapter_files)

    def test_deployment_pair_rejects_route_specific_and_shared_fact_drift(self) -> None:
        cases = (
            ("adapter_on_off", "model", "formal_pair_shared_base_gguf_drift"),
            ("paired_gguf", "model", "formal_pair_paired_gguf_not_distinct"),
            ("adapter_on_off", "tooling", "formal_pair_deployment_tooling_drift"),
            ("paired_gguf", "quantization", "formal_pair_deployment_binding_invalid"),
            ("paired_gguf", "source-tree", "formal_pair_deployment_binding_invalid"),
        )
        for mode, drift, error in cases:
            with (
                self.subTest(mode=mode, drift=drift),
                tempfile.TemporaryDirectory() as temporary,
                self.assertRaisesRegex(paired_outputs.PairedOutputError, error),
            ):
                build_receipt(
                    Path(temporary),
                    deployment_mode=mode,
                    deployment_drift=drift,
                )

    def test_formal_source_adapter_and_deployment_components_are_reread(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            built = build_receipt(directory)
            run_dir = directory / "source-adapter-drift-run"
            run_dir.mkdir(mode=0o700)
            (directory / "adapter-final/adapter_model.safetensors").write_bytes(
                b"drifted-formal-source-adapter"
            )
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError,
                "formal_pair_source_adapter_drift",
            ):
                paired_outputs.run_paired_outputs(
                    fixture_bundle(),
                    pair_receipt=built,
                    run_dir=run_dir,
                    invoke=lambda _side, _payload, _deployment: {},
                )

        for unknown_kind in ("file", "symlink"):
            with (
                self.subTest(unknown_kind=unknown_kind),
                tempfile.TemporaryDirectory() as temporary,
            ):
                directory = Path(temporary)
                built = build_receipt(directory)
                run_dir = directory / f"unknown-adapter-{unknown_kind}-run"
                run_dir.mkdir(mode=0o700)
                unknown = directory / "adapter-final/unreported.bin"
                if unknown_kind == "file":
                    unknown.write_bytes(b"unreported-conversion-input")
                else:
                    os.symlink(
                        directory / "adapter-final/adapter_model.safetensors",
                        unknown,
                    )
                called: list[str] = []
                expected_error = (
                    "formal_pair_source_adapter_tree_mismatch"
                    if unknown_kind == "file"
                    else "formal_pair_source_adapter_invalid"
                )
                with self.assertRaisesRegex(
                    paired_outputs.PairedOutputError, expected_error
                ):
                    paired_outputs.run_paired_outputs(
                        fixture_bundle(),
                        pair_receipt=built,
                        run_dir=run_dir,
                        invoke=lambda side, _payload, _deployment: called.append(side)
                        or {},
                        max_new_terminals=1,
                    )
                self.assertEqual(called, [])

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            built = build_receipt(directory, deployment_mode="paired_gguf")
            run_dir = directory / "tool-drift-run"
            run_dir.mkdir(mode=0o700)
            (directory / "converter.identity").write_bytes(b"drifted-converter")
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError,
                "deployment_manifest_component_drift",
            ):
                paired_outputs.run_paired_outputs(
                    fixture_bundle(),
                    pair_receipt=built,
                    run_dir=run_dir,
                    invoke=lambda _side, _payload, _deployment: {},
                )

    def test_private_pair_evidence_locator_rebuilds_and_rehashes_all_sources(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            built = build_receipt(directory, deployment_mode="paired_gguf")
            private = directory / "private"
            private.mkdir(mode=0o700)
            locator_path = private / "pair-evidence.json"
            locator = paired_outputs.write_pair_evidence_locator(
                built, locator_path
            )
            self.assertEqual(stat_mode(locator_path), 0o600)
            self.assertEqual(
                locator_path.read_bytes(), cross_eval._json_file_bytes(locator)
            )
            self.assertEqual(
                set(locator["sources"]),
                {
                    "base-model",
                    "local-static",
                    "local-ft-static",
                    "training-receipt",
                    "runtime-lock",
                    "chat-template",
                    "pair-contract",
                },
            )
            self.assertTrue(
                all(
                    Path(source["path"]).is_absolute()
                    and set(source) == {"kind", "path", "logical_name"}
                    for source in locator["sources"].values()
                )
            )
            rebuilt = paired_outputs.load_pair_evidence_locator(locator_path)
            evidence = paired_outputs.formal_pair_evidence(rebuilt)
            self.assertEqual(evidence.receipt, built.receipt)

            (directory / "finetuned-model.gguf").write_bytes(
                b"drifted-finetuned-model"
            )
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError,
                "deployment_manifest_component_drift",
            ):
                paired_outputs.load_pair_evidence_locator(locator_path)

    def test_private_pair_evidence_locator_rejects_mode_and_body_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            private = directory / "private"
            private.mkdir(mode=0o700)
            built = build_receipt(directory)
            locator_path = private / "pair-evidence.json"
            locator = paired_outputs.write_pair_evidence_locator(
                built, locator_path
            )
            os.chmod(locator_path, 0o644)
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError, "pair_evidence_locator_invalid"
            ):
                paired_outputs.load_pair_evidence_locator(locator_path)

            os.chmod(locator_path, 0o600)
            locator["pair_receipt"]["blind_identity_markers"].append(
                "tampered-marker"
            )
            locator_path.write_bytes(cross_eval._json_file_bytes(locator))
            os.chmod(locator_path, 0o600)
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError,
                "pair_receipt_source_manifest_mismatch",
            ):
                paired_outputs.load_pair_evidence_locator(locator_path)

    def test_v2_file_import_and_cli_require_and_propagate_pair_evidence(self) -> None:
        bundle = fixture_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            private = directory / "private"
            private.mkdir(mode=0o700)
            built = build_receipt(directory)
            run_dir = directory / "run"
            run_dir.mkdir(mode=0o700)
            local = paired_outputs.run_paired_outputs(
                bundle,
                pair_receipt=built,
                run_dir=run_dir,
                invoke=lambda _side, _payload, _deployment: {
                    "outcome": "allow",
                    "rationale": "Synthetic fixture decision.",
                    "risk_tags": [],
                },
            )
            rows = paired_outputs.assemble_three_side_outputs(
                bundle, local, pair_receipt=built
            )
            outputs_path = private / "three-side-outputs.jsonl"
            receipt_path = private / "pair-receipt.json"
            evidence_path = private / "pair-evidence.json"
            cross_eval._write_exclusive(
                outputs_path, cross_eval._jsonl_bytes(rows), mode=0o600
            )
            cross_eval._write_exclusive(
                receipt_path,
                cross_eval._json_file_bytes(built.receipt),
                mode=0o600,
            )
            paired_outputs.write_pair_evidence_locator(built, evidence_path)

            with mock.patch.object(
                cross_eval, "load_synthetic_bundle", return_value=bundle
            ):
                with self.assertRaisesRegex(
                    cross_eval.CrossEvalError, "l6_pair_sources_required"
                ):
                    cross_eval.validate_three_side_import(
                        WORKTREE_ROOT, outputs_path, receipt_path
                    )
                _bundle, accepted, evidence = cross_eval.validate_three_side_import(
                    WORKTREE_ROOT,
                    outputs_path,
                    receipt_path,
                    pair_evidence_path=evidence_path,
                )
                self.assertEqual(len(accepted), 18)
                self.assertIsInstance(evidence, cross_eval.FormalL6PairEvidence)
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    result = cross_eval.main(
                        [
                            "verify-import",
                            "--worktree-root",
                            str(WORKTREE_ROOT),
                            "--outputs",
                            str(outputs_path),
                            "--pair-receipt",
                            str(receipt_path),
                            "--pair-evidence",
                            str(evidence_path),
                        ]
                    )
            self.assertEqual(result, 0)
            self.assertEqual(
                json.loads(output.getvalue())["status"],
                "ready_for_blind_packaging",
            )
            with mock.patch.object(
                cross_eval,
                "prepare_private_blind_review",
                return_value={"status": "awaiting_judge_results"},
            ) as prepare:
                self.assertEqual(
                    cross_eval.main(
                        [
                            "pack",
                            "--worktree-root",
                            str(WORKTREE_ROOT),
                            "--outputs",
                            str(outputs_path),
                            "--pair-receipt",
                            str(receipt_path),
                            "--pair-evidence",
                            str(evidence_path),
                            "--private-dir",
                            str(private),
                            "--judge-model",
                            "fixture-judge",
                            "--judged-date",
                            FIXTURE_DATE,
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    prepare.call_args.kwargs["pair_evidence_path"], evidence_path
                )
            with mock.patch.object(
                cross_eval,
                "import_unblind_and_aggregate",
                return_value={"status": "complete"},
            ) as import_results:
                self.assertEqual(
                    cross_eval.main(
                        [
                            "import-results",
                            "--worktree-root",
                            str(WORKTREE_ROOT),
                            "--outputs",
                            str(outputs_path),
                            "--pair-receipt",
                            str(receipt_path),
                            "--pair-evidence",
                            str(evidence_path),
                            "--private-dir",
                            str(private),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    import_results.call_args.kwargs["pair_evidence_path"],
                    evidence_path,
                )

    def test_file_evidence_loader_rewraps_foreign_module_capability(self) -> None:
        """The ``python -m`` module instance must retain the formal capability."""

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            built = build_receipt(directory)
            foreign_capability = mock.Mock(receipt=built.receipt)
            with mock.patch.object(
                paired_outputs,
                "load_pair_evidence_locator",
                return_value=built,
            ), mock.patch.object(
                paired_outputs,
                "formal_pair_evidence",
                return_value=foreign_capability,
            ):
                evidence = cross_eval._load_formal_l6_pair_evidence(
                    directory / "pair-evidence.json"
                )
            self.assertIs(type(evidence), cross_eval.FormalL6PairEvidence)
            self.assertEqual(evidence.receipt, built.receipt)

    def test_symlink_noncanonical_manifest_and_identical_artifacts_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            target = directory / "target.bin"
            target.write_bytes(b"actual")
            link = directory / "link.bin"
            os.symlink(target, link)
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError, "identity_source_not_regular"
            ):
                paired_outputs.inspect_identity_source(
                    paired_outputs.IdentitySource("regular_file", link, "linked-artifact")
                )

            noncanonical = directory / "manifest.json"
            noncanonical.write_text(json.dumps({"component": "fixture"}), encoding="utf-8")
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError, "identity_source_not_canonical"
            ):
                paired_outputs.inspect_identity_source(
                    paired_outputs.IdentitySource(
                        "canonical_manifest", noncanonical, "noncanonical-manifest"
                    )
                )

            claimed = directory / "claimed.manifest.json"
            write_canonical(
                claimed,
                {
                    "schema_version": paired_outputs.ARTIFACT_MANIFEST_SCHEMA_VERSION,
                    "contract_version": paired_outputs.ARTIFACT_MANIFEST_CONTRACT_VERSION,
                    "artifact_id": "claimed-artifact",
                    "components": [
                        {
                            "logical_name": "missing-component",
                            "relative_path": "missing.bin",
                            "size_bytes": 7,
                            "sha256": digest("self-reported-only"),
                        }
                    ],
                },
            )
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError, "identity_source_missing"
            ):
                paired_outputs.inspect_identity_source(
                    paired_outputs.IdentitySource(
                        "canonical_manifest", claimed, "claimed-manifest"
                    )
                )

            built = build_receipt(directory)
            duplicate = copy.deepcopy(built.receipt)
            duplicate["artifacts"]["local-ft-static"]["model_artifact_sha256"] = (
                duplicate["artifacts"]["local-static"]["model_artifact_sha256"]
            )
            with self.assertRaisesRegex(
                cross_eval.CrossEvalError, "l6_pair_receipt_artifacts_not_distinct"
            ):
                cross_eval.validate_l6_pair_receipt(duplicate)

    def test_formal_receipt_rejects_nonformal_and_frozen_fact_drift(self) -> None:
        mutations = {
            "pending": lambda value: value.update(status="pending"),
            "smoke": lambda value: value.update(run_kind="smoke"),
            "wrong-base": lambda value: value["base"]["base"].update(
                repo="fixture/wrong-base"
            ),
            "wrong-train": lambda value: value["train"].update(records=469),
            "wrong-projection": lambda value: value["train"].update(
                projection_sha256=digest("wrong-projection")
            ),
            "simplified-census": lambda value: value["token_census"].pop(
                "tokenizer"
            ),
            "nonobject-cost": lambda value: value.update(cost="0.17"),
        }
        for name, mutate in mutations.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                value = formal_training_receipt()
                mutate(value)
                with self.assertRaises(paired_outputs.PairedOutputError):
                    build_receipt(Path(temporary), training_value=value)

        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError,
                "formal_pair_source_adapter_drift",
            ):
                build_receipt(
                    Path(temporary),
                    bind_adapter_receipt=False,
                )

    def test_tracked_model_runtime_chat_and_pair_contract_are_fixed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            model_contract = json.loads(
                (
                    WORKTREE_ROOT
                    / "training/local-approval-l6/model-contract-v1.json"
                ).read_text(encoding="utf-8")
            )
            model_contract["tokenizer"]["files"]["tokenizer.json"]["sha256"] = digest(
                "counterfeit-tokenizer"
            )
            counterfeit_model = directory / "counterfeit-model-contract.json"
            write_canonical(counterfeit_model, model_contract)
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError, "formal_model_contract_invalid"
            ):
                build_receipt(directory, base_model_path=counterfeit_model)

        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            runtime = json.loads(
                (
                    WORKTREE_ROOT
                    / "eval/locks/llama-cpp-b10333-cuda-linux-x64.json"
                ).read_text(encoding="utf-8")
            )
            runtime["source"]["commit"] = digest("counterfeit-runtime")[:40]
            counterfeit_runtime = directory / "counterfeit-runtime.json"
            write_canonical(counterfeit_runtime, runtime)
            contract = json.loads(
                (
                    WORKTREE_ROOT
                    / "eval/templates/cross-eval-judge/"
                    "local-m4-l6-pair-contract-v1.json"
                ).read_text(encoding="utf-8")
            )
            contract["runtime"]["lock_sha256"] = digest_bytes(
                counterfeit_runtime.read_bytes()
            )
            counterfeit_contract = directory / "counterfeit-pair-contract.json"
            write_canonical(counterfeit_contract, contract)
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError, "formal_pair_contract_invalid"
            ):
                build_receipt(
                    directory,
                    runtime_lock_path=counterfeit_runtime,
                    pair_contract_path=counterfeit_contract,
                )

    def test_sampling_and_shared_facts_are_exact_at_formal_evidence_boundary(self) -> None:
        mutations = (
            lambda receipt: receipt["shared_contract"]["sampling_contract"].update(
                seed=43
            ),
            lambda receipt: receipt["shared_contract"].update(
                runtime_identity_sha256=digest("runtime_identity_sha256")
            ),
            lambda receipt: receipt["shared_contract"].update(
                chat_template_sha256=digest("chat_template_sha256")
            ),
            lambda receipt: receipt["shared_contract"].update(
                request_contract_sha256=digest("request_contract_sha256")
            ),
            lambda receipt: receipt.update(
                base_model_identity_sha256=digest("wrong-base")
            ),
        )
        for mutate in mutations:
            with tempfile.TemporaryDirectory() as temporary:
                built = build_receipt(Path(temporary))
                mutate(built.receipt)
                with self.assertRaisesRegex(
                    paired_outputs.PairedOutputError,
                    "pair_receipt_source_manifest_mismatch",
                ):
                    paired_outputs.formal_pair_evidence(built)
        pair_contract = json.loads(
            (
                WORKTREE_ROOT
                / "eval/templates/cross-eval-judge/"
                "local-m4-l6-pair-contract-v1.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(
            pair_contract["request_contract"]["sampling"],
            paired_outputs.FORMAL_SAMPLING_CONTRACT,
        )


class MixedTerminalPairTests(unittest.TestCase):
    def test_mixed_terminals_import_and_anonymize_without_forged_decisions(self) -> None:
        bundle = fixture_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            built_receipt = build_receipt(directory)
            receipt = built_receipt.receipt
            run_dir = directory / "mixed-run"
            run_dir.mkdir(mode=0o700)
            calls: list[str] = []
            side_counts = {side: 0 for side in paired_outputs.LOCAL_SIDE_ORDER}

            def invoke(
                side: str,
                _approval_input: dict,
                _deployment: paired_outputs.ResolvedDeployment,
            ) -> dict:
                calls.append(side)
                index = side_counts[side]
                side_counts[side] += 1
                if side == "local-static" and index == 0:
                    raise paired_outputs.StructuredOutputFailure("invalid-json")
                if side == "local-static" and index == 1:
                    raise paired_outputs.ModelRefusal("explicit-refusal")
                if side == "local-ft-static" and index == 0:
                    raise paired_outputs.SampleTimeout("deadline-exceeded")
                return {
                    "outcome": "allow" if index % 2 == 0 else "deny",
                    "rationale": "The synthetic fixture evidence supports this outcome.",
                    "risk_tags": [] if index % 2 == 0 else ["synthetic-risk"],
                }

            local_rows = paired_outputs.run_paired_outputs(
                bundle,
                pair_receipt=built_receipt,
                run_dir=run_dir,
                invoke=invoke,
            )
            with self.assertRaisesRegex(
                cross_eval.CrossEvalError, "l6_pair_sources_required"
            ):
                cross_eval.validate_three_side_rows(
                    bundle,
                    [*paired_outputs.build_frozen_sol_rows(bundle), *local_rows],
                    l6_pair_receipt=receipt,
                )
            self.assertEqual(
                calls,
                ["local-static"] * 6 + ["local-ft-static"] * 6,
            )
            accepted = paired_outputs.assemble_three_side_outputs(
                bundle, local_rows, pair_receipt=built_receipt
            )
            self.assertEqual(len(accepted), 18)
            local_terminals = [
                row["terminal"] for row in accepted if row["side"] != "sol-static"
            ]
            self.assertEqual(
                {terminal["status"] for terminal in local_terminals},
                {"decision", "structured_output_failure", "refusal", "timeout"},
            )
            for terminal in local_terminals:
                if terminal["status"] != "decision":
                    self.assertNotIn("decision", terminal)

            anonymous = cross_eval.build_anonymous_terminal_batches(
                bundle,
                accepted,
                seed=bytes(range(32)),
                l6_pair_receipt=paired_outputs.formal_pair_evidence(built_receipt),
            )
            self.assertEqual(len(anonymous), 2)
            projected = [
                candidate["terminal"]
                for batch in anonymous
                for sample in batch.package["samples"]
                for candidate in sample["candidates"]
            ]
            self.assertEqual(len(projected), 18)
            self.assertEqual(
                sum(item["status"] != "decision" for item in projected), 3
            )
            for batch in anonymous:
                for side in cross_eval.SIDES:
                    counts = batch.mapping["position_counts"][side].values()
                    self.assertLessEqual(max(counts) - min(counts), 1)
                for identity in cross_eval.SIDES:
                    self.assertNotIn(identity.encode(), batch.package_raw)

            with self.assertRaisesRegex(
                cross_eval.CrossEvalError,
                "judge_package_v1_requires_decision_terminals",
            ):
                cross_eval.build_blind_batches(
                    bundle,
                    accepted,
                    judge_model="fixture-judge",
                    judged_date=FIXTURE_DATE,
                    seed=bytes(range(32)),
                    templates=cross_eval.load_template_identity(WORKTREE_ROOT),
                    l6_pair_receipt=paired_outputs.formal_pair_evidence(
                        built_receipt
                    ),
                )

    def test_terminal_union_rejects_failure_with_decision_and_sol_failure(self) -> None:
        bad_terminal = {
            "schema_version": cross_eval.OUTPUT_TERMINAL_SCHEMA_VERSION,
            "contract_version": cross_eval.OUTPUT_TERMINAL_CONTRACT_VERSION,
            "status": "timeout",
            "failure_code": "deadline-exceeded",
            "decision": {
                "outcome": "deny",
                "rationale": "This must never stand in for a timeout.",
                "risk_tags": ["uncertainty"],
            },
        }
        with self.assertRaisesRegex(
            cross_eval.CrossEvalError, "output_terminal_fields_invalid"
        ):
            cross_eval.validate_output_terminal(bad_terminal)

        bundle = fixture_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            built_receipt = build_receipt(directory)
            receipt = built_receipt.receipt
            run_dir = directory / "sol-failure-run"
            run_dir.mkdir(mode=0o700)
            rows = paired_outputs.build_frozen_sol_rows(bundle)
            sol = rows[0]
            sol["schema_version"] = cross_eval.TERMINAL_IMPORT_SCHEMA_VERSION
            sol["contract_version"] = cross_eval.TERMINAL_IMPORT_CONTRACT_VERSION
            sol["terminal"] = {
                "schema_version": cross_eval.OUTPUT_TERMINAL_SCHEMA_VERSION,
                "contract_version": cross_eval.OUTPUT_TERMINAL_CONTRACT_VERSION,
                "status": "timeout",
                "failure_code": "deadline-exceeded",
            }
            del sol["decision"]
            local = paired_outputs.run_paired_outputs(
                bundle,
                pair_receipt=built_receipt,
                run_dir=run_dir,
                invoke=lambda _side, _payload, _deployment: {
                    "outcome": "allow",
                    "rationale": "Synthetic fixture decision.",
                    "risk_tags": [],
                },
            )
            with self.assertRaisesRegex(
                cross_eval.CrossEvalError, "sol_target_terminal_invalid"
            ):
                cross_eval.validate_three_side_rows(
                    bundle,
                    [*rows, *local],
                    l6_pair_receipt=paired_outputs.formal_pair_evidence(
                        built_receipt
                    ),
                )

    def test_all_decision_v2_rows_still_build_the_frozen_v1_blind_package(self) -> None:
        bundle = fixture_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            built_receipt = build_receipt(directory)
            run_dir = directory / "all-decision-run"
            run_dir.mkdir(mode=0o700)
            local = paired_outputs.run_paired_outputs(
                bundle,
                pair_receipt=built_receipt,
                run_dir=run_dir,
                invoke=lambda _side, _payload, _deployment: {
                    "outcome": "allow",
                    "rationale": "Synthetic fixture decision.",
                    "risk_tags": [],
                },
            )
            accepted = paired_outputs.assemble_three_side_outputs(
                bundle, local, pair_receipt=built_receipt
            )
            blind = cross_eval.build_blind_batches(
                bundle,
                accepted,
                judge_model="fixture-judge",
                judged_date=FIXTURE_DATE,
                seed=bytes(range(32)),
                templates=cross_eval.load_template_identity(WORKTREE_ROOT),
                l6_pair_receipt=paired_outputs.formal_pair_evidence(built_receipt),
            )
            self.assertEqual(len(blind), 2)
            self.assertTrue(
                all(
                    set(candidate) == {"candidate_id", "decision"}
                    for batch in blind
                    for sample in batch.package["samples"]
                    for candidate in sample["candidates"]
                )
            )


class PairedJournalTests(unittest.TestCase):
    @staticmethod
    def decision(
        _side: str,
        _payload: dict,
        _deployment: paired_outputs.ResolvedDeployment,
    ) -> dict:
        return {
            "outcome": "allow",
            "rationale": "Synthetic durable-journal fixture decision.",
            "risk_tags": [],
        }

    def test_completed_terminals_resume_without_duplicate_invocation(self) -> None:
        bundle = fixture_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            receipt = build_receipt(directory)
            run_dir = directory / "resume-run"
            run_dir.mkdir(mode=0o700)
            calls: list[tuple[str, str]] = []

            def invoke(
                side: str,
                payload: dict,
                deployment: paired_outputs.ResolvedDeployment,
            ) -> dict:
                calls.append((side, cross_eval._canonical_sha256(payload)))
                return self.decision(side, payload, deployment)

            partial = paired_outputs.run_paired_outputs(
                bundle,
                pair_receipt=receipt,
                run_dir=run_dir,
                invoke=invoke,
                max_new_terminals=2,
            )
            self.assertEqual(len(partial), 2)
            self.assertEqual(len(calls), 2)
            completed = paired_outputs.run_paired_outputs(
                bundle,
                pair_receipt=receipt,
                run_dir=run_dir,
                invoke=invoke,
            )
            self.assertEqual(len(completed), 12)
            self.assertEqual(len(calls), 12)
            self.assertEqual(len(set(calls)), 12)
            journal = run_dir / "paired-output-journal.jsonl"
            self.assertEqual(stat_mode(journal), 0o600)
            self.assertEqual(stat_mode(run_dir), 0o700)

    def test_interruption_requires_explicit_infrastructure_resolution_then_resumes(self) -> None:
        bundle = fixture_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            receipt = build_receipt(directory)
            run_dir = directory / "interrupted-run"
            run_dir.mkdir(mode=0o700)
            first_calls: list[tuple[str, str]] = []

            def interrupted(
                side: str,
                payload: dict,
                _deployment: paired_outputs.ResolvedDeployment,
            ) -> dict:
                first_calls.append((side, cross_eval._canonical_sha256(payload)))
                raise RuntimeError("synthetic interruption")

            with self.assertRaisesRegex(RuntimeError, "synthetic interruption"):
                paired_outputs.run_paired_outputs(
                    bundle,
                    pair_receipt=receipt,
                    run_dir=run_dir,
                    invoke=interrupted,
                )
            self.assertEqual(len(first_calls), 1)
            resumed_calls: list[tuple[str, str]] = []
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError,
                "paired_journal_attempt_without_terminal",
            ):
                paired_outputs.run_paired_outputs(
                    bundle,
                    pair_receipt=receipt,
                    run_dir=run_dir,
                    invoke=lambda side, payload, deployment: resumed_calls.append(
                        (side, cross_eval._canonical_sha256(payload))
                    )
                    or self.decision(side, payload, deployment),
                )
            self.assertEqual(resumed_calls, [])

            infrastructure = paired_outputs.resolve_interrupted_attempt(
                bundle,
                pair_receipt=receipt,
                run_dir=run_dir,
                failure_code="worker-process-lost",
            )
            self.assertEqual(
                infrastructure["terminal"],
                {
                    "schema_version": 2,
                    "contract_version": "rondo_l6_output_terminal_v2",
                    "status": "infrastructure_failure",
                    "failure_code": "worker-process-lost",
                },
            )
            self.assertNotIn("decision", infrastructure["terminal"])
            side_schema_path = (
                WORKTREE_ROOT
                / "eval/templates/cross-eval-judge/local-m4-side-output-v2.schema.json"
            )
            side_schema = json.loads(side_schema_path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator(
                side_schema["properties"]["terminal"]
            ).validate(infrastructure["terminal"])
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError,
                "paired_journal_no_interrupted_attempt",
            ):
                paired_outputs.resolve_interrupted_attempt(
                    bundle,
                    pair_receipt=receipt,
                    run_dir=run_dir,
                    failure_code="duplicate-resolution",
                )

            completed = paired_outputs.run_paired_outputs(
                bundle,
                pair_receipt=receipt,
                run_dir=run_dir,
                invoke=lambda side, payload, deployment: resumed_calls.append(
                    (side, cross_eval._canonical_sha256(payload))
                )
                or self.decision(side, payload, deployment),
            )
            self.assertEqual(len(completed), 12)
            self.assertEqual(len(resumed_calls), 11)
            self.assertEqual(len(set([*first_calls, *resumed_calls])), 12)
            keys = [(row["side"], row["sample_id"]) for row in completed]
            self.assertEqual(len(keys), len(set(keys)))
            infrastructure_rows = [
                row
                for row in completed
                if row["terminal"]["status"] == "infrastructure_failure"
            ]
            self.assertEqual(infrastructure_rows, [infrastructure])
            accepted = paired_outputs.assemble_three_side_outputs(
                bundle, completed, pair_receipt=receipt
            )
            with self.assertRaisesRegex(
                cross_eval.CrossEvalError,
                "judge_package_v1_requires_decision_terminals",
            ):
                cross_eval.build_blind_batches(
                    bundle,
                    accepted,
                    judge_model="fixture-judge",
                    judged_date=FIXTURE_DATE,
                    seed=bytes(range(32)),
                    templates=cross_eval.load_template_identity(WORKTREE_ROOT),
                    l6_pair_receipt=paired_outputs.formal_pair_evidence(receipt),
                )

    def test_interruption_resolution_rejects_missing_non_tail_and_pair_drift(self) -> None:
        bundle = fixture_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            receipt = build_receipt(directory)
            clean_run = directory / "clean-run"
            clean_run.mkdir(mode=0o700)
            paired_outputs.run_paired_outputs(
                bundle,
                pair_receipt=receipt,
                run_dir=clean_run,
                invoke=self.decision,
                max_new_terminals=0,
            )
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError,
                "paired_journal_no_interrupted_attempt",
            ):
                paired_outputs.resolve_interrupted_attempt(
                    bundle,
                    pair_receipt=receipt,
                    run_dir=clean_run,
                    failure_code="nothing-to-resolve",
                )

            interrupted_run = directory / "non-tail-run"
            interrupted_run.mkdir(mode=0o700)
            with self.assertRaises(RuntimeError):
                paired_outputs.run_paired_outputs(
                    bundle,
                    pair_receipt=receipt,
                    run_dir=interrupted_run,
                    invoke=lambda _side, _payload, _deployment: (_ for _ in ()).throw(
                        RuntimeError("interrupt")
                    ),
                )
            other_dir = directory / "other-pair"
            other_dir.mkdir()
            other_receipt = build_receipt(
                other_dir, pair_id="l6-other-resolution-fixture-v1"
            )
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError, "paired_journal_binding_mismatch"
            ):
                paired_outputs.resolve_interrupted_attempt(
                    bundle,
                    pair_receipt=other_receipt,
                    run_dir=interrupted_run,
                    failure_code="wrong-pair",
                )

            journal = interrupted_run / "paired-output-journal.jsonl"
            paired_outputs._append_journal_record(
                journal,
                {
                    "schema_version": paired_outputs.JOURNAL_SCHEMA_VERSION,
                    "contract_version": paired_outputs.JOURNAL_CONTRACT_VERSION,
                    "record_type": "attempt",
                    "sequence": 1,
                    "side": "local-static",
                    "sample_id": sorted(bundle.source_rows)[1],
                },
            )
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError, "paired_journal_terminal_invalid"
            ):
                paired_outputs.resolve_interrupted_attempt(
                    bundle,
                    pair_receipt=receipt,
                    run_dir=interrupted_run,
                    failure_code="non-tail-attempt",
                )

    def test_journal_rejects_pair_and_cohort_binding_drift(self) -> None:
        bundle = fixture_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            receipt = build_receipt(directory)
            pair_run = directory / "pair-binding-run"
            pair_run.mkdir(mode=0o700)
            paired_outputs.run_paired_outputs(
                bundle,
                pair_receipt=receipt,
                run_dir=pair_run,
                invoke=self.decision,
                max_new_terminals=0,
            )
            other_dir = directory / "other-artifacts"
            other_dir.mkdir()
            other_receipt = build_receipt(
                other_dir, pair_id="l6-other-paired-output-fixture-v1"
            )
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError, "paired_journal_binding_mismatch"
            ):
                paired_outputs.run_paired_outputs(
                    bundle,
                    pair_receipt=other_receipt,
                    run_dir=pair_run,
                    invoke=self.decision,
                    max_new_terminals=0,
                )

            cohort_run = directory / "cohort-binding-run"
            cohort_run.mkdir(mode=0o700)
            paired_outputs.run_paired_outputs(
                bundle,
                pair_receipt=receipt,
                run_dir=cohort_run,
                invoke=self.decision,
                max_new_terminals=0,
            )
            drifted_manifest = copy.deepcopy(bundle.manifest)
            drifted_manifest["cohort_id"] = "l6-pair-fixture-body-v2"
            drifted = cross_eval.CohortBundle(
                bundle.partition,
                drifted_manifest,
                digest_bytes(cross_eval._json_file_bytes(drifted_manifest)),
                bundle.source_rows,
            )
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError, "paired_journal_binding_mismatch"
            ):
                paired_outputs.run_paired_outputs(
                    drifted,
                    pair_receipt=receipt,
                    run_dir=cohort_run,
                    invoke=self.decision,
                    max_new_terminals=0,
                )


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
