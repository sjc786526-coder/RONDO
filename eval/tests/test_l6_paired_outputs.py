from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path

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


def shared_contract() -> dict:
    return {
        "runtime_identity_sha256": digest("pair-runtime"),
        "chat_template_sha256": digest("pair-chat-template"),
        "request_contract_sha256": digest("pair-request-contract"),
        "sampling_contract": {
            "context_size": 12288,
            "max_output_tokens": 512,
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": 42,
        },
        "output_contract_sha256": cross_eval._canonical_sha256(
            cross_eval.STATIC_DECISION_SCHEMA
        ),
    }


def write_canonical(path: Path, value: object) -> None:
    path.write_bytes(cross_eval._json_file_bytes(value))


def build_receipt(
    directory: Path, *, pair_id: str = "l6-paired-output-fixture-v1"
) -> paired_outputs.BuiltPairReceipt:
    base = directory / "base.lock.json"
    static = directory / "base.gguf"
    adapter = directory / "adapter.safetensors"
    finetuned = directory / "adapter.manifest.json"
    training = directory / "training-receipt.json"
    write_canonical(base, {"revision": digest("base-revision")})
    static.write_bytes(b"fixture-unfinetuned-artifact")
    adapter.write_bytes(b"fixture-finetuned-adapter")
    write_canonical(
        finetuned,
        paired_outputs.build_canonical_artifact_manifest(
            artifact_id="fixture-finetuned-adapter",
            manifest_path=finetuned,
            components={"adapter": adapter},
        ),
    )
    write_canonical(training, {"status": "completed", "steps": 2})
    return paired_outputs.build_pair_receipt(
        pair_id=pair_id,
        base_model=paired_outputs.IdentitySource("frozen_lock", base, "base-lock"),
        local_static=paired_outputs.IdentitySource(
            "regular_file", static, "unfinetuned-artifact"
        ),
        local_ft_static=paired_outputs.IdentitySource(
            "canonical_manifest", finetuned, "finetuned-manifest"
        ),
        training_receipt=paired_outputs.IdentitySource(
            "frozen_lock", training, "training-receipt"
        ),
        shared_contract=shared_contract(),
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
                digest_bytes((directory / "base.gguf").read_bytes()),
            )
            self.assertEqual(
                built.receipt["artifacts"]["local-ft-static"]["model_artifact_sha256"],
                digest_bytes((directory / "adapter.manifest.json").read_bytes()),
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
                sources["local-ft-static"]["components"],
                [
                    {
                        "logical_name": "adapter",
                        "relative_path": "adapter.safetensors",
                        "size_bytes": (directory / "adapter.safetensors").stat().st_size,
                        "sha256": digest_bytes(
                            (directory / "adapter.safetensors").read_bytes()
                        ),
                    }
                ],
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
                    invoke=lambda _side, _payload: {},
                )
            (directory / "adapter.safetensors").write_bytes(b"changed-adapter")
            called = []
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError, "artifact_manifest_component_drift"
            ):
                paired_outputs.run_paired_outputs(
                    fixture_bundle(),
                    pair_receipt=built,
                    run_dir=run_dir,
                    invoke=lambda side, _payload: called.append(side) or {},
                )
            self.assertEqual(called, [])

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

            def invoke(side: str, _approval_input: dict) -> dict:
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
            self.assertEqual(
                calls,
                ["local-static"] * 6 + ["local-ft-static"] * 6,
            )
            accepted = paired_outputs.assemble_three_side_outputs(
                bundle, local_rows, pair_receipt=receipt
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
                l6_pair_receipt=receipt,
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
                    l6_pair_receipt=receipt,
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
                invoke=lambda _side, _payload: {
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
                    l6_pair_receipt=receipt,
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
                invoke=lambda _side, _payload: {
                    "outcome": "allow",
                    "rationale": "Synthetic fixture decision.",
                    "risk_tags": [],
                },
            )
            accepted = paired_outputs.assemble_three_side_outputs(
                bundle, local, pair_receipt=built_receipt.receipt
            )
            blind = cross_eval.build_blind_batches(
                bundle,
                accepted,
                judge_model="fixture-judge",
                judged_date=FIXTURE_DATE,
                seed=bytes(range(32)),
                templates=cross_eval.load_template_identity(WORKTREE_ROOT),
                l6_pair_receipt=built_receipt.receipt,
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
    def decision(_side: str, _payload: dict) -> dict:
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

            def invoke(side: str, payload: dict) -> dict:
                calls.append((side, cross_eval._canonical_sha256(payload)))
                return self.decision(side, payload)

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

    def test_unexpected_interruption_leaves_attempt_and_resume_refuses_reinvoke(self) -> None:
        bundle = fixture_bundle()
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            receipt = build_receipt(directory)
            run_dir = directory / "interrupted-run"
            run_dir.mkdir(mode=0o700)
            first_calls = []

            def interrupted(side: str, _payload: dict) -> dict:
                first_calls.append(side)
                raise RuntimeError("synthetic interruption")

            with self.assertRaisesRegex(RuntimeError, "synthetic interruption"):
                paired_outputs.run_paired_outputs(
                    bundle,
                    pair_receipt=receipt,
                    run_dir=run_dir,
                    invoke=interrupted,
                )
            self.assertEqual(first_calls, ["local-static"])
            resumed_calls = []
            with self.assertRaisesRegex(
                paired_outputs.PairedOutputError,
                "paired_journal_attempt_without_terminal",
            ):
                paired_outputs.run_paired_outputs(
                    bundle,
                    pair_receipt=receipt,
                    run_dir=run_dir,
                    invoke=lambda side, payload: resumed_calls.append(side)
                    or self.decision(side, payload),
                )
            self.assertEqual(resumed_calls, [])

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
