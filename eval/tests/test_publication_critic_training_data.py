import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.contract import load_fixed_input_contract  # noqa: E402
from rondo_eval.publication_critic.tokenization import (  # noqa: E402
    EXPECTED_CHAT_ADDED_TOKEN_IDS,
    ExactTokenizer,
)
from rondo_eval.publication_critic.training_data import (  # noqa: E402
    DatasetConsumer,
    TrainingDataError,
    build_freeze_manifest,
    build_group_components,
    build_memberships,
    build_train_only_smoke_bundle,
    census_packets,
    deterministic_grouped_stratified_split,
    find_near_duplicate_edges,
    model_visible_candidate_length_shortcut_findings,
    model_visible_text_shortcut_findings,
    shortcut_contingencies,
    validate_dataset,
    validate_group_closure,
    validate_packet_row,
    validate_scenario_row,
    validate_supervision_row,
    validate_train_only_smoke_bundle,
    variable_text_similarity,
    verify_freeze_manifest,
)
from rondo_eval.publication_critic.training_data.input_identity import (  # noqa: E402
    load_plan054_training_input,
)


IDENTITY = {
    "model": "gpt-5.6-sol",
    "reasoning_effort": "xhigh",
    "role": "independent reviewer",
    "prompt_sha256": "a" * 64,
    "date": "2026-08-23",
    "session_identity": "test-session",
}


class _CharacterTokenizer:
    pad_token_id = 151654
    bos_token_id = None
    eos_token_id = 151645
    all_special_ids = (151644, 151645, 151654)
    padding_side = "left"

    @staticmethod
    def get_added_vocab() -> dict[str, int]:
        return {
            "<|im_start|>": 151644,
            "<|im_end|>": 151645,
            "<|assistant|>": 151667,
            "<|analysis|>": 151668,
            "<|pad|>": 151654,
        }

    @staticmethod
    def apply_chat_template(
        messages: list[dict[str, str]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
    ) -> str:
        if tokenize or add_generation_prompt:
            raise AssertionError("wrong template options")
        return "".join(f"ROLE_{row['role']}\n{row['content']}\n" for row in messages)

    @staticmethod
    def __call__(
        rendered: str,
        *,
        add_special_tokens: bool,
        truncation: bool,
        return_attention_mask: bool,
        return_offsets_mapping: bool,
    ) -> dict[str, list]:
        if add_special_tokens or truncation or not return_attention_mask or not return_offsets_mapping:
            raise AssertionError("wrong tokenizer options")
        ids = [*EXPECTED_CHAT_ADDED_TOKEN_IDS, *range(200_000, 200_000 + len(rendered))]
        return {
            "input_ids": ids,
            "attention_mask": [1] * len(ids),
            "offset_mapping": [
                *((0, 0) for _ in EXPECTED_CHAT_ADDED_TOKEN_IDS),
                *((index, index + 1) for index in range(len(rendered))),
            ],
        }


class PublicationCriticTrainingDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        first = json.loads(
            (REPO_ROOT / "eval/fixtures/publication-critic-v1/packets.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()[0]
        )
        cls.base_packet = first["packet"]

    def test_packet_adapter_reuses_strict_plan054_validation(self) -> None:
        row = self._packet("candidate-a", "A useful state transfer.")
        validate_packet_row(row)
        row["packet"]["binary_label"] = "PASS"
        with self.assertRaisesRegex(TrainingDataError, "supervision keys"):
            validate_packet_row(row)

    def test_raw_supervision_allows_only_pending_null_reviewer(self) -> None:
        row = self._supervision("candidate-a", "PASS", split=None, status="pending")
        row["reviewer_identity"] = None
        validate_supervision_row(row)
        row["review_status"] = "accept"
        with self.assertRaisesRegex(TrainingDataError, "only pending"):
            validate_supervision_row(row)

    def test_scenario_blueprint_is_public_and_consistent(self) -> None:
        row = {
            "schema_version": 1,
            "scenario_id": "scenario-a",
            "source_id": "plan059-synthetic-product-shaped-v1",
            "source_group": "source-a",
            "scenario_group": "scenario-a",
            "template_group": "template-a",
            "publication_class": "new_event_completed",
            "completion_state": "completed",
            "actor_role": "root",
            "style": "formal",
            "length_bucket": "medium",
            "unicode": False,
            "slices": [
                "contains_long_candidate",
                "continuity_not_applicable",
                "evidence_not_applicable",
            ],
            "blueprint": {
                "local_scope_title": "Public scenario",
                "public_state": "The bounded task completed.",
                "continuity_state": "not_applicable",
                "evidence_appearance": "not_applicable",
                "candidate_brief": "Publish the useful final state.",
            },
        }
        validate_scenario_row(
            row,
            allowed_source_ids={"plan059-synthetic-product-shaped-v1"},
        )
        row["blueprint"]["continuity_state"] = "available"
        with self.assertRaisesRegex(TrainingDataError, "conflicts"):
            validate_scenario_row(row)

    def test_final_dataset_closes_binary_pair_and_review_invariants(self) -> None:
        packets, supervision, pairs, candidate_reviews, pair_reviews = self._complete_rows()
        validate_dataset(
            packets,
            supervision,
            pairs,
            candidate_reviews=candidate_reviews,
            pair_reviews=pair_reviews,
            dropped_oldest_publications={row["candidate_id"]: 0 for row in packets},
        )
        broken = copy.deepcopy(packets)
        broken[1]["packet"]["local_scope"]["title"] = "Changed context"
        with self.assertRaisesRegex(TrainingDataError, "non-candidate model-visible context"):
            validate_dataset(
                broken,
                supervision,
                pairs,
                candidate_reviews=candidate_reviews,
                pair_reviews=pair_reviews,
                dropped_oldest_publications={row["candidate_id"]: 0 for row in broken},
            )

    def test_group_closure_and_split_search_are_deterministic(self) -> None:
        rows = [
            self._supervision("a", "PASS", scenario="s1", source="src1", template="t1"),
            self._supervision("b", "REWRITE", scenario="s1", source="src1", template="t1"),
            self._supervision("c", "PASS", scenario="s2", source="src2", template="t2"),
            self._supervision("d", "REWRITE", scenario="s3", source="src3", template="t3"),
        ]
        pair = self._pair("p1", "boundary", "s1", "a", "b")
        components = build_group_components(rows, [pair])
        lock = self._small_design_lock()
        first = deterministic_grouped_stratified_split(components, rows, [pair], lock)
        second = deterministic_grouped_stratified_split(components, rows, [pair], lock)
        self.assertEqual(first, second)
        self.assertEqual(first["a"], first["b"])
        validate_group_closure(components, first)

    def test_exact_and_near_duplicate_screen_uses_variable_packet_text(self) -> None:
        left = self._packet("left", "A complete and useful state transfer.")
        right = self._packet("right", "A complete and useful state transfer!")
        self.assertGreater(variable_text_similarity(left["packet"], right["packet"]), 0.9)
        edges = find_near_duplicate_edges([left, right], threshold=0.9)
        self.assertEqual([(edge.left_candidate_id, edge.right_candidate_id) for edge in edges], [("left", "right")])

    def test_shortcut_report_skips_label_axis_and_derives_canonical_slices(self) -> None:
        rows = [
            self._supervision("a", "PASS"),
            self._supervision("b", "REWRITE"),
        ]
        for row in rows:
            row["slices"] = ["unit_test", "continuity_available", "evidence_present"]
        report = shortcut_contingencies(
            rows,
            ["binary_label", "continuity_state", "evidence_appearance"],
        )
        self.assertNotIn("binary_label", report)
        self.assertEqual(report["continuity_state"]["available"], {"PASS": 1, "REWRITE": 1})
        self.assertEqual(report["evidence_appearance"]["present"], {"PASS": 1, "REWRITE": 1})

    def test_model_visible_text_shortcut_requires_support_splits_and_one_label(self) -> None:
        packets, supervision = self._text_shortcut_rows(
            labels=["PASS", "PASS", "PASS", "PASS"],
            splits=["train", "train", "validation", "unseen_test"],
        )
        findings = model_visible_text_shortcut_findings(packets, supervision)
        marker = next(finding for finding in findings if finding["fragment"] == "mark")
        self.assertEqual(
            marker,
            {
                "fragment": "mark",
                "support": 4,
                "label": "PASS",
                "splits": ["train", "unseen_test", "validation"],
                "candidate_ids": ["shortcut-0", "shortcut-1", "shortcut-2", "shortcut-3"],
            },
        )

        _packets, mixed_labels = self._text_shortcut_rows(
            labels=["PASS", "PASS", "REWRITE", "REWRITE"],
            splits=["train", "train", "validation", "unseen_test"],
        )
        self.assertNotIn(
            "mark",
            {finding["fragment"] for finding in model_visible_text_shortcut_findings(packets, mixed_labels)},
        )

        self.assertNotIn(
            "mark",
            {
                finding["fragment"]
                for finding in model_visible_text_shortcut_findings(packets[:3], supervision[:3])
            },
        )
        one_split = [dict(row, proposed_split="train") for row in supervision]
        self.assertNotIn(
            "mark",
            {finding["fragment"] for finding in model_visible_text_shortcut_findings(packets, one_split)},
        )

    def test_candidate_length_shortcut_requires_threshold_support_splits_and_one_label(self) -> None:
        supervision = [
            self._supervision(f"length-{index}", "REWRITE" if index >= 3 else "PASS")
            for index in range(9)
        ]
        for index, row in enumerate(supervision):
            row["proposed_split"] = ("train", "validation", "unseen_test")[index % 3]
        census = [
            {"candidate_id": f"length-{index}", "buckets": {"candidate": value}}
            for index, value in enumerate((20, 21, 22, 80, 81, 82, 83, 84, 85))
        ]
        findings = model_visible_candidate_length_shortcut_findings(census, supervision)
        finding = next(
            finding
            for finding in findings
            if finding["direction"] == "at_least" and finding["threshold"] == 80
        )
        self.assertEqual(finding["support"], 6)
        self.assertEqual(finding["label"], "REWRITE")
        self.assertEqual(finding["splits"], ["train", "unseen_test", "validation"])

        mixed = [dict(row) for row in supervision]
        mixed[-1]["binary_label"] = "PASS"
        self.assertFalse(model_visible_candidate_length_shortcut_findings(census, mixed))

        one_split = [dict(row, proposed_split="train") for row in supervision]
        self.assertFalse(model_visible_candidate_length_shortcut_findings(census, one_split))

    def test_freeze_hashes_fail_closed_after_file_drift(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "packets.jsonl").write_text("{}\n", encoding="utf-8")
            manifest = build_freeze_manifest(
                root,
                ["packets.jsonl"],
                dataset_revision="v1",
                input_identity={"revision": "exact"},
                design_lock_sha256="b" * 64,
                generation_commit="c" * 40,
                contracts={"rows": "v1"},
                statistics={"candidates": 1},
            )
            verify_freeze_manifest(root, manifest, expected_input_identity={"revision": "exact"})
            (root / "packets.jsonl").write_text("{\"drift\":true}\n", encoding="utf-8")
            with self.assertRaisesRegex(TrainingDataError, "identity drifted"):
                verify_freeze_manifest(
                    root,
                    manifest,
                    expected_input_identity={"revision": "exact"},
                )

    def test_consumer_memberships_bundle_and_default_holdout_denial(self) -> None:
        packets, supervision, pairs, _candidate_reviews, _pair_reviews = self._complete_rows()
        membership = build_memberships(supervision, pairs, dataset_revision="v1")
        consumer = DatasetConsumer.from_rows(packets, supervision, pairs, membership)
        self.assertEqual(len(consumer.stage("C1")["binary"]), 4)
        self.assertEqual([pair["kind"] for pair in consumer.stage("C2")["pairs"]], ["boundary"])
        self.assertEqual(
            {pair["kind"] for pair in consumer.stage("C3")["pairs"]},
            {"boundary", "within_pass"},
        )
        with self.assertRaisesRegex(TrainingDataError, "explicit evaluation mode"):
            consumer.evaluation_split("unseen_test")
        bundle = build_train_only_smoke_bundle(
            packets,
            supervision,
            pairs,
            dataset_revision="v1",
            source_hashes={"packets.jsonl": "d" * 64},
        )
        self.assertEqual({row["proposed_split"] for row in bundle["supervision"]}, {"train"})
        validate_train_only_smoke_bundle(bundle)

    def test_frozen_directory_consumer_verifies_hashes_before_loading(self) -> None:
        packets, supervision, pairs, _candidate_reviews, _pair_reviews = self._complete_rows()
        membership = build_memberships(supervision, pairs, dataset_revision="v1")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name, rows in (
                ("packets.jsonl", packets),
                ("supervision.jsonl", supervision),
                ("pairs.jsonl", pairs),
            ):
                root.joinpath(name).write_text(
                    "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows),
                    encoding="utf-8",
                )
            root.joinpath("membership.json").write_text(json.dumps(membership), encoding="utf-8")
            manifest = build_freeze_manifest(
                root,
                ["packets.jsonl", "supervision.jsonl", "pairs.jsonl", "membership.json"],
                dataset_revision="v1",
                input_identity=load_plan054_training_input(REPO_ROOT).input_identity,
                design_lock_sha256="b" * 64,
                generation_commit="c" * 40,
                contracts={"rows": "v1"},
                statistics={"candidates": 4},
            )
            root.joinpath("manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
            consumer = DatasetConsumer.from_frozen_directory(
                root,
            )
            self.assertEqual(len(consumer.stage("C3")["pairs"]), 2)

    def test_exact_token_census_reconciles_every_packet(self) -> None:
        packets = [self._packet("candidate-a", "A useful state transfer.")]
        tokenizer = ExactTokenizer(_CharacterTokenizer())
        fixed = load_fixed_input_contract(REPO_ROOT)
        rows, summary = census_packets(packets, tokenizer, fixed.rubric)
        self.assertEqual(summary["candidate_count"], 1)
        self.assertEqual(summary["token_total"], rows[0]["token_count"])
        self.assertEqual(sum(rows[0]["buckets"].values()), rows[0]["token_count"])

    def _packet(self, candidate_id: str, summary: str) -> dict:
        packet = copy.deepcopy(self.base_packet)
        packet["candidate"]["summary"] = summary
        return {"schema_version": 1, "candidate_id": candidate_id, "packet": packet}

    @staticmethod
    def _supervision(
        candidate_id: str,
        label: str,
        *,
        split: str | None = "train",
        status: str = "accept",
        scenario: str = "scenario-1",
        source: str = "source-1",
        template: str = "template-1",
    ) -> dict:
        defects = [] if label == "PASS" else ["internal_consistency"]
        return {
            "schema_version": 1,
            "candidate_id": candidate_id,
            "scenario_id": scenario,
            "source_group": source,
            "scenario_group": scenario,
            "template_group": template,
            "proposed_split": split,
            "binary_label": label,
            "publication_class": "new_event_completed",
            "completion_state": "completed",
            "hard_focus": None if label == "PASS" else "internal_consistency",
            "defects": defects,
            "slices": ["unit_test", "continuity_not_applicable", "evidence_not_applicable"],
            "actor_role": "root",
            "style": "formal",
            "length_bucket": "short",
            "unicode": False,
            "generator_identity": IDENTITY,
            "reviewer_identity": IDENTITY,
            "review_status": status,
        }

    @staticmethod
    def _pair(pair_id: str, kind: str, scenario: str, preferred: str, dispreferred: str) -> dict:
        return {
            "schema_version": 1,
            "pair_id": pair_id,
            "kind": kind,
            "scenario_id": scenario,
            "preferred_candidate_id": preferred,
            "dispreferred_candidate_id": dispreferred,
            "target_dimension": "internal_consistency" if kind == "boundary" else None,
            "soft_preference": None if kind == "boundary" else "more direct state transfer",
            "review_status": "accept",
        }

    def _complete_rows(self) -> tuple[list[dict], list[dict], list[dict], list[dict], list[dict]]:
        packets = [
            self._packet("b-pass", "A complete and internally consistent state transfer."),
            self._packet("b-rewrite", "Completed, but also not completed."),
            self._packet("w-best", "The task completed and the verified result is ready."),
            self._packet("w-less", "The verified result is ready because the task completed."),
        ]
        supervision = [
            self._supervision("b-pass", "PASS", scenario="boundary", source="source-b", template="template-b"),
            self._supervision("b-rewrite", "REWRITE", scenario="boundary", source="source-b", template="template-b"),
            self._supervision("w-best", "PASS", scenario="within", source="source-w", template="template-w"),
            self._supervision("w-less", "PASS", scenario="within", source="source-w", template="template-w"),
        ]
        pairs = [
            self._pair("boundary-pair", "boundary", "boundary", "b-pass", "b-rewrite"),
            self._pair("within-pair", "within_pass", "within", "w-best", "w-less"),
        ]
        candidate_reviews = [
            {
                "schema_version": 1,
                "candidate_id": row["candidate_id"],
                "decision": "accept",
                "independent_label": row["binary_label"],
                "failed_hard_dimensions": list(row["defects"]),
                "rationale": "Independent unit-test review.",
                "reviewer_identity": IDENTITY,
            }
            for row in supervision
        ]
        pair_reviews = [
            {
                "schema_version": 1,
                "pair_id": pair["pair_id"],
                "decision": "accept",
                "direction_confirmed": True,
                "context_equal": True,
                "omission_equal": True,
                "atomicity_confirmed": pair["kind"] == "boundary",
                "soft_only_confirmed": pair["kind"] == "within_pass",
                "rationale": "Independent unit-test pair review.",
                "reviewer_identity": IDENTITY,
            }
            for pair in pairs
        ]
        return packets, supervision, pairs, candidate_reviews, pair_reviews

    def _text_shortcut_rows(
        self,
        *,
        labels: list[str],
        splits: list[str],
    ) -> tuple[list[dict], list[dict]]:
        packets: list[dict] = []
        supervision: list[dict] = []
        spellings = ["FIXED   MARKER", "fixed marker", "ＦＩＸＥＤ marker", "Fixed Marker"]
        for index, (label, split) in enumerate(zip(labels, splits, strict=True)):
            candidate_id = f"shortcut-{index}"
            packet = self._packet(
                candidate_id,
                f"Unique-{index} {spellings[index]} outcome-{index}.",
            )
            packet["packet"]["candidate"]["handoff"] = f"Unique next step {index}."
            packets.append(packet)
            supervision.append(
                self._supervision(
                    candidate_id,
                    label,
                    split=split,
                    scenario=f"shortcut-scenario-{index}",
                    source=f"shortcut-source-{index}",
                    template=f"shortcut-template-{index}",
                )
            )
        return packets, supervision

    @staticmethod
    def _small_design_lock() -> dict:
        return {
            "split_contract": {
                "names": ["train", "validation", "unseen_test"],
                "target_candidate_ratios": {"train": 0.5, "validation": 0.25, "unseen_test": 0.25},
                "candidate_ratio_tolerance": 0.26,
                "seed": "unit-test",
                "search_attempts": 500,
            },
            "coverage_minimums": {
                "formal_total_candidates": 4,
                "split_candidates": {"train": 2, "validation": 1, "unseen_test": 1},
                "split_binary_labels": {
                    "train": {"PASS": 1, "REWRITE": 1},
                    "validation": {"PASS": 0, "REWRITE": 0},
                    "unseen_test": {"PASS": 0, "REWRITE": 0},
                },
                "publication_classes": {
                    "values": [],
                    "minimum_scenario_groups_per_value_global": 0,
                    "minimum_scenario_groups_per_value_per_split": 0,
                },
                "boundary_hard_dimensions": {
                    "values": [],
                    "minimum_pairs_per_value_global": 0,
                    "minimum_pairs_per_value_per_split": 0,
                },
                "natural_mixed_binary_candidates_per_split": 0,
                "within_pass_pairs_per_split": 0,
                "roles_per_split": [],
                "styles_per_split": [],
                "unicode_scenario_groups_global": 0,
                "long_input_candidates_per_split": 0,
            },
        }


if __name__ == "__main__":
    unittest.main()
