from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rondo_eval.local_approval import (
    cross_eval,
    formal_result,
    holdout_anchor,
)

from eval.tests.test_local_m4_cross_eval import (
    FIXTURE_DATE,
    JUDGE_MODEL,
    WORKTREE_ROOT,
    aggregate_side_facts,
    digest,
    fixture_bundle,
    judge_rows,
    l6_pair_receipt,
    source_candidate,
    three_side_rows,
)


HOLDOUT_BATCH_ID = "fixture-holdout-anchor-v1"
TEACHER_MODEL = "point-in-time-teacher"
TEACHER_PROMPT_VERSION = "holdout-teacher-prompt-v1"
TEACHER_PROMPT_SHA256 = digest("holdout-teacher-prompt")


def frozen_batch(count: int = 4, *, holdout: int = 2) -> dict:
    """Build a Plan 032 shaped frozen batch with mixed partitions and exclusions."""

    instances = []
    outbound = []
    labels = []
    for index in range(count):
        source = source_candidate(index)
        semantic_id = digest(f"holdout-semantic-{index}")
        partition = "holdout" if index < holdout else "seed"
        instance = {
            "semantic_id": semantic_id,
            "task_id": f"terminal-bench/fixture-task-{index}",
            "e_final_sha256": digest(f"holdout-e-final-{index}"),
            "static_payload_sha256": source["payload_sha256"],
            "partition": partition,
            "usage": (
                "holdout_evaluation_only"
                if partition == "holdout"
                else "seed_evaluation_and_future_synthesis_reference"
            ),
            "selected": True,
        }
        instances.append(instance)
        outbound.append(
            {
                "semantic_id": semantic_id,
                "partition": partition,
                "static_payload_sha256": source["payload_sha256"],
                "canonical_payload": copy.deepcopy(source["input"]),
            }
        )
        labels.append(
            {
                "semantic_id": semantic_id,
                "partition": partition,
                "static_payload_sha256": source["payload_sha256"],
                "representative_e_final_sha256": instance["e_final_sha256"],
                "teacher_model": TEACHER_MODEL,
                "generated_date": FIXTURE_DATE,
                "prompt_version": TEACHER_PROMPT_VERSION,
                "prompt_sha256": TEACHER_PROMPT_SHA256,
                "decision": copy.deepcopy(source["target"]),
            }
        )
    # One over-window instance that Plan 032 excluded: it must never surface.
    excluded = source_candidate(count)
    instances.append(
        {
            "semantic_id": digest(f"holdout-semantic-{count}"),
            "task_id": f"terminal-bench/fixture-task-{count}",
            "e_final_sha256": digest(f"holdout-e-final-{count}"),
            "static_payload_sha256": excluded["payload_sha256"],
            "partition": "holdout",
            "usage": "holdout_evaluation_only",
            "selected": False,
        }
    )
    return {
        "manifest": {
            "batch_id": "20260815-fixture-teacher-labels-v1",
            "prompt_version": TEACHER_PROMPT_VERSION,
            "prompt_sha256": TEACHER_PROMPT_SHA256,
            "counts": {"selected_partitions": {"seed": count - holdout, "holdout": holdout}},
            "instances": instances,
        },
        "manifest_sha256": digest("holdout-frozen-manifest"),
        "outbound": outbound,
        "labels": labels,
        "labels_sha256": digest("holdout-frozen-labels"),
        "teacher_model": TEACHER_MODEL,
        "generated_date": FIXTURE_DATE,
    }


def holdout_records(count: int = 4, *, holdout: int = 2) -> list[dict]:
    return holdout_anchor.build_holdout_records(
        frozen_batch(count, holdout=holdout), holdout_batch_id=HOLDOUT_BATCH_ID
    )


class HoldoutMaterializationTest(unittest.TestCase):
    def test_only_selected_holdout_rows_are_projected(self) -> None:
        records = holdout_records()
        self.assertEqual(len(records), 2)
        self.assertEqual(
            [record["sample_id"] for record in records],
            sorted(record["sample_id"] for record in records),
        )
        for record in records:
            self.assertEqual(
                record["contract_version"], cross_eval.HOLDOUT_PRIVATE_CONTRACT_VERSION
            )
            self.assertEqual(record["holdout_batch_id"], HOLDOUT_BATCH_ID)
            self.assertEqual(record["split_group_id"], record["sample_id"])
            self.assertTrue(
                record["source_group_id"].startswith(
                    holdout_anchor.SOURCE_GROUP_PREFIX
                )
            )
            self.assertEqual(record["teacher_model"], TEACHER_MODEL)
            identities = cross_eval._approval_identities(record["approval_input"])
            self.assertEqual(identities["payload_sha256"], record["payload_sha256"])

    def test_source_group_is_stable_and_body_free(self) -> None:
        first = holdout_anchor._source_group_id("terminal-bench/fix-git")
        second = holdout_anchor._source_group_id("terminal-bench/fix-git")
        other = holdout_anchor._source_group_id("terminal-bench/other-task")
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertNotIn("fix-git", first)
        self.assertIsNotNone(cross_eval._ID.fullmatch(first))

    def test_declared_and_materialized_holdout_counts_must_agree(self) -> None:
        batch = frozen_batch()
        batch["manifest"]["counts"]["selected_partitions"]["holdout"] = 3
        with self.assertRaisesRegex(
            holdout_anchor.HoldoutAnchorError, "holdout_set_incomplete"
        ):
            holdout_anchor.build_holdout_records(
                batch, holdout_batch_id=HOLDOUT_BATCH_ID
            )

    def test_teacher_identity_drift_is_rejected(self) -> None:
        mutations = (
            ("labels", 0, "teacher_model", "other-teacher"),
            ("labels", 0, "generated_date", "2026-01-01"),
            ("labels", 0, "prompt_sha256", digest("other-prompt")),
            ("labels", 0, "static_payload_sha256", digest("other-payload")),
            ("outbound", 0, "static_payload_sha256", digest("other-payload")),
        )
        for section, index, field, value in mutations:
            batch = frozen_batch()
            batch[section][index][field] = value
            with self.subTest(section=section, field=field):
                with self.assertRaisesRegex(
                    holdout_anchor.HoldoutAnchorError,
                    "holdout_sample_identity_drift",
                ):
                    holdout_anchor.build_holdout_records(
                        batch, holdout_batch_id=HOLDOUT_BATCH_ID
                    )

    def test_missing_label_or_payload_fails_closed(self) -> None:
        batch = frozen_batch()
        batch["labels"] = batch["labels"][1:]
        with self.assertRaisesRegex(
            holdout_anchor.HoldoutAnchorError, "holdout_sample_source_missing"
        ):
            holdout_anchor.build_holdout_records(
                batch, holdout_batch_id=HOLDOUT_BATCH_ID
            )


class HoldoutBundleTest(unittest.TestCase):
    def _materialize(self, private: Path) -> cross_eval.CohortBundle:
        records = holdout_records()
        bundle = cross_eval.build_private_holdout_bundle(
            records, holdout_batch_id=HOLDOUT_BATCH_ID
        )
        cross_eval._write_exclusive(
            private / holdout_anchor.SOURCE_FILE_NAME,
            cross_eval._jsonl_bytes(records),
            mode=0o600,
        )
        receipt = {
            "schema_version": holdout_anchor.MATERIALIZATION_SCHEMA_VERSION,
            "contract_version": holdout_anchor.MATERIALIZATION_CONTRACT_VERSION,
            "holdout_batch_id": HOLDOUT_BATCH_ID,
            "cohort_manifest_sha256": bundle.manifest_sha256,
            "private_source_sha256": bundle.manifest["source"]["private_source_sha256"],
            "sample_count": len(records),
        }
        cross_eval._write_exclusive(
            private / holdout_anchor.RECEIPT_FILE_NAME,
            cross_eval._json_file_bytes(receipt),
            mode=0o600,
        )
        return bundle

    def test_reload_rebuilds_the_same_private_cohort(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary) / "holdout-execution"
            private.mkdir(mode=0o700)
            expected = self._materialize(private)
            loaded = holdout_anchor.load_holdout_bundle(private)
            self.assertEqual(loaded.partition, "holdout")
            self.assertEqual(loaded.manifest_sha256, expected.manifest_sha256)
            self.assertEqual(loaded.manifest["visibility"], "private_only")

    def test_receipt_binding_rejects_a_tampered_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary) / "holdout-execution"
            private.mkdir(mode=0o700)
            self._materialize(private)
            source_path = private / holdout_anchor.SOURCE_FILE_NAME
            records = holdout_records()
            records[0]["sol_target"] = {
                "outcome": "deny",
                "rationale": "tampered target",
                "risk_tags": ["tampered"],
            }
            source_path.unlink()
            cross_eval._write_exclusive(
                source_path, cross_eval._jsonl_bytes(records), mode=0o600
            )
            with self.assertRaisesRegex(
                holdout_anchor.HoldoutAnchorError, "holdout_receipt_binding_invalid"
            ):
                holdout_anchor.load_holdout_bundle(private)

    def test_cli_bundle_selection_rewraps_a_foreign_cohort_class(self) -> None:
        """Under ``python -m`` this module is also loaded as ``__main__``."""

        import dataclasses
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary) / "holdout-execution"
            private.mkdir(mode=0o700)
            expected = self._materialize(private)

            @dataclasses.dataclass(frozen=True)
            class ForeignCohortBundle:
                partition: str
                manifest: dict
                manifest_sha256: str
                source_rows: dict

            real_loader = holdout_anchor.load_holdout_bundle

            def foreign_loader(path: Path) -> ForeignCohortBundle:
                built = real_loader(path)
                return ForeignCohortBundle(
                    built.partition,
                    built.manifest,
                    built.manifest_sha256,
                    built.source_rows,
                )

            with mock.patch.object(
                holdout_anchor, "load_holdout_bundle", foreign_loader
            ):
                selected = cross_eval._selected_bundle(
                    SimpleNamespace(partition="holdout", private_dir=private)
                )
            self.assertIsInstance(selected, cross_eval.CohortBundle)
            self.assertEqual(selected.manifest_sha256, expected.manifest_sha256)
            cross_eval.validate_cohort_bundle(selected)

    def test_holdout_bundle_cannot_be_imported_as_the_synthetic_cohort(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary) / "holdout-execution"
            private.mkdir(mode=0o700)
            self._materialize(private)
            outputs = private / "three-side-outputs.jsonl"
            receipt = private / "l6-pair-receipt.json"
            cross_eval._write_exclusive(outputs, b"{}\n", mode=0o600)
            cross_eval._write_exclusive(receipt, b"{}\n", mode=0o600)
            with self.assertRaisesRegex(
                cross_eval.CrossEvalError, "synthetic_bundle_must_be_tracked"
            ):
                cross_eval.validate_three_side_import(
                    WORKTREE_ROOT,
                    outputs,
                    receipt,
                    bundle=fixture_bundle(2),
                )


class HoldoutBlindRoundTripTest(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = cross_eval.build_private_holdout_bundle(
            holdout_records(6, holdout=6), holdout_batch_id=HOLDOUT_BATCH_ID
        )
        self.rows = three_side_rows(self.bundle)
        self.blinds = cross_eval.build_blind_batches(
            self.bundle,
            self.rows,
            judge_model=JUDGE_MODEL,
            judged_date=FIXTURE_DATE,
            seed=bytes(range(32)),
            templates=cross_eval.load_template_identity(WORKTREE_ROOT),
            l6_pair_receipt=l6_pair_receipt(),
        )

    def test_holdout_packages_are_anonymous_balanced_and_partition_tagged(self) -> None:
        seen = set()
        for blind in self.blinds:
            self.assertEqual(blind.package["partition"], "holdout")
            self.assertTrue(blind.request["body_batch_id"].startswith("holdout-anchor-"))
            seen.update(item["sample_id"] for item in blind.package["samples"])
            raw = cross_eval._canonical_bytes(blind.package)
            for marker in (b"sol-static", b"local-ft-static", b"side", b"teacher"):
                self.assertNotIn(marker, raw)
            # The private batch id is the Sol side's source_dataset_batch_id,
            # so it must not reach the judge through the cohort identity.
            self.assertNotIn(HOLDOUT_BATCH_ID.encode("utf-8"), raw)
            self.assertNotIn(HOLDOUT_BATCH_ID, self.bundle.manifest["cohort_id"])
            counts = cross_eval._position_counts(blind.mapping["entries"])
            for side in cross_eval.SIDES:
                values = list(counts[side].values())
                self.assertLessEqual(max(values) - min(values), 1)
        self.assertEqual(seen, set(self.bundle.source_rows))

    def test_unblind_and_aggregate_stay_inside_the_holdout_partition(self) -> None:
        unblinded = [
            cross_eval.unblind_batch(
                self.bundle,
                self.rows,
                blind,
                judge_rows(blind),
                l6_pair_receipt=l6_pair_receipt(),
            )
            for blind in self.blinds
        ]
        aggregate = cross_eval.aggregate_unblinded(unblinded)
        self.assertEqual(aggregate["partition"], "holdout")
        self.assertEqual(aggregate["sample_count"], 6)
        self.assertFalse(aggregate["synthetic_holdout_combined"])
        projection = cross_eval.public_holdout_summary(aggregate)
        self.assertIsNone(projection["tasks"])
        raw = cross_eval._canonical_bytes(projection)
        for marker in (b"sample_id", b"approval_input", b"rationale"):
            self.assertNotIn(marker, raw)


def formal_pair_evidence() -> cross_eval.FormalL6PairEvidence:
    """Formal v2 local rows require source-validated evidence, not a bare receipt.

    The source-validation gate itself is covered by the paired-output tests; here
    the same already-validated receipt is wrapped so the packaging semantics can
    be exercised directly.
    """

    return cross_eval.FormalL6PairEvidence._from_source_validation(l6_pair_receipt())


def mixed_terminal_rows(bundle: cross_eval.CohortBundle) -> list[dict]:
    """Give the unfine-tuned side one recorded terminal with no decision."""

    rows = copy.deepcopy(three_side_rows(bundle))
    failed_sample = sorted(bundle.source_rows)[0]
    for row in rows:
        if row["side"] == "local-static" and row["sample_id"] == failed_sample:
            row.pop("decision")
            row["schema_version"] = cross_eval.TERMINAL_IMPORT_SCHEMA_VERSION
            row["contract_version"] = cross_eval.TERMINAL_IMPORT_CONTRACT_VERSION
            row["terminal"] = {
                "schema_version": cross_eval.OUTPUT_TERMINAL_SCHEMA_VERSION,
                "contract_version": cross_eval.OUTPUT_TERMINAL_CONTRACT_VERSION,
                "status": "structured_output_failure",
                "failure_code": "fixture-structured-output",
            }
    return rows


def terminal_judge_rows(blind: cross_eval.BlindBatch) -> list[dict]:
    request = blind.request
    values = []
    for sample in blind.package["samples"]:
        assessments = []
        preferred = []
        for candidate in sample["candidates"]:
            if candidate["terminal"]["status"] == "decision":
                assessments.append(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "approval_judgment": "supported",
                        "reason_quality": "adequate",
                        "rationale": "The supplied evidence supports this call.",
                    }
                )
                preferred.append(candidate["candidate_id"])
            else:
                assessments.append(
                    {
                        "candidate_id": candidate["candidate_id"],
                        "approval_judgment": cross_eval.NO_DECISION_JUDGMENT,
                        "reason_quality": cross_eval.NO_DECISION_QUALITY,
                        "rationale": "No compliant decision was produced.",
                    }
                )
        values.append(
            {
                "schema_version": cross_eval.HOLDOUT_JUDGE_RESULT_SCHEMA_VERSION,
                "contract_version": cross_eval.HOLDOUT_JUDGE_RESULT_CONTRACT_VERSION,
                "partition": request["partition"],
                "cohort_manifest_sha256": request["cohort_manifest_sha256"],
                "body_batch_id": request["body_batch_id"],
                "package_sha256": request["package_sha256"],
                "sample_id": sample["sample_id"],
                "judge_prompt_version": request["judge_prompt_version"],
                "judge_prompt_sha256": request["judge_prompt_sha256"],
                "judge_model": request["expected_judge_model"],
                "judged_date": request["expected_judged_date"],
                "independent_judgment": {
                    "outcome": "allow",
                    "rationale": "The requested action is supported by the evidence.",
                    "risk_tags": [],
                },
                "candidate_assessments": assessments,
                "preferred_candidates": preferred,
                "all_candidates_inadequate": False,
                "comparative_rationale": "Compared on the shared evidence only.",
            }
        )
    return values


class HoldoutMixedTerminalTest(unittest.TestCase):
    """The holdout-only v2 contract must express recorded failures honestly."""

    def setUp(self) -> None:
        self.bundle = cross_eval.build_private_holdout_bundle(
            holdout_records(6, holdout=6), holdout_batch_id=HOLDOUT_BATCH_ID
        )
        self.rows = mixed_terminal_rows(self.bundle)
        self.templates = cross_eval.load_template_identity(WORKTREE_ROOT)
        self.blinds = cross_eval.build_terminal_blind_batches(
            self.bundle,
            self.rows,
            judge_model=JUDGE_MODEL,
            judged_date=FIXTURE_DATE,
            seed=bytes(range(32)),
            templates=self.templates,
            l6_pair_receipt=formal_pair_evidence(),
        )

    def test_frozen_v1_package_still_refuses_a_missing_decision(self) -> None:
        with self.assertRaisesRegex(
            cross_eval.CrossEvalError, "judge_package_v1_requires_decision_terminals"
        ):
            cross_eval.build_blind_batches(
                self.bundle,
                self.rows,
                judge_model=JUDGE_MODEL,
                judged_date=FIXTURE_DATE,
                seed=bytes(range(32)),
                templates=self.templates,
                l6_pair_receipt=formal_pair_evidence(),
            )

    def test_terminal_package_keeps_the_complete_set_and_is_holdout_only(self) -> None:
        covered = {
            item["sample_id"]
            for blind in self.blinds
            for item in blind.package["samples"]
        }
        self.assertEqual(covered, set(self.bundle.source_rows))
        statuses = [
            candidate["terminal"]["status"]
            for blind in self.blinds
            for sample in blind.package["samples"]
            for candidate in sample["candidates"]
        ]
        self.assertEqual(statuses.count("structured_output_failure"), 1)
        self.assertEqual(len(statuses), 18)
        for blind in self.blinds:
            self.assertEqual(
                blind.package["judge_prompt_version"],
                cross_eval.HOLDOUT_JUDGE_PROMPT_VERSION,
            )
            raw = cross_eval._canonical_bytes(blind.package)
            for marker in (b"sol-static", b"local-static", b"local-ft-static"):
                self.assertNotIn(marker, raw)
        with self.assertRaisesRegex(
            cross_eval.CrossEvalError, "terminal_package_is_holdout_only"
        ):
            cross_eval.build_terminal_blind_batches(
                fixture_bundle(6),
                three_side_rows(fixture_bundle(6)),
                judge_model=JUDGE_MODEL,
                judged_date=FIXTURE_DATE,
                seed=bytes(range(32)),
                templates=self.templates,
                l6_pair_receipt=formal_pair_evidence(),
            )

    def test_no_decision_candidate_cannot_be_scored_or_preferred(self) -> None:
        blind = next(
            item
            for item in self.blinds
            if any(
                candidate["terminal"]["status"] != "decision"
                for sample in item.package["samples"]
                for candidate in sample["candidates"]
            )
        )
        valid = terminal_judge_rows(blind)
        target = next(
            row
            for row in valid
            if any(
                item["approval_judgment"] == cross_eval.NO_DECISION_JUDGMENT
                for item in row["candidate_assessments"]
            )
        )
        missing = next(
            item
            for item in target["candidate_assessments"]
            if item["approval_judgment"] == cross_eval.NO_DECISION_JUDGMENT
        )

        scored = copy.deepcopy(valid)
        entry = next(
            item
            for item in next(
                row for row in scored if row["sample_id"] == target["sample_id"]
            )["candidate_assessments"]
            if item["candidate_id"] == missing["candidate_id"]
        )
        entry["approval_judgment"] = "unsupported"
        entry["reason_quality"] = "weak"
        with self.assertRaisesRegex(
            cross_eval.CrossEvalError, "judge_terminal_assessment_mismatch"
        ):
            cross_eval.validate_judge_results(blind, scored, markers=set(cross_eval.SIDES))

        promoted = copy.deepcopy(valid)
        row = next(
            item for item in promoted if item["sample_id"] == target["sample_id"]
        )
        row["preferred_candidates"] = sorted(
            {*row["preferred_candidates"], missing["candidate_id"]}
        )
        with self.assertRaisesRegex(
            cross_eval.CrossEvalError, "judge_no_decision_candidate_preferred"
        ):
            cross_eval.validate_judge_results(
                blind, promoted, markers=set(cross_eval.SIDES)
            )

    def test_missing_decision_never_becomes_an_implied_deny(self) -> None:
        unblinded = [
            cross_eval.unblind_batch(
                self.bundle,
                self.rows,
                blind,
                terminal_judge_rows(blind),
                l6_pair_receipt=formal_pair_evidence(),
            )
            for blind in self.blinds
        ]
        aggregate = cross_eval.aggregate_unblinded(unblinded)
        base = aggregate["sides"]["local-static"]
        tuned = aggregate["sides"]["local-ft-static"]
        self.assertEqual(base["candidate_outcomes"].get("no_decision"), 1)
        self.assertNotIn("no_decision", tuned["candidate_outcomes"])
        self.assertEqual(
            base["judge_outcome_agreement"]
            + base["judge_deny_side_allow"]
            + base["judge_allow_side_deny"],
            5,
        )
        self.assertEqual(
            tuned["judge_outcome_agreement"]
            + tuned["judge_deny_side_allow"]
            + tuned["judge_allow_side_deny"],
            6,
        )
        projection = cross_eval.public_holdout_summary(aggregate)
        self.assertEqual(projection["contract_version"], "rondo_m4_holdout_batch_summary_v2")
        self.assertIsNone(projection["tasks"])
        self.assertEqual(projection["sides"]["local-static"]["no_decision_count"], 1)
        self.assertEqual(
            projection["sides"]["local-static"]["comparable_decision_count"], 5
        )
        self.assertEqual(
            projection["sides"]["local-ft-static"]["no_decision_count"], 0
        )
        raw = cross_eval._canonical_bytes(projection)
        for marker in (b"sample_id", b"approval_input", b"rationale"):
            self.assertNotIn(marker, raw)


class FormalResultTest(unittest.TestCase):
    def setUp(self) -> None:
        self.synthetic_bundle = fixture_bundle(6)
        self.synthetic_rows = three_side_rows(self.synthetic_bundle)
        self.holdout_bundle = cross_eval.build_private_holdout_bundle(
            holdout_records(6, holdout=6), holdout_batch_id=HOLDOUT_BATCH_ID
        )
        self.holdout_rows = three_side_rows(self.holdout_bundle)

    def _aggregate(self, partition: str, cohort_sha: str, batch_id: str) -> dict:
        return {
            "schema_version": cross_eval.AGGREGATE_SCHEMA_VERSION,
            "contract_version": cross_eval.AGGREGATE_CONTRACT_VERSION,
            "partition": partition,
            "cohort_manifest_sha256": cohort_sha,
            "body_batch_ids": [batch_id],
            "sample_count": 6,
            "judge_models": [JUDGE_MODEL],
            "judged_dates": [FIXTURE_DATE],
            "judge_outcomes": {"allow": 3, "deny": 3},
            "sides": {
                side: aggregate_side_facts(6, preferred=side == "sol-static")
                for side in cross_eval.SIDES
            },
            "decision": None,
            "thresholds": None,
            "synthetic_holdout_combined": False,
        }

    def _request(self, **overrides: object) -> dict:
        request = {
            "review_id": "fixture-local-m4-formal-v1",
            "judge_model": JUDGE_MODEL,
            "synthetic_judge_contract": {
                "prompt_version": cross_eval.JUDGE_PROMPT_VERSION,
                "prompt_sha256": digest("judge-prompt"),
                "result_schema_version": cross_eval.JUDGE_RESULT_SCHEMA_VERSION,
                "result_schema_sha256": digest("judge-result-schema"),
            },
            "holdout_judge_contract": {
                "prompt_version": cross_eval.HOLDOUT_JUDGE_PROMPT_VERSION,
                "prompt_sha256": digest("holdout-judge-prompt"),
                "result_schema_version": cross_eval.HOLDOUT_JUDGE_RESULT_SCHEMA_VERSION,
                "result_schema_sha256": digest("holdout-judge-result-schema"),
            },
            "synthetic_aggregate": self._aggregate(
                "synthetic",
                self.synthetic_bundle.manifest_sha256,
                "synthetic-body-b01",
            ),
            "synthetic_rows": self.synthetic_rows,
            "holdout_aggregate": self._aggregate(
                "holdout", self.holdout_bundle.manifest_sha256, "holdout-anchor-b01"
            ),
            "holdout_rows": self.holdout_rows,
            "decision": "keep_as_experiment",
            "decision_date": FIXTURE_DATE,
            "decision_rationale": "Fixture decision recorded by the user.",
            "private_artifacts": {"synthetic-aggregate": digest("aggregate")},
            "limitations": ["Point-in-time subscription judge."],
        }
        request.update(overrides)
        return request

    def test_result_keeps_partitions_separate_and_records_the_user_decision(self) -> None:
        value = formal_result.build_formal_result(**self._request())
        self.assertEqual(value["decision"]["choice"], "keep_as_experiment")
        self.assertEqual(value["decision"]["made_by"], "user")
        self.assertFalse(value["decision"]["production_default_changed"])
        self.assertFalse(value["boundaries"]["synthetic_holdout_combined"])
        self.assertIsNone(value["boundaries"]["thresholds"])
        self.assertFalse(value["partitions"]["holdout"]["three_way_ranking_claimed"])
        self.assertIsNone(value["partitions"]["holdout"]["batch_summary"]["tasks"])
        self.assertNotEqual(
            value["partitions"]["synthetic"]["cohort_manifest_sha256"],
            value["partitions"]["holdout"]["batch_summary"]["cohort_manifest_sha256"],
        )
        raw = cross_eval._canonical_bytes(value)
        for marker in (b"approval_input", b"candidate-a", b"comparative_rationale"):
            self.assertNotIn(marker, raw)

    def test_unknown_decision_and_mixed_judge_identity_are_rejected(self) -> None:
        with self.assertRaisesRegex(
            formal_result.FormalResultError, "formal_result_decision_invalid"
        ):
            formal_result.build_formal_result(**self._request(decision="adopt_later"))
        mixed = self._request()
        mixed["holdout_aggregate"]["judge_models"] = ["other-judge"]
        with self.assertRaisesRegex(
            formal_result.FormalResultError, "formal_result_judge_identity_mixed"
        ):
            formal_result.build_formal_result(**mixed)

    def test_same_cohort_for_both_partitions_is_rejected(self) -> None:
        request = self._request()
        request["holdout_aggregate"]["cohort_manifest_sha256"] = (
            self.synthetic_bundle.manifest_sha256
        )
        with self.assertRaisesRegex(
            formal_result.FormalResultError,
            "formal_result_partition_cohorts_not_distinct",
        ):
            formal_result.build_formal_result(**request)

    def test_teacher_agreement_only_counts_comparable_decisions(self) -> None:
        rows = copy.deepcopy(self.synthetic_rows)
        failed = next(row for row in rows if row["side"] == "local-static")
        failed.pop("decision", None)
        failed["schema_version"] = cross_eval.TERMINAL_IMPORT_SCHEMA_VERSION
        failed["contract_version"] = cross_eval.TERMINAL_IMPORT_CONTRACT_VERSION
        failed["terminal"] = {
            "schema_version": cross_eval.OUTPUT_TERMINAL_SCHEMA_VERSION,
            "contract_version": cross_eval.OUTPUT_TERMINAL_CONTRACT_VERSION,
            "status": "structured_output_failure",
            "failure_code": "fixture-structured-output",
        }
        agreement = formal_result.teacher_agreement(rows)
        terminals = formal_result.side_terminal_counts(rows)
        self.assertEqual(agreement["local-static"]["sample_count"], 6)
        self.assertEqual(agreement["local-static"]["comparable_decision_count"], 5)
        self.assertEqual(agreement["local-ft-static"]["comparable_decision_count"], 6)
        self.assertEqual(
            terminals["local-static"]["structured_output_failure"], 1
        )
        self.assertEqual(terminals["sol-static"]["decision"], 6)


if __name__ == "__main__":
    unittest.main()
