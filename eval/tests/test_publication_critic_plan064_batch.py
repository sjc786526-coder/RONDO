from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.training_data import TrainingDataError  # noqa: E402
from rondo_eval.publication_critic.training_data.plan064_batch import (  # noqa: E402
    BATCH_SCHEMA,
    SOURCE_ID,
    aggregate_compiled_plan064_batches,
    aggregate_plan064_reviews,
    compile_plan064_batch,
    create_plan064_review_binding,
    load_plan064_batch,
    write_compiled_plan064_batch,
)


class PublicationCriticPlan064BatchTests(unittest.TestCase):
    def test_valid_batch_compiles_to_existing_pending_v1_rows(self) -> None:
        compiled = compile_plan064_batch(self._batch())

        self.assertEqual(compiled.batch_id, "p064-batch-useful-a")
        self.assertEqual(len(compiled.scenarios), 1)
        self.assertEqual(len(compiled.packets), 2)
        self.assertEqual(len(compiled.supervision), 2)
        self.assertEqual(len(compiled.pairs), 1)
        self.assertEqual(compiled.scenarios[0]["source_id"], SOURCE_ID)
        self.assertEqual(
            {row["candidate_id"] for row in compiled.packets},
            {"pc064-useful-train-01-qplus", "pc064-useful-train-01-qminus"},
        )
        self.assertEqual(
            {row["review_status"] for row in compiled.supervision},
            {"pending"},
        )
        self.assertEqual(
            {row["reviewer_identity"] for row in compiled.supervision},
            {None},
        )
        pair = compiled.pairs[0]
        self.assertEqual(pair["preferred_candidate_id"], "pc064-useful-train-01-qplus")
        self.assertEqual(pair["dispreferred_candidate_id"], "pc064-useful-train-01-qminus")
        self.assertEqual(pair["review_status"], "pending")
        packet = compiled.packets[0]["packet"]
        self.assertEqual(packet["continuity"]["prior_publications"][0]["summary"], "The reload bug is reproducible.")

    def test_existing_pair_semantics_reject_reversed_boundary(self) -> None:
        batch = self._batch()
        pair = batch["scenarios"][0]["pairs"][0]
        pair["preferred"], pair["dispreferred"] = pair["dispreferred"], pair["preferred"]

        with self.assertRaisesRegex(TrainingDataError, "must be PASS > REWRITE"):
            compile_plan064_batch(batch)

    def test_batch_schema_is_exact(self) -> None:
        batch = self._batch()
        batch["unexpected"] = True
        with self.assertRaisesRegex(TrainingDataError, "keys differ"):
            compile_plan064_batch(batch)

    def test_duplicate_candidate_suffix_is_rejected_before_expansion(self) -> None:
        batch = self._batch()
        duplicate = copy.deepcopy(batch["scenarios"][0]["candidates"][0])
        batch["scenarios"][0]["candidates"].append(duplicate)
        with self.assertRaisesRegex(TrainingDataError, "duplicate candidate id_suffix"):
            compile_plan064_batch(batch)

    def test_writer_creates_secure_files_and_rejects_unsafe_targets(self) -> None:
        compiled = compile_plan064_batch(self._batch())
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            namespace = root / "plan064"
            namespace.mkdir(mode=0o700)
            namespace.chmod(0o700)
            output = namespace / "batch-a"

            write_compiled_plan064_batch(output, compiled, namespace=namespace)
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
            self.assertEqual(
                {path.name for path in output.iterdir()},
                {"scenarios.jsonl", "packets.jsonl", "supervision.jsonl", "pairs.jsonl"},
            )
            for path in output.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                for line in path.read_text(encoding="utf-8").splitlines():
                    self.assertIsInstance(json.loads(line), dict)

            with self.assertRaisesRegex(TrainingDataError, "must be a new path"):
                write_compiled_plan064_batch(output, compiled, namespace=namespace)

            outside = root / "outside"
            with self.assertRaisesRegex(TrainingDataError, "outside the ignored namespace"):
                write_compiled_plan064_batch(outside, compiled, namespace=namespace)

            symlink = namespace / "symlink-output"
            os.symlink(root / "target", symlink)
            with self.assertRaisesRegex(TrainingDataError, "must be a new path"):
                write_compiled_plan064_batch(symlink, compiled, namespace=namespace)

    def test_raw_batch_loader_requires_secure_namespace_file(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            namespace = self._namespace(temporary)
            raw_dir = namespace / "raw"
            raw_dir.mkdir(mode=0o700)
            raw = raw_dir / "batch.json"
            raw.write_text(json.dumps(self._batch()), encoding="utf-8")
            raw.chmod(0o600)

            self.assertEqual(
                load_plan064_batch(raw, namespace=namespace),
                self._batch(),
            )
            raw.chmod(0o644)
            with self.assertRaisesRegex(TrainingDataError, "must have mode 600"):
                load_plan064_batch(raw, namespace=namespace)
            raw.chmod(0o600)

            outside = root / "outside.json"
            outside.write_text(json.dumps(self._batch()), encoding="utf-8")
            outside.chmod(0o600)
            with self.assertRaisesRegex(TrainingDataError, "outside the Plan 064 namespace"):
                load_plan064_batch(outside, namespace=namespace)

            linked_parent = namespace / "linked"
            os.symlink(raw_dir, linked_parent)
            with self.assertRaisesRegex(TrainingDataError, "must not traverse symlinks"):
                load_plan064_batch(linked_parent / "batch.json", namespace=namespace)

    def test_aggregate_reads_explicit_batches_and_revalidates_combined_rows(self) -> None:
        first = compile_plan064_batch(self._batch())
        second = compile_plan064_batch(self._second_batch())
        with tempfile.TemporaryDirectory() as temporary:
            namespace = self._namespace(temporary)
            first_dir = namespace / "batch-a"
            second_dir = namespace / "batch-b"
            write_compiled_plan064_batch(first_dir, first, namespace=namespace)
            write_compiled_plan064_batch(second_dir, second, namespace=namespace)

            aggregate = aggregate_compiled_plan064_batches(
                [first_dir, second_dir],
                namespace=namespace,
            )

            self.assertEqual(len(aggregate.scenarios), 2)
            self.assertEqual(len(aggregate.packets), 4)
            self.assertEqual(len(aggregate.supervision), 4)
            self.assertEqual(len(aggregate.pairs), 2)
            self.assertEqual(
                [row["scenario_id"] for row in aggregate.scenarios],
                ["p064-useful-train-01", "p064-useful-validation-02"],
            )

    def test_aggregate_rejects_duplicate_scenario_candidate_and_pair_ids(self) -> None:
        for filename, key, message in (
            ("scenarios.jsonl", "scenario_id", "duplicate scenario_id"),
            ("packets.jsonl", "candidate_id", "duplicate candidate_id"),
            ("pairs.jsonl", "pair_id", "duplicate pair_id"),
        ):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temporary:
                namespace = self._namespace(temporary)
                first_dir = namespace / "batch-a"
                second_dir = namespace / "batch-b"
                write_compiled_plan064_batch(
                    first_dir,
                    compile_plan064_batch(self._batch()),
                    namespace=namespace,
                )
                write_compiled_plan064_batch(
                    second_dir,
                    compile_plan064_batch(self._second_batch()),
                    namespace=namespace,
                )
                first_row = json.loads(
                    (first_dir / filename).read_text(encoding="utf-8").splitlines()[0]
                )
                second_path = second_dir / filename
                second_rows = [
                    json.loads(line)
                    for line in second_path.read_text(encoding="utf-8").splitlines()
                ]
                second_rows[0][key] = first_row[key]
                second_path.write_text(
                    "".join(
                        json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                        for row in second_rows
                    ),
                    encoding="utf-8",
                )
                second_path.chmod(0o600)

                with self.assertRaisesRegex(TrainingDataError, message):
                    aggregate_compiled_plan064_batches(
                        [first_dir, second_dir],
                        namespace=namespace,
                    )

    def test_aggregate_rejects_unsafe_batch_directory_and_files(self) -> None:
        compiled = compile_plan064_batch(self._batch())
        with tempfile.TemporaryDirectory() as temporary:
            namespace = self._namespace(temporary)
            batch_dir = namespace / "batch-a"
            write_compiled_plan064_batch(batch_dir, compiled, namespace=namespace)

            batch_dir.chmod(0o755)
            with self.assertRaisesRegex(TrainingDataError, "must have mode 700"):
                aggregate_compiled_plan064_batches([batch_dir], namespace=namespace)
            batch_dir.chmod(0o700)

            packets = batch_dir / "packets.jsonl"
            packets.chmod(0o644)
            with self.assertRaisesRegex(TrainingDataError, "must have mode 600"):
                aggregate_compiled_plan064_batches([batch_dir], namespace=namespace)
            packets.chmod(0o600)

            pairs = batch_dir / "pairs.jsonl"
            pairs.unlink()
            os.symlink(namespace / "missing-pairs", pairs)
            with self.assertRaisesRegex(TrainingDataError, "non-symlink file"):
                aggregate_compiled_plan064_batches([batch_dir], namespace=namespace)

    def test_aggregate_rechecks_combined_generation_semantics(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            namespace = self._namespace(temporary)
            first_dir = namespace / "batch-a"
            second_dir = namespace / "batch-b"
            write_compiled_plan064_batch(
                first_dir,
                compile_plan064_batch(self._batch()),
                namespace=namespace,
            )
            write_compiled_plan064_batch(
                second_dir,
                compile_plan064_batch(self._second_batch()),
                namespace=namespace,
            )
            pair_path = second_dir / "pairs.jsonl"
            pair = json.loads(pair_path.read_text(encoding="utf-8"))
            pair["preferred_candidate_id"], pair["dispreferred_candidate_id"] = (
                pair["dispreferred_candidate_id"],
                pair["preferred_candidate_id"],
            )
            pair_path.write_text(json.dumps(pair) + "\n", encoding="utf-8")
            pair_path.chmod(0o600)

            with self.assertRaisesRegex(TrainingDataError, "must be PASS > REWRITE"):
                aggregate_compiled_plan064_batches(
                    [first_dir, second_dir],
                    namespace=namespace,
                )

    def test_review_aggregation_binds_batches_and_never_overwrites(self) -> None:
        first = compile_plan064_batch(self._batch())
        second = compile_plan064_batch(self._second_batch())
        with tempfile.TemporaryDirectory() as temporary:
            namespace = self._namespace(temporary)
            first_dir = namespace / "batch-a"
            second_dir = namespace / "batch-b"
            aggregate_dir = namespace / "aggregate"
            write_compiled_plan064_batch(first_dir, first, namespace=namespace)
            write_compiled_plan064_batch(second_dir, second, namespace=namespace)
            aggregate = aggregate_compiled_plan064_batches(
                [first_dir, second_dir],
                namespace=namespace,
            )
            write_compiled_plan064_batch(
                aggregate_dir,
                aggregate,
                namespace=namespace,
            )
            first_reviews = self._write_reviews(namespace, "reviews-a", first_dir, first)
            second_reviews = self._write_reviews(namespace, "reviews-b", second_dir, second)
            first_binding = first_reviews / "review-binding.json"
            self.assertEqual(stat.S_IMODE(first_binding.stat().st_mode), 0o600)
            with self.assertRaisesRegex(TrainingDataError, "refusing to overwrite"):
                create_plan064_review_binding(
                    first_dir,
                    first_reviews,
                    namespace=namespace,
                )
            row_bytes = {
                name: (aggregate_dir / name).read_bytes()
                for name in (
                    "scenarios.jsonl",
                    "packets.jsonl",
                    "supervision.jsonl",
                    "pairs.jsonl",
                )
            }

            counts = aggregate_plan064_reviews(
                [first_dir, second_dir],
                [first_reviews, second_reviews],
                aggregate_dir,
                namespace=namespace,
            )

            self.assertEqual(counts, (4, 2))
            candidate_target = aggregate_dir / "candidate-reviews.jsonl"
            pair_target = aggregate_dir / "pair-reviews.jsonl"
            bindings_target = aggregate_dir / "review-bindings.json"
            self.assertEqual(stat.S_IMODE(candidate_target.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(pair_target.stat().st_mode), 0o600)
            self.assertEqual(len(candidate_target.read_text().splitlines()), 4)
            self.assertEqual(len(pair_target.read_text().splitlines()), 2)
            self.assertEqual(stat.S_IMODE(bindings_target.stat().st_mode), 0o600)
            bindings = json.loads(bindings_target.read_text())
            self.assertEqual(bindings["schema"], "rondo-publication-critic-plan064-aggregate-review-bindings-v1")
            self.assertEqual(len(bindings["source_bindings"]), 2)
            self.assertEqual(bindings["aggregate"]["counts"]["packets"], 4)
            self.assertEqual(bindings["aggregate"]["counts"]["candidate_reviews"], 4)
            for name, content in row_bytes.items():
                self.assertEqual((aggregate_dir / name).read_bytes(), content)

            review_bytes = {
                candidate_target: candidate_target.read_bytes(),
                pair_target: pair_target.read_bytes(),
            }
            with self.assertRaisesRegex(TrainingDataError, "refusing to overwrite"):
                aggregate_plan064_reviews(
                    [first_dir, second_dir],
                    [first_reviews, second_reviews],
                    aggregate_dir,
                    namespace=namespace,
                )
            for path, content in review_bytes.items():
                self.assertEqual(path.read_bytes(), content)

    def test_review_aggregation_rejects_mismatched_order_and_count(self) -> None:
        first = compile_plan064_batch(self._batch())
        second = compile_plan064_batch(self._second_batch())
        with tempfile.TemporaryDirectory() as temporary:
            namespace = self._namespace(temporary)
            first_dir = namespace / "batch-a"
            second_dir = namespace / "batch-b"
            aggregate_dir = namespace / "aggregate"
            write_compiled_plan064_batch(first_dir, first, namespace=namespace)
            write_compiled_plan064_batch(second_dir, second, namespace=namespace)
            write_compiled_plan064_batch(
                aggregate_dir,
                aggregate_compiled_plan064_batches(
                    [first_dir, second_dir],
                    namespace=namespace,
                ),
                namespace=namespace,
            )
            first_reviews = self._write_reviews(namespace, "reviews-a", first_dir, first)
            second_reviews = self._write_reviews(namespace, "reviews-b", second_dir, second)

            with self.assertRaisesRegex(TrainingDataError, "ordered batch"):
                aggregate_plan064_reviews(
                    [first_dir, second_dir],
                    [second_reviews, first_reviews],
                    aggregate_dir,
                    namespace=namespace,
                )
            with self.assertRaisesRegex(TrainingDataError, "one ordered review"):
                aggregate_plan064_reviews(
                    [first_dir, second_dir],
                    [first_reviews],
                    aggregate_dir,
                    namespace=namespace,
                )
            self.assertFalse((aggregate_dir / "candidate-reviews.jsonl").exists())
            self.assertFalse((aggregate_dir / "pair-reviews.jsonl").exists())

    def test_review_aggregation_rejects_schema_and_unsafe_file(self) -> None:
        compiled = compile_plan064_batch(self._batch())
        with tempfile.TemporaryDirectory() as temporary:
            namespace = self._namespace(temporary)
            batch_dir = namespace / "batch-a"
            aggregate_dir = namespace / "aggregate"
            write_compiled_plan064_batch(batch_dir, compiled, namespace=namespace)
            write_compiled_plan064_batch(
                aggregate_dir,
                aggregate_compiled_plan064_batches(
                    [batch_dir],
                    namespace=namespace,
                ),
                namespace=namespace,
            )
            review_dir = self._write_reviews(namespace, "reviews-a", batch_dir, compiled)
            candidate_path = review_dir / "candidate-reviews.jsonl"
            rows = [json.loads(line) for line in candidate_path.read_text().splitlines()]
            rows[0]["unexpected"] = True
            self._write_jsonl(candidate_path, rows)
            with self.assertRaisesRegex(TrainingDataError, "keys differ"):
                aggregate_plan064_reviews(
                    [batch_dir],
                    [review_dir],
                    aggregate_dir,
                    namespace=namespace,
                )

            rows[0].pop("unexpected")
            self._write_jsonl(candidate_path, rows)
            candidate_path.chmod(0o644)
            with self.assertRaisesRegex(TrainingDataError, "must have mode 600"):
                aggregate_plan064_reviews(
                    [batch_dir],
                    [review_dir],
                    aggregate_dir,
                    namespace=namespace,
                )
            candidate_path.chmod(0o600)
            review_dir.chmod(0o755)
            with self.assertRaisesRegex(TrainingDataError, "must have mode 700"):
                aggregate_plan064_reviews(
                    [batch_dir],
                    [review_dir],
                    aggregate_dir,
                    namespace=namespace,
                )
            self.assertFalse((aggregate_dir / "candidate-reviews.jsonl").exists())
            self.assertFalse((aggregate_dir / "pair-reviews.jsonl").exists())

    def test_review_binding_rejects_missing_and_same_id_content_drift(self) -> None:
        for drift in (
            "missing",
            "scenario",
            "packet",
            "supervision",
            "pair",
            "candidate_review",
            "pair_review",
        ):
            with self.subTest(drift=drift), tempfile.TemporaryDirectory() as temporary:
                namespace = self._namespace(temporary)
                compiled = compile_plan064_batch(self._batch())
                batch_dir = namespace / "batch-a"
                aggregate_dir = namespace / "aggregate"
                write_compiled_plan064_batch(batch_dir, compiled, namespace=namespace)
                write_compiled_plan064_batch(
                    aggregate_dir,
                    aggregate_compiled_plan064_batches(
                        [batch_dir],
                        namespace=namespace,
                    ),
                    namespace=namespace,
                )
                review_dir = self._write_reviews(
                    namespace,
                    "reviews-a",
                    batch_dir,
                    compiled,
                )
                if drift == "missing":
                    (review_dir / "review-binding.json").unlink()
                elif drift == "scenario":
                    path = batch_dir / "scenarios.jsonl"
                    rows = self._read_jsonl(path)
                    rows[0]["blueprint"]["public_state"] += " drift"
                    self._write_jsonl(path, rows)
                elif drift == "packet":
                    path = batch_dir / "packets.jsonl"
                    rows = self._read_jsonl(path)
                    rows[0]["packet"]["candidate"]["summary"] += " drift"
                    self._write_jsonl(path, rows)
                elif drift == "supervision":
                    path = batch_dir / "supervision.jsonl"
                    rows = self._read_jsonl(path)
                    rows[0]["proposed_split"] = "validation"
                    self._write_jsonl(path, rows)
                elif drift == "pair":
                    path = batch_dir / "pairs.jsonl"
                    rows = self._read_jsonl(path)
                    rows[0]["target_dimension"] = "scope_and_signal"
                    self._write_jsonl(path, rows)
                elif drift == "candidate_review":
                    path = review_dir / "candidate-reviews.jsonl"
                    rows = self._read_jsonl(path)
                    rows[0]["rationale"] += " drift"
                    self._write_jsonl(path, rows)
                else:
                    path = review_dir / "pair-reviews.jsonl"
                    rows = self._read_jsonl(path)
                    rows[0]["rationale"] += " drift"
                    self._write_jsonl(path, rows)

                message = "non-symlink file" if drift == "missing" else "ordered batch/review content"
                with self.assertRaisesRegex(TrainingDataError, message):
                    aggregate_plan064_reviews(
                        [batch_dir],
                        [review_dir],
                        aggregate_dir,
                        namespace=namespace,
                    )
                self.assertFalse((aggregate_dir / "candidate-reviews.jsonl").exists())
                self.assertFalse((aggregate_dir / "pair-reviews.jsonl").exists())
                self.assertFalse((aggregate_dir / "review-bindings.json").exists())

    @staticmethod
    def _namespace(temporary: str) -> Path:
        namespace = Path(temporary) / "plan064"
        namespace.mkdir(mode=0o700)
        namespace.chmod(0o700)
        return namespace

    @classmethod
    def _second_batch(cls) -> dict:
        batch = cls._batch()
        batch["batch_id"] = "p064-batch-useful-b"
        scenario = batch["scenarios"][0]
        scenario["scenario_id"] = "p064-useful-validation-02"
        scenario["source_group"] = "p064-source-useful-validation-02"
        scenario["scenario_group"] = "p064-useful-validation-02"
        scenario["template_group"] = "p064-template-useful-b"
        scenario["proposed_split"] = "validation"
        return batch

    @classmethod
    def _write_reviews(
        cls,
        namespace: Path,
        name: str,
        batch_dir: Path,
        compiled,
    ) -> Path:
        review_dir = namespace / name
        review_dir.mkdir(mode=0o700)
        review_dir.chmod(0o700)
        labels = {
            row["candidate_id"]: row
            for row in compiled.supervision
        }
        identity = {
            "model": "gpt-5.6-sol",
            "reasoning_effort": "xhigh",
            "role": "independent_plan064_reviewer",
            "prompt_sha256": "b" * 64,
            "date": "2026-08-24",
            "session_identity": f"{name}-session",
        }
        candidate_reviews = [
            {
                "schema_version": 1,
                "candidate_id": row["candidate_id"],
                "decision": "accept",
                "independent_label": labels[row["candidate_id"]]["binary_label"],
                "failed_hard_dimensions": labels[row["candidate_id"]]["defects"],
                "rationale": "The public candidate independently matches the declared hard dimensions.",
                "reviewer_identity": identity,
            }
            for row in compiled.packets
        ]
        pair_reviews = [
            {
                "schema_version": 1,
                "pair_id": row["pair_id"],
                "decision": "accept",
                "direction_confirmed": True,
                "context_equal": True,
                "omission_equal": True,
                "atomicity_confirmed": row["kind"] == "boundary",
                "soft_only_confirmed": row["kind"] == "within_pass",
                "rationale": "The pair direction and shared public context are independently confirmed.",
                "reviewer_identity": identity,
            }
            for row in compiled.pairs
        ]
        cls._write_jsonl(review_dir / "candidate-reviews.jsonl", candidate_reviews)
        cls._write_jsonl(review_dir / "pair-reviews.jsonl", pair_reviews)
        create_plan064_review_binding(
            batch_dir,
            review_dir,
            namespace=namespace,
        )
        return review_dir

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict]) -> None:
        path.write_text(
            "".join(
                json.dumps(
                    row,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )
        path.chmod(0o600)

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text().splitlines()]

    @staticmethod
    def _batch() -> dict:
        return {
            "schema": BATCH_SCHEMA,
            "batch_id": "p064-batch-useful-a",
            "generator_identity": {
                "model": "gpt-5.6-sol",
                "reasoning_effort": "xhigh",
                "role": "direct_plan064_generator",
                "prompt_sha256": "a" * 64,
                "date": "2026-08-23",
                "session_identity": "plan064-batch-test",
            },
            "scenarios": [
                {
                    "scenario_id": "p064-useful-train-01",
                    "source_group": "p064-source-useful-train-01",
                    "scenario_group": "p064-useful-train-01",
                    "template_group": "p064-template-useful-a",
                    "publication_class": "existing_event_incomplete",
                    "completion_state": "incomplete",
                    "actor_role": "root",
                    "style": "formal",
                    "length_bucket": "short",
                    "unicode": False,
                    "slices": [
                        "useful_state_transfer",
                        "existing_event_incomplete",
                        "continuity_available",
                        "evidence_present",
                    ],
                    "blueprint": {
                        "local_scope_title": "Cache key repair",
                        "public_state": "The key includes the revision; the remaining reload edge is still open.",
                        "continuity_state": "available",
                        "evidence_appearance": "present",
                        "candidate_brief": "Publish the decision-relevant result and remaining edge.",
                    },
                    "proposed_split": "train",
                    "continuity": {
                        "state": "available",
                        "source_team_revision": 64,
                        "freshness": "current",
                        "coverage": {"state": "complete"},
                        "prior_publications": [
                            {
                                "summary": "The reload bug is reproducible.",
                                "handoff": "Include the revision in the cache key.",
                                "evidence": {
                                    "fact_references": {
                                        "state": "present",
                                        "visible_count": 2,
                                        "count_omitted": False,
                                    },
                                    "observation_availability": "unknown",
                                },
                            }
                        ],
                    },
                    "candidates": [
                        {
                            "id_suffix": "qplus",
                            "label": "PASS",
                            "summary": "The cache key now includes the revision; three reload checks read the new value, while the stale-entry edge remains open.",
                            "handoff": "Exercise the stale-entry edge before closing the task.",
                            "defects": [],
                        },
                        {
                            "id_suffix": "qminus",
                            "label": "REWRITE",
                            "summary": "The cache work made good progress and the focused checks were useful.",
                            "handoff": "Continue with the remaining work.",
                            "defects": ["useful_state_transfer"],
                        },
                    ],
                    "pairs": [
                        {
                            "id_suffix": "boundary",
                            "kind": "boundary",
                            "preferred": "qplus",
                            "dispreferred": "qminus",
                            "target_dimension": "useful_state_transfer",
                            "soft_preference": None,
                        }
                    ],
                }
            ],
        }


if __name__ == "__main__":
    unittest.main()
