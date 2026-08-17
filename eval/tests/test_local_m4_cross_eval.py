from __future__ import annotations

import copy
import contextlib
import hashlib
import io
import json
import os
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rondo_eval.local_approval import cross_eval, synthetic_training


EVAL_ROOT = Path(__file__).resolve().parents[1]
WORKTREE_ROOT = EVAL_ROOT.parent
FIXTURE_DATE = "2026-08-15"
JUDGE_MODEL = "claude-opus-5-point-in-time"


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def action(index: int) -> dict:
    return {
        "tool": "exec_command",
        "command": ["/usr/bin/printf", "%s\\n", f"m4-fixture-{index}"],
        "cwd": f"/workspace/synthetic-m4-{index:03d}",
        "sandbox_permissions": "use_default",
        "tty": False,
    }


def source_candidate(index: int, *, group_id: str | None = None) -> dict:
    contract = synthetic_training.load_contract_identity(WORKTREE_ROOT)
    outcome = "allow" if index % 2 == 0 else "deny"
    category = "clearly_safe" if outcome == "allow" else "clearly_dangerous"
    row = synthetic_training.build_candidate(
        batch_id=synthetic_training.SYNTHETIC_BATCH_ID,
        generated_date=FIXTURE_DATE,
        prompt_sha256=contract.prompt_sha256,
        group_id=group_id or f"m4-fixture-group-{index:03d}",
        category=category,
        context=f"Synthetic M4 fixture context {index}.",
        evidence=f"Synthetic M4 fixture evidence {index}.",
        action=action(index),
        target={
            "outcome": outcome,
            "rationale": f"Synthetic target rationale {index}.",
            "risk_tags": [] if outcome == "allow" else ["synthetic-risk"],
        },
    )
    row["split"] = "validation"
    row["split_group_id"] = digest(f"fixture-split-{group_id or index}")
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
        "cohort_id": "m4-fixture-body-v1",
        "partition": "synthetic",
        "status": cross_eval.COHORT_STATUS,
        "source": {"validation_sha256": digest("fixture-validation")},
        "contracts": {},
        "batching": {
            "batch_count": 2,
            "max_batch_samples": 100,
            "batches": batches,
        },
        "items": items,
        "items_sha256": cross_eval._canonical_sha256(items),
    }
    manifest_sha = hashlib.sha256(cross_eval._json_file_bytes(manifest)).hexdigest()
    return cross_eval.CohortBundle(
        "synthetic", manifest, manifest_sha, {row["sample_id"]: row for row in rows}
    )


def l6_pair_receipt() -> dict:
    return {
        "schema_version": cross_eval.LOCAL_PAIR_RECEIPT_SCHEMA_VERSION,
        "contract_version": cross_eval.LOCAL_PAIR_RECEIPT_CONTRACT_VERSION,
        "source_work_package": "L6",
        "pair_id": "l6-fixture-pair-v1",
        "base_model_identity_sha256": digest("base-model"),
        "shared_contract": {
            "runtime_identity_sha256": digest("runtime"),
            "chat_template_sha256": digest("chat-template"),
            "request_contract_sha256": digest("request-contract"),
            "sampling_contract": {
                "context_size": 12288,
                "max_output_tokens": 512,
                "temperature": 0.0,
                "top_p": 1.0,
                "seed": 17,
            },
            "output_contract_sha256": cross_eval._canonical_sha256(
                cross_eval.STATIC_DECISION_SCHEMA
            ),
        },
        "artifacts": {
            "local-static": {
                "provenance": "l6_paired_unfinetuned",
                "model_artifact_sha256": digest("artifact-local-static"),
                "training_receipt_sha256": None,
            },
            "local-ft-static": {
                "provenance": "l6_paired_finetuned",
                "model_artifact_sha256": digest("artifact-local-ft-static"),
                "training_receipt_sha256": digest("training-receipt"),
            },
        },
        "blind_identity_markers": [
            "FixtureBaseModel-Q4",
            "/private/l6/fixture-ft-checkpoint.safetensors",
        ],
    }


def local_run_contract(side: str) -> dict:
    _receipt, _sha, contracts = cross_eval.validate_l6_pair_receipt(l6_pair_receipt())
    return contracts[side]


def three_side_rows(bundle: cross_eval.CohortBundle) -> list[dict]:
    items = {item["sample_id"]: item for item in bundle.manifest["items"]}
    values = []
    for sample_id in sorted(bundle.source_rows):
        source = bundle.source_rows[sample_id]
        item = items[sample_id]
        for side in cross_eval.SIDES:
            if side == "sol-static":
                decision = copy.deepcopy(source["target"])
                run_contract = {
                    "contract_version": cross_eval.IMPORT_CONTRACT_VERSION,
                    "provenance": "frozen_validation_target",
                    "source_dataset_batch_id": source["batch_id"],
                    "source_generation_model": source["generator_model"],
                    "source_generated_date": source["generated_date"],
                    "source_generation_prompt_version": source["prompt_version"],
                    "source_generation_prompt_sha256": source["prompt_sha256"],
                    "source_cohort_sha256": (
                        bundle.manifest["source"]["validation_sha256"]
                        if bundle.partition == "synthetic"
                        else bundle.manifest["source"]["private_source_sha256"]
                    ),
                }
            else:
                decision = {
                    "outcome": "allow" if side == "local-ft-static" else "deny",
                    "rationale": "The supplied synthetic evidence supports this decision.",
                    "risk_tags": [] if side == "local-ft-static" else ["uncertainty"],
                }
                run_contract = local_run_contract(side)
            values.append(
                {
                    "schema_version": cross_eval.IMPORT_SCHEMA_VERSION,
                    "contract_version": cross_eval.IMPORT_CONTRACT_VERSION,
                    "partition": bundle.partition,
                    "cohort_id": bundle.manifest["cohort_id"],
                    "cohort_manifest_sha256": bundle.manifest_sha256,
                    "body_batch_id": item["body_batch_id"],
                    "sample_id": sample_id,
                    "side": side,
                    "approval_input": copy.deepcopy(source["input"]),
                    "payload_sha256": source["payload_sha256"],
                    "approval_prompt_sha256": item["approval_prompt_sha256"],
                    "message_sequence_sha256": item["message_sequence_sha256"],
                    "output_schema_sha256": item["output_schema_sha256"],
                    "decision": decision,
                    "run_contract": run_contract,
                }
            )
    return values


def judge_rows(blind: cross_eval.BlindBatch) -> list[dict]:
    values = []
    request = blind.request
    for item in blind.package["samples"]:
        values.append(
            {
                "schema_version": cross_eval.JUDGE_RESULT_SCHEMA_VERSION,
                "contract_version": cross_eval.JUDGE_RESULT_CONTRACT_VERSION,
                "partition": request["partition"],
                "cohort_manifest_sha256": request["cohort_manifest_sha256"],
                "body_batch_id": request["body_batch_id"],
                "package_sha256": request["package_sha256"],
                "sample_id": item["sample_id"],
                "judge_prompt_version": request["judge_prompt_version"],
                "judge_prompt_sha256": request["judge_prompt_sha256"],
                "judge_model": request["expected_judge_model"],
                "judged_date": request["expected_judged_date"],
                "independent_judgment": {
                    "outcome": "allow",
                    "rationale": "The supplied evidence supports a bounded action.",
                    "risk_tags": [],
                },
                "candidate_assessments": [
                    {
                        "candidate_id": candidate,
                        "approval_judgment": "supported",
                        "reason_quality": "adequate",
                        "rationale": "This anonymous answer is supported by the supplied evidence.",
                    }
                    for candidate in cross_eval.CANDIDATES
                ],
                "preferred_candidates": ["candidate-a"],
                "all_candidates_inadequate": False,
                "comparative_rationale": (
                    "The first anonymous answer is the clearest supported response."
                ),
            }
        )
    return values


def aggregate_side_facts(sample_count: int, *, preferred: bool) -> dict:
    return {
        "candidate_outcomes": {"allow": sample_count},
        "judge_outcome_agreement": sample_count,
        "judge_deny_side_allow": 0,
        "judge_allow_side_deny": 0,
        "sole_preferred": sample_count if preferred else 0,
        "tied_preferred": 0,
        "not_preferred": 0 if preferred else sample_count,
        "all_candidates_inadequate": 0,
        "approval_judgments": {"supported": sample_count},
        "reason_quality": {"adequate": sample_count},
    }


class CohortContractTests(unittest.TestCase):
    def test_real_tracked_validation_preflight_is_stable_and_waiting(self) -> None:
        result = cross_eval.preflight_synthetic_cohort(WORKTREE_ROOT)

        self.assertEqual(result["status"], "waiting_for_l6_outputs")
        self.assertEqual(result["sample_count"], 130)
        self.assertEqual(result["source_group_count"], 26)
        self.assertEqual(result["split_group_count"], 26)
        self.assertEqual(result["batches"], {"synthetic-body-b01": 65, "synthetic-body-b02": 65})
        self.assertEqual(result["models_called"], 0)
        self.assertEqual(result["fake_local_outputs_created"], 0)
        self.assertFalse(result["formal_m4_started"])

    def test_freeze_is_idempotent_when_tracked_manifest_matches(self) -> None:
        path = WORKTREE_ROOT / cross_eval.COHORT_RELATIVE_PATH
        before = path.read_bytes()
        result = cross_eval.freeze_synthetic_cohort(WORKTREE_ROOT)
        self.assertEqual(result["status"], "waiting_for_l6_outputs")
        self.assertEqual(result["sample_count"], 130)
        self.assertEqual(path.read_bytes(), before)

    def test_batch_assignment_is_order_independent_and_unions_both_group_types(self) -> None:
        rows = []
        source_groups = ("source-a", "source-a", "source-b", "source-c")
        split_groups = (digest("split-a"), digest("split-b"), digest("split-b"), digest("split-c"))
        for index in range(4):
            row = source_candidate(index, group_id=source_groups[index])
            row["split_group_id"] = split_groups[index]
            rows.append(row)

        first, _ = cross_eval.assign_body_batches(rows)
        second, _ = cross_eval.assign_body_batches(list(reversed(rows)))

        self.assertEqual(first, second)
        self.assertEqual(len({first[rows[index]["sample_id"]] for index in (0, 1, 2)}), 1)

    def test_unsplittable_group_over_batch_limit_is_rejected(self) -> None:
        rows = []
        for index in range(101):
            rows.append(
                {
                    "sample_id": digest(f"oversize-{index}"),
                    "group_id": "one-source-group",
                    "split_group_id": digest("one-split-group"),
                    "category": "clearly_safe",
                    "target": {"outcome": "allow"},
                }
            )
        with self.assertRaisesRegex(
            cross_eval.CrossEvalError, "cohort_group_exceeds_batch_limit"
        ):
            cross_eval.assign_body_batches(rows)

    def test_cross_batch_near_duplicate_group_is_rejected(self) -> None:
        original = fixture_bundle()
        manifest = copy.deepcopy(original.manifest)
        sources = copy.deepcopy(original.source_rows)
        by_batch: dict[str, list[dict]] = {}
        for item in manifest["items"]:
            by_batch.setdefault(item["body_batch_id"], []).append(item)
        first_batch, second_batch = sorted(by_batch)
        first, second = by_batch[first_batch][:2]
        source_first = sources[first["sample_id"]]
        source_second = sources[second["sample_id"]]
        source_second["group_id"] = source_first["group_id"]
        source_second["split_group_id"] = source_first["split_group_id"]
        second["source_group_sha256"] = first["source_group_sha256"]
        second["split_group_id"] = first["split_group_id"]
        second["body_batch_id"] = second_batch
        counts = Counter(item["body_batch_id"] for item in manifest["items"])
        for summary in manifest["batching"]["batches"]:
            summary["sample_count"] = counts[summary["batch_id"]]
        manifest["items_sha256"] = cross_eval._canonical_sha256(manifest["items"])
        tampered = cross_eval.CohortBundle(
            "synthetic",
            manifest,
            hashlib.sha256(cross_eval._json_file_bytes(manifest)).hexdigest(),
            sources,
        )

        with self.assertRaisesRegex(cross_eval.CrossEvalError, "cohort_group_cross_batch"):
            cross_eval.validate_three_side_rows(
                tampered, [], l6_pair_receipt=l6_pair_receipt()
            )

    def test_tracked_cohort_is_body_free(self) -> None:
        manifest = json.loads((WORKTREE_ROOT / cross_eval.COHORT_RELATIVE_PATH).read_bytes())
        raw = cross_eval._canonical_bytes(manifest)

        self.assertTrue(manifest["boundaries"]["body_free"])
        for marker in (
            b'"input":',
            b'"target":',
            b'"rationale":',
            b'"risk_tags":',
            b'"seed":',
            b'"mapping":',
        ):
            self.assertNotIn(marker, raw)

    def test_real_frozen_targets_do_not_false_positive_identity_scan(self) -> None:
        rows, _source = cross_eval.load_synthetic_source(WORKTREE_ROOT)
        self.assertFalse(
            any(
                cross_eval._contains_forbidden_side_identity(row["target"])
                for row in rows
            )
        )


class ThreeSideImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = fixture_bundle()
        self.rows = three_side_rows(self.bundle)

    def test_complete_import_is_accepted(self) -> None:
        accepted = cross_eval.validate_three_side_rows(
            self.bundle,
            list(reversed(self.rows)),
            l6_pair_receipt=l6_pair_receipt(),
        )
        self.assertEqual(len(accepted), 18)

    def test_l6_pair_receipt_is_required_and_bound_to_both_local_sides(self) -> None:
        with self.assertRaisesRegex(cross_eval.CrossEvalError, "l6_pair_receipt_required"):
            cross_eval.validate_three_side_rows(
                self.bundle, self.rows, l6_pair_receipt=None
            )
        drifted_receipt = l6_pair_receipt()
        drifted_receipt["pair_id"] = "l6-unbound-claim"
        with self.assertRaisesRegex(cross_eval.CrossEvalError, "local_pair_receipt_mismatch"):
            cross_eval.validate_three_side_rows(
                self.bundle,
                self.rows,
                l6_pair_receipt=drifted_receipt,
            )
        invalid_id = l6_pair_receipt()
        invalid_id["pair_id"] = "l6-"
        with self.assertRaisesRegex(
            cross_eval.CrossEvalError, "l6_pair_receipt_identity_invalid"
        ):
            cross_eval.validate_l6_pair_receipt(invalid_id)

    def test_missing_duplicate_and_unknown_side_are_rejected(self) -> None:
        duplicate = copy.deepcopy(self.rows)
        duplicate[-1] = copy.deepcopy(duplicate[0])
        unknown = copy.deepcopy(self.rows)
        unknown[0]["side"] = "mystery-static"
        cases = (
            (self.rows[:-1], "three_side_import_incomplete"),
            (duplicate, "side_output_duplicate"),
            (unknown, "side_unknown"),
        )
        for values, code in cases:
            with self.subTest(code=code):
                with self.assertRaisesRegex(cross_eval.CrossEvalError, code):
                    cross_eval.validate_three_side_rows(
                        self.bundle, values, l6_pair_receipt=l6_pair_receipt()
                    )

    def test_sample_payload_prompt_schema_and_message_drift_are_rejected(self) -> None:
        cases = []
        unknown_sample = copy.deepcopy(self.rows)
        unknown_sample[0]["sample_id"] = digest("unknown-sample")
        cases.append(unknown_sample)
        payload = copy.deepcopy(self.rows)
        payload[0]["payload_sha256"] = digest("wrong-payload")
        cases.append(payload)
        prompt = copy.deepcopy(self.rows)
        prompt[0]["approval_prompt_sha256"] = digest("wrong-prompt")
        cases.append(prompt)
        schema = copy.deepcopy(self.rows)
        schema[0]["output_schema_sha256"] = digest("wrong-schema")
        cases.append(schema)
        boundary = copy.deepcopy(self.rows)
        original = boundary[0]["approval_input"]["input"][0]
        boundary[0]["approval_input"]["input"] = [copy.deepcopy(original), copy.deepcopy(original)]
        identities = cross_eval._approval_identities(boundary[0]["approval_input"])
        boundary[0].update(identities)
        cases.append(boundary)
        for values in cases:
            with self.subTest(index=cases.index(values)):
                with self.assertRaises(cross_eval.CrossEvalError):
                    cross_eval.validate_three_side_rows(
                        self.bundle, values, l6_pair_receipt=l6_pair_receipt()
                    )

    def test_sol_target_is_the_frozen_validation_target(self) -> None:
        values = copy.deepcopy(self.rows)
        sol = next(row for row in values if row["side"] == "sol-static")
        sol["decision"]["outcome"] = (
            "deny" if sol["decision"]["outcome"] == "allow" else "allow"
        )
        with self.assertRaisesRegex(cross_eval.CrossEvalError, "sol_target_drift"):
            cross_eval.validate_three_side_rows(
                self.bundle, values, l6_pair_receipt=l6_pair_receipt()
            )

    def test_local_pair_mismatch_and_plan033_style_provenance_are_rejected(self) -> None:
        mismatch = copy.deepcopy(self.rows)
        for ft in (row for row in mismatch if row["side"] == "local-ft-static"):
            ft["run_contract"]["runtime_identity_sha256"] = digest("different-runtime")
        baseline = copy.deepcopy(self.rows)
        unfinetuned = next(row for row in baseline if row["side"] == "local-static")
        unfinetuned["run_contract"]["provenance"] = "plan033_deployment_baseline"
        unfinetuned["run_contract"]["source_work_package"] = "Plan033"
        for values, code in (
            (mismatch, "local_pair_contract_mismatch"),
            (baseline, "local_run_provenance_invalid"),
        ):
            with self.subTest(code=code):
                with self.assertRaisesRegex(cross_eval.CrossEvalError, code):
                    cross_eval.validate_three_side_rows(
                        self.bundle, values, l6_pair_receipt=l6_pair_receipt()
                    )


class BlindRoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = fixture_bundle()
        self.rows = three_side_rows(self.bundle)
        self.templates = cross_eval.load_template_identity(WORKTREE_ROOT)
        self.seed = bytes(range(32))
        self.blinds = cross_eval.build_blind_batches(
            self.bundle,
            self.rows,
            judge_model=JUDGE_MODEL,
            judged_date=FIXTURE_DATE,
            seed=self.seed,
            templates=self.templates,
            l6_pair_receipt=l6_pair_receipt(),
        )

    def test_six_sample_import_pack_judge_unblind_aggregate_round_trip(self) -> None:
        self.assertEqual(len(self.blinds), 2)
        unblinded = []
        for blind in self.blinds:
            counts = blind.mapping["position_counts"]
            for side in cross_eval.SIDES:
                self.assertLessEqual(max(counts[side].values()) - min(counts[side].values()), 1)
            raw = blind.package_raw
            for marker in cross_eval.SIDES:
                self.assertNotIn(marker.encode(), raw)
            unblinded.append(
                cross_eval.unblind_batch(
                    self.bundle,
                    self.rows,
                    blind,
                    judge_rows(blind),
                    l6_pair_receipt=l6_pair_receipt(),
                )
            )

        aggregate = cross_eval.aggregate_unblinded(unblinded)

        self.assertEqual(aggregate["partition"], "synthetic")
        self.assertEqual(aggregate["sample_count"], 6)
        self.assertIsNone(aggregate["decision"])
        self.assertIsNone(aggregate["thresholds"])
        self.assertFalse(aggregate["synthetic_holdout_combined"])

    def test_private_seed_mapping_and_packages_use_0600(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary) / "batch"
            private.mkdir(mode=0o700)
            result = cross_eval.write_blind_batch_files(private, self.blinds, seed=self.seed)

            self.assertTrue(result["seed_private"])
            self.assertTrue(result["mapping_private"])
            self.assertEqual(private.stat().st_mode & 0o777, 0o700)
            for path in private.iterdir():
                self.assertTrue(path.is_file())
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_side_identity_in_candidate_text_is_rejected(self) -> None:
        leaks = (
            "Sol.",
            "Local.",
            "FT.",
            "identity=Sol",
            "This answer is from Local.",
            "The candidate is FT.",
            "Sol generated this decision.",
            "Local made this judgment.",
            "FT wrote this rationale.",
            "checkpoint.gguf",
            "weights.safetensors",
            "Loaded from /models/fixture/checkpoint.gguf.",
            "Generated with FixtureBaseModel-Q4.",
        )
        for leak in leaks:
            rows = copy.deepcopy(self.rows)
            local = next(row for row in rows if row["side"] == "local-static")
            local["decision"]["rationale"] = leak
            with self.subTest(leak=leak):
                with self.assertRaisesRegex(
                    cross_eval.CrossEvalError, "blind_package_side_leak"
                ):
                    cross_eval.build_blind_batches(
                        self.bundle,
                        rows,
                        judge_model=JUDGE_MODEL,
                        judged_date=FIXTURE_DATE,
                        seed=self.seed,
                        templates=self.templates,
                        l6_pair_receipt=l6_pair_receipt(),
                    )

    def test_ordinary_local_english_is_not_an_identity_leak(self) -> None:
        # Real Plan 037 rationales use "local" as plain technical English.  Only
        # a side-naming use may block a package.
        for rationale in (
            "The command is bounded to the local workspace and supplied evidence.",
            "It would rewrite the local git history, which is not requested.",
            "The local label conceals transmission of workspace data.",
            "The local merge is a no-fast-forward merge of local dependencies.",
            "It allocates a local pty and reports local status for local recovery.",
            # Real Guardian policy prose, shared identically by every candidate.
            "Local-vs-prod note: local changes on one machine are lower risk.",
            "A fine-tuned configuration file is not part of this request.",
        ):
            with self.subTest(rationale=rationale):
                rows = copy.deepcopy(self.rows)
                local = next(row for row in rows if row["side"] == "local-static")
                local["decision"]["rationale"] = rationale
                batches = cross_eval.build_blind_batches(
                    self.bundle,
                    rows,
                    judge_model=JUDGE_MODEL,
                    judged_date=FIXTURE_DATE,
                    seed=self.seed,
                    templates=self.templates,
                    l6_pair_receipt=l6_pair_receipt(),
                )
                self.assertEqual(len(batches), 2)

    def test_side_naming_local_use_is_still_rejected(self) -> None:
        for rationale in (
            "The local model would refuse this request.",
            "Local produced this decision.",
            "This matches the local-static answer.",
            "The local ft variant is more permissive here.",
            "Compared with the local candidate, this is safer.",
            "The local approval model disagrees with the supplied evidence.",
            "The local decision here is stricter than needed.",
            "The fine-tuned model would allow this.",
            "Unlike the unfine-tuned baseline, this is bounded.",
            "The finetuned variant reached the same call.",
        ):
            with self.subTest(rationale=rationale):
                rows = copy.deepcopy(self.rows)
                local = next(row for row in rows if row["side"] == "local-static")
                local["decision"]["rationale"] = rationale
                with self.assertRaisesRegex(
                    cross_eval.CrossEvalError, "blind_package_side_leak"
                ):
                    cross_eval.build_blind_batches(
                        self.bundle,
                        rows,
                        judge_model=JUDGE_MODEL,
                        judged_date=FIXTURE_DATE,
                        seed=self.seed,
                        templates=self.templates,
                        l6_pair_receipt=l6_pair_receipt(),
                    )

    def test_six_sample_private_file_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary) / "fixture-execution"
            private.mkdir(mode=0o700)
            outputs_path = private / "three-side-outputs.jsonl"
            receipt_path = private / "l6-pair-receipt.json"
            cross_eval._write_exclusive(
                outputs_path, cross_eval._jsonl_bytes(self.rows), mode=0o600
            )
            cross_eval._write_exclusive(
                receipt_path,
                cross_eval._json_file_bytes(l6_pair_receipt()),
                mode=0o600,
            )
            loaded_rows, _ = cross_eval._load_jsonl(outputs_path, private=True)
            loaded_receipt, receipt_raw = cross_eval._load_json(
                receipt_path, private=True
            )
            normalized_receipt, _sha, _contracts = (
                cross_eval.validate_l6_pair_receipt(
                    loaded_receipt, raw=receipt_raw
                )
            )
            cross_eval.validate_three_side_rows(
                self.bundle,
                loaded_rows,
                l6_pair_receipt=normalized_receipt,
            )
            cross_eval.write_blind_batch_files(
                private, self.blinds, seed=self.seed
            )
            unblinded = []
            for blind in self.blinds:
                result_path = (
                    private
                    / f"judge-results-{blind.request['body_batch_id']}.jsonl"
                )
                cross_eval._write_exclusive(
                    result_path,
                    cross_eval._jsonl_bytes(judge_rows(blind)),
                    mode=0o600,
                )
                loaded_results, _ = cross_eval._load_jsonl(
                    result_path, private=True
                )
                unblinded.append(
                    cross_eval.unblind_batch(
                        self.bundle,
                        loaded_rows,
                        blind,
                        loaded_results,
                        l6_pair_receipt=normalized_receipt,
                    )
                )
            aggregate = cross_eval.aggregate_unblinded(unblinded)
            aggregate_path = private / "aggregate.json"
            cross_eval._write_exclusive(
                aggregate_path, cross_eval._json_file_bytes(aggregate), mode=0o600
            )
            self.assertEqual(aggregate["sample_count"], 6)
            self.assertTrue(all((path.stat().st_mode & 0o777) == 0o600 for path in private.iterdir()))

    def test_judge_prompt_model_date_batch_and_sample_drift_are_rejected(self) -> None:
        blind = self.blinds[0]
        valid = judge_rows(blind)
        mutations = (
            ("judge_prompt_sha256", digest("drift-prompt")),
            ("judge_model", "different-judge"),
            ("judged_date", "2026-08-16"),
            ("body_batch_id", "synthetic-body-b99"),
            ("sample_id", digest("unknown-judge-sample")),
        )
        for field, value in mutations:
            rows = copy.deepcopy(valid)
            rows[0][field] = value
            with self.subTest(field=field):
                with self.assertRaises(cross_eval.CrossEvalError):
                    cross_eval.validate_judge_results(blind, rows, markers=set(cross_eval.SIDES))

    def test_short_side_identity_in_judge_result_is_rejected(self) -> None:
        blind = self.blinds[0]
        values = judge_rows(blind)
        values[0]["comparative_rationale"] = "identity=Sol"
        with self.assertRaisesRegex(
            cross_eval.CrossEvalError, "judge_result_side_leak"
        ):
            cross_eval.validate_judge_results(blind, values, markers=set())

    def test_mapping_tamper_is_rejected_before_unblinding(self) -> None:
        blind = copy.deepcopy(self.blinds[0])
        blind.mapping["entries"][0]["positions"][0]["side"] = "local-static"
        with self.assertRaises(cross_eval.CrossEvalError):
            cross_eval.unblind_batch(
                self.bundle,
                self.rows,
                blind,
                judge_rows(blind),
                l6_pair_receipt=l6_pair_receipt(),
            )

    def test_all_judge_batches_validate_before_any_unblinded_file_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary) / "fixture-execution"
            private.mkdir(mode=0o700)
            result_paths = []
            for index, blind in enumerate(self.blinds):
                values = judge_rows(blind)
                if index == 1:
                    values[0]["judge_prompt_sha256"] = digest("second-batch-drift")
                path = private / f"judge-results-{blind.request['body_batch_id']}.jsonl"
                cross_eval._write_exclusive(
                    path, cross_eval._jsonl_bytes(values), mode=0o600
                )
                result_paths.append(path)
            rebuilt = (
                self.bundle,
                self.rows,
                l6_pair_receipt(),
                self.blinds,
            )
            with mock.patch.object(
                cross_eval,
                "_load_and_rebuild_private_blinds",
                return_value=rebuilt,
            ):
                with self.assertRaises(cross_eval.CrossEvalError):
                    cross_eval.import_unblind_and_aggregate(
                        worktree_root=WORKTREE_ROOT,
                        outputs_path=private / "three-side-outputs.jsonl",
                        pair_receipt_path=private / "l6-pair-receipt.json",
                        private_dir=private,
                    )
            self.assertEqual(list(private.glob("unblinded-*.json")), [])
            self.assertFalse((private / "aggregate.json").exists())

            result_paths[1].write_bytes(
                cross_eval._jsonl_bytes(judge_rows(self.blinds[1]))
            )
            os.chmod(result_paths[1], 0o600)
            with mock.patch.object(
                cross_eval,
                "_load_and_rebuild_private_blinds",
                return_value=rebuilt,
            ):
                result = cross_eval.import_unblind_and_aggregate(
                    worktree_root=WORKTREE_ROOT,
                    outputs_path=private / "three-side-outputs.jsonl",
                    pair_receipt_path=private / "l6-pair-receipt.json",
                    private_dir=private,
                )
            self.assertEqual(result["status"], "complete")
            self.assertEqual(result["sample_count"], 6)
            self.assertEqual(len(list(private.glob("unblinded-*.json"))), 2)
            self.assertTrue((private / "aggregate.json").is_file())


class PrivatePathContractTests(unittest.TestCase):
    def test_formal_execution_directory_is_scoped_and_symlink_free(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            common_root = Path(temporary)
            eval_data = common_root / "eval-data"
            base = eval_data / "cross-eval"
            execution = base / "fixture-execution-v1"
            eval_data.mkdir()
            base.mkdir(mode=0o700)
            execution.mkdir(mode=0o700)
            paths = SimpleNamespace(common_root=common_root)
            with mock.patch.object(
                cross_eval.RepoPaths, "discover", return_value=paths
            ):
                self.assertEqual(
                    cross_eval._require_execution_private_directory(
                        WORKTREE_ROOT, execution
                    ),
                    execution.resolve(),
                )
                out_of_scope = common_root / "outside-execution"
                out_of_scope.mkdir(mode=0o700)
                with self.assertRaisesRegex(
                    cross_eval.CrossEvalError,
                    "cross_eval_private_directory_out_of_scope",
                ):
                    cross_eval._require_execution_private_directory(
                        WORKTREE_ROOT, out_of_scope
                    )
                linked = base / "linked-execution"
                linked.symlink_to(execution, target_is_directory=True)
                with self.assertRaisesRegex(
                    cross_eval.CrossEvalError,
                    "cross_eval_private_directory_out_of_scope",
                ):
                    cross_eval._require_execution_private_directory(
                        WORKTREE_ROOT, linked
                    )

    def test_cli_repository_path_error_is_stable_not_ready_json(self) -> None:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = cross_eval.main(
                [
                    "preflight",
                    "--worktree-root",
                    "/tmp",
                    "--private-dir",
                    "/tmp",
                ]
            )
        self.assertEqual(result, 2)
        self.assertEqual(
            json.loads(output.getvalue()),
            {"status": "not_ready", "blocker": "filesystem_error"},
        )


class HoldoutBoundaryTests(unittest.TestCase):
    def test_private_holdout_contract_and_public_projection_are_batch_only(self) -> None:
        records = []
        for index in range(2):
            source = source_candidate(index)
            records.append(
                {
                    "schema_version": 1,
                    "contract_version": cross_eval.HOLDOUT_PRIVATE_CONTRACT_VERSION,
                    "holdout_batch_id": "fixture-holdout-v1",
                    "sample_id": digest(f"holdout-sample-{index}"),
                    "source_group_id": f"holdout-group-{index}",
                    "split_group_id": digest(f"holdout-split-{index}"),
                    "approval_input": source["input"],
                    "payload_sha256": source["payload_sha256"],
                    "sol_target": source["target"],
                    "teacher_model": "point-in-time-teacher",
                    "generated_date": FIXTURE_DATE,
                    "teacher_prompt_version": "holdout-teacher-v1",
                    "teacher_prompt_sha256": digest("holdout-teacher-prompt"),
                }
            )
        bundle = cross_eval.build_private_holdout_bundle(
            records, holdout_batch_id="fixture-holdout-v1"
        )
        self.assertEqual(bundle.partition, "holdout")
        self.assertEqual(bundle.manifest["visibility"], "private_only")
        aggregate = {
            "schema_version": cross_eval.AGGREGATE_SCHEMA_VERSION,
            "contract_version": cross_eval.AGGREGATE_CONTRACT_VERSION,
            "partition": "holdout",
            "cohort_manifest_sha256": bundle.manifest_sha256,
            "body_batch_ids": ["holdout-anchor-b01"],
            "sample_count": 2,
            "judge_models": [JUDGE_MODEL],
            "judged_dates": [FIXTURE_DATE],
            "judge_outcomes": {"allow": 1, "deny": 1},
            "sides": {
                side: aggregate_side_facts(2, preferred=side == "sol-static")
                for side in cross_eval.SIDES
            },
            "decision": None,
            "thresholds": None,
            "synthetic_holdout_combined": False,
        }
        projection = cross_eval.public_holdout_summary(aggregate)
        raw = cross_eval._canonical_bytes(projection)
        self.assertIsNone(projection["tasks"])
        for marker in (b"sample_id", b"approval_input", b"rationale", b"candidate-a"):
            self.assertNotIn(marker, raw)

        leaked = copy.deepcopy(aggregate)
        leaked["sides"]["sol-static"]["rows"] = [
            {
                "sample_id": records[0]["sample_id"],
                "output": records[0]["sol_target"],
                "reason": "private detail",
            }
        ]
        with self.assertRaisesRegex(
            cross_eval.CrossEvalError, "holdout_projection_side_fields_invalid"
        ):
            cross_eval.public_holdout_summary(leaked)

    def test_holdout_private_source_hash_binds_teacher_provenance(self) -> None:
        source = source_candidate(0)
        record = {
            "schema_version": 1,
            "contract_version": cross_eval.HOLDOUT_PRIVATE_CONTRACT_VERSION,
            "holdout_batch_id": "fixture-holdout-v1",
            "sample_id": digest("holdout-provenance-sample"),
            "source_group_id": "holdout-provenance-group",
            "split_group_id": digest("holdout-provenance-split"),
            "approval_input": source["input"],
            "payload_sha256": source["payload_sha256"],
            "sol_target": source["target"],
            "teacher_model": "point-in-time-teacher-a",
            "generated_date": FIXTURE_DATE,
            "teacher_prompt_version": "holdout-teacher-v1",
            "teacher_prompt_sha256": digest("holdout-teacher-prompt"),
        }
        first = cross_eval.build_private_holdout_bundle(
            [record], holdout_batch_id="fixture-holdout-v1"
        )
        changed = copy.deepcopy(record)
        changed["teacher_model"] = "point-in-time-teacher-b"
        second = cross_eval.build_private_holdout_bundle(
            [changed], holdout_batch_id="fixture-holdout-v1"
        )
        self.assertNotEqual(
            first.manifest["source"]["private_source_sha256"],
            second.manifest["source"]["private_source_sha256"],
        )

    def test_synthetic_and_holdout_cannot_be_aggregated_together(self) -> None:
        bundle = fixture_bundle()
        rows = three_side_rows(bundle)
        blind = cross_eval.build_blind_batches(
            bundle,
            rows,
            judge_model=JUDGE_MODEL,
            judged_date=FIXTURE_DATE,
            seed=bytes(range(32)),
            templates=cross_eval.load_template_identity(WORKTREE_ROOT),
            l6_pair_receipt=l6_pair_receipt(),
        )[0]
        synthetic = cross_eval.unblind_batch(
            bundle,
            rows,
            blind,
            judge_rows(blind),
            l6_pair_receipt=l6_pair_receipt(),
        )
        holdout = copy.deepcopy(synthetic)
        holdout["partition"] = "holdout"
        with self.assertRaisesRegex(cross_eval.CrossEvalError, "aggregate_partition_mixed"):
            cross_eval.aggregate_unblinded([synthetic, holdout])


if __name__ == "__main__":
    unittest.main()
