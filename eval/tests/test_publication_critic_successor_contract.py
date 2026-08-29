import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.successor_data import (  # noqa: E402
    CANDIDATE_SCHEMA,
    MANIFEST_SCHEMA,
    PAIR_SCHEMA,
    SuccessorDataError,
    SuccessorRelease,
    SuccessorSplit,
    validate_candidate_row,
    validate_split,
)
from rondo_eval.publication_critic.successor_task import (  # noqa: E402
    DIMENSION_CLASSES,
    FORBIDDEN_MODEL_INPUT_FIELDS,
    HARD_DIMENSIONS,
    STRUCTURED_OUTPUT_SCHEMA,
    SuccessorTaskError,
    decode_structured_output as decode_zero_margin_diagnostic,
    derive_loss_targets,
    derive_pair_loss_targets,
    derive_quality,
    derive_verdict,
    evaluate_predictions,
    evaluate_pair_predictions,
    load_task_projection,
    task_content_sha256,
    validate_labels,
    validate_pair_labels,
    validate_structured_output,
)


class PublicationCriticSuccessorContractTests(unittest.TestCase):
    def test_authority_projection_and_machine_schemas_are_versioned(self) -> None:
        projection = load_task_projection(REPO_ROOT)
        self.assertEqual(
            projection["authority"],
            {
                "name": "rondo-publication-critic-task",
                "version": "v2",
                "path": "doc/rondo-multi-publication-critic-task-contract-v2.md",
            },
        )
        self.assertEqual(projection["dimensions"]["order"], list(HARD_DIMENSIONS))
        self.assertEqual(projection["output"]["backbone_forward_count"], 1)
        self.assertEqual(projection["output"]["head_count"], 5)
        self.assertIsNone(projection["output"]["global_quality_head"])
        self.assertRegex(task_content_sha256(REPO_ROOT), r"^[0-9a-f]{64}$")

        output_schema = self._load_json(
            REPO_ROOT
            / "eval/templates/publication-critic/successor-output-schema-v1.json"
        )
        formal_decision = self._load_json(
            REPO_ROOT
            / "eval/templates/publication-critic/formal-decision-projection-v1.json"
        )
        release_contract = self._load_json(
            REPO_ROOT
            / "eval/templates/publication-critic/successor-release-contract-v1.json"
        )
        self.assertEqual(output_schema["$id"], STRUCTURED_OUTPUT_SCHEMA)
        self.assertEqual(
            output_schema["x-rondo-runtime-validator"],
            "eval/rondo_eval/publication_critic/successor_task.py"
            "#validate_structured_output",
        )
        self.assertEqual(
            output_schema["x-rondo-runtime-decoder"],
            "eval/rondo_eval/publication_critic/successor_task.py"
            "#decode_structured_output",
        )
        self.assertEqual(
            formal_decision["raw_output"]["schema_sha256"],
            hashlib.sha256(
                (
                    REPO_ROOT / "eval/templates/publication-critic/"
                    "successor-output-schema-v1.json"
                ).read_bytes()
            ).hexdigest(),
        )
        self.assertEqual(
            formal_decision["raw_output"]["historical_decoder"],
            output_schema["x-rondo-runtime-decoder"],
        )
        self.assertEqual(
            formal_decision["raw_output"]["historical_decoder_role"],
            "zero_margin_diagnostic_only",
        )
        self.assertEqual(
            formal_decision["raw_output"]["formal_decision_use"],
            "forbidden",
        )
        self.assertEqual(
            formal_decision["formal_decision"]["decoder"],
            "eval/rondo_eval/publication_critic/qualification.py#"
            "decode_with_decision_config",
        )
        self.assertEqual(release_contract["kind"], "rondo-contract-projection")
        self.assertNotIn("$schema", release_contract)
        self.assertEqual(
            release_contract["authority"],
            "rondo-publication-critic-task@v2",
        )
        self.assertEqual(
            release_contract["manifest"]["consumer_access"]["test"],
            "no training or selection entrypoint",
        )
        self.assertEqual(
            projection["input"]["forbidden_model_input_fields"],
            list(FORBIDDEN_MODEL_INPUT_FIELDS),
        )
        self.assertEqual(
            release_contract["candidate"]["forbidden_model_input_fields"],
            list(FORBIDDEN_MODEL_INPUT_FIELDS),
        )

    def test_non_compensating_gate_na_and_scalar_projection(self) -> None:
        labels = self._labels()
        labels["honest_uncertainty"] = "FAIL"
        satisfaction = {dimension: 1.0 for dimension in HARD_DIMENSIONS}
        satisfaction["honest_uncertainty"] = 0.2
        self.assertEqual(derive_verdict(labels), "REWRITE")
        self.assertEqual(derive_quality(labels, satisfaction), 0.2)

        completed = self._labels(continuity="N/A")
        satisfaction["honest_uncertainty"] = 0.8
        satisfaction["conditional_continuity"] = 0.0
        self.assertEqual(derive_verdict(completed), "PASS")
        self.assertEqual(derive_quality(completed, satisfaction), 0.8)

        invalid = self._labels()
        invalid["scope_and_signal"] = "N/A"
        with self.assertRaisesRegex(SuccessorTaskError, "invalid scope_and_signal"):
            validate_labels(invalid)

    def test_output_is_one_forward_and_exactly_five_heads(self) -> None:
        output = self._structured_output()
        validate_structured_output(output)
        decoded = decode_zero_margin_diagnostic(output)
        self.assertEqual(decoded, (self._labels(continuity="N/A"),))

        for mutation, message in (
            (lambda value: value.update({"global_quality": [[0.9]]}), "keys differ"),
            (
                lambda value: value["heads"].pop("internal_consistency"),
                "heads keys differ",
            ),
            (
                lambda value: value.update({"backbone_forward_count": 5}),
                "backbone_forward_count",
            ),
            (
                lambda value: value["heads"]["useful_state_transfer"].update(
                    {"logits": [[0.9]]}
                ),
                "width differs",
            ),
        ):
            broken = copy.deepcopy(output)
            mutation(broken)
            with self.assertRaisesRegex(SuccessorTaskError, message):
                validate_structured_output(broken)

        with self.assertRaisesRegex(SuccessorTaskError, "keys differ"):
            validate_structured_output({"logits": [[0.9]]})

        all_tied = self._structured_output()
        for head in all_tied["heads"].values():
            head["logits"] = [[0.0] * len(head["classes"])]
        tied_labels = decode_zero_margin_diagnostic(all_tied)[0]
        self.assertEqual(set(tied_labels.values()), {"FAIL"})
        self.assertEqual(derive_verdict(tied_labels), "REWRITE")

        local_tie = self._structured_output()
        local_tie["heads"]["useful_state_transfer"]["logits"] = [[0.5, 0.5]]
        local_labels = decode_zero_margin_diagnostic(local_tie)[0]
        self.assertEqual(local_labels["useful_state_transfer"], "FAIL")
        self.assertEqual(local_labels["conditional_continuity"], "N/A")
        self.assertEqual(derive_verdict(local_labels), "REWRITE")

    def test_boundary_and_soft_only_pairs_require_absolute_closure(self) -> None:
        q_plus = self._labels()
        q_minus = self._labels()
        q_minus["scope_and_signal"] = "FAIL"
        validate_pair_labels(
            "boundary",
            q_plus,
            q_minus,
            target_dimension="scope_and_signal",
        )
        with self.assertRaisesRegex(SuccessorTaskError, "non-target labels"):
            broken = copy.deepcopy(q_minus)
            broken["honest_uncertainty"] = "FAIL"
            validate_pair_labels(
                "boundary",
                q_plus,
                broken,
                target_dimension="scope_and_signal",
            )

        left = self._labels(continuity="N/A")
        right = copy.deepcopy(left)
        validate_pair_labels(
            "soft_only_invariance",
            left,
            right,
            target_dimension=None,
        )
        right["conditional_continuity"] = "PASS"
        with self.assertRaisesRegex(SuccessorTaskError, "labels must be identical"):
            validate_pair_labels(
                "soft_only_invariance",
                left,
                right,
                target_dimension=None,
            )

    def test_loss_targets_are_complete_dimensions_plus_derived_gate(self) -> None:
        completed = self._labels(continuity="N/A")
        failed = self._labels()
        failed["honest_uncertainty"] = "FAIL"
        targets = derive_loss_targets([completed, failed])
        self.assertEqual(
            set(targets[0]),
            {"dimension_labels", "applicable_dimensions", "derived_gate_label"},
        )
        self.assertEqual(targets[0]["derived_gate_label"], "PASS")
        self.assertNotIn(
            "conditional_continuity",
            targets[0]["applicable_dimensions"],
        )
        self.assertEqual(targets[1]["derived_gate_label"], "REWRITE")
        self.assertNotIn("global_quality_target", targets[1])

        boundary_right = self._labels()
        boundary_right["honest_uncertainty"] = "FAIL"
        pair_targets = derive_pair_loss_targets(
            [
                {
                    "pair_id": "boundary-loss-a",
                    "kind": "boundary",
                    "left_labels": self._labels(),
                    "right_labels": boundary_right,
                    "target_dimension": "honest_uncertainty",
                }
            ]
        )
        boundary_target = pair_targets[0]
        self.assertEqual(boundary_target["left_gate_label"], "PASS")
        self.assertEqual(boundary_target["right_gate_label"], "REWRITE")
        self.assertEqual(
            boundary_target["constraints"]["target_head"],
            {
                "dimension": "honest_uncertainty",
                "left_label": "PASS",
                "right_label": "FAIL",
                "objective": "finite_margin",
            },
        )
        self.assertNotIn(
            "honest_uncertainty",
            boundary_target["constraints"]["prediction_invariance_dimensions"],
        )
        self.assertEqual(
            len(boundary_target["constraints"]["prediction_invariance_dimensions"]),
            4,
        )

    def test_evaluation_reports_per_head_applicability_and_gate_errors(self) -> None:
        pass_gold = self._labels(continuity="N/A")
        rewrite_gold = self._labels()
        rewrite_gold["useful_state_transfer"] = "FAIL"
        false_rewrite = copy.deepcopy(pass_gold)
        false_rewrite["internal_consistency"] = "FAIL"
        false_pass = self._labels()
        summary = evaluate_predictions(
            [pass_gold, rewrite_gold],
            [false_rewrite, false_pass],
        )
        self.assertEqual(summary["gate"]["false_pass"], 1)
        self.assertEqual(summary["gate"]["false_rewrite"], 1)
        self.assertEqual(
            summary["per_dimension"]["conditional_continuity"]["gold_na"],
            1,
        )
        self.assertEqual(
            summary["per_dimension"]["conditional_continuity"]["applicable_total"],
            1,
        )

        boundary_plus = self._labels()
        boundary_minus = self._labels()
        boundary_minus["useful_state_transfer"] = "FAIL"
        pair_summary = evaluate_pair_predictions(
            [
                {
                    "pair_id": "boundary-eval-a",
                    "kind": "boundary",
                    "left_labels": boundary_plus,
                    "right_labels": boundary_minus,
                    "target_dimension": "useful_state_transfer",
                },
                {
                    "pair_id": "invariance-eval-a",
                    "kind": "soft_only_invariance",
                    "left_labels": pass_gold,
                    "right_labels": pass_gold,
                    "target_dimension": None,
                },
            ]
        )
        self.assertEqual(
            pair_summary["summary"]["boundary"],
            {"total": 1, "closed": 1},
        )
        self.assertEqual(
            pair_summary["summary"]["soft_only_invariance"],
            {"total": 1, "closed": 1},
        )
        self.assertEqual(
            pair_summary["pairs"],
            [
                {
                    "pair_id": "boundary-eval-a",
                    "kind": "boundary",
                    "closed": True,
                    "reason": None,
                },
                {
                    "pair_id": "invariance-eval-a",
                    "kind": "soft_only_invariance",
                    "closed": True,
                    "reason": None,
                },
            ],
        )

        invalid_right = self._labels()
        invalid_right["useful_state_transfer"] = "FAIL"
        invalid_right["scope_and_signal"] = "FAIL"
        failed_report = evaluate_pair_predictions(
            [
                {
                    "pair_id": "boundary-eval-failed",
                    "kind": "boundary",
                    "left_labels": self._labels(),
                    "right_labels": invalid_right,
                    "target_dimension": "useful_state_transfer",
                }
            ]
        )
        self.assertFalse(failed_report["pairs"][0]["closed"])
        self.assertIn("non-target labels", failed_report["pairs"][0]["reason"])

    def test_candidate_schema_uses_visible_applicability_and_rejects_hidden_state(
        self,
    ) -> None:
        completed = self._candidate("complete", self._labels(continuity="N/A"))
        validate_candidate_row(completed, repo_root=REPO_ROOT)

        broken = copy.deepcopy(completed)
        broken["continuity_label_basis"]["type"] = (
            "model_visible_unfinished_or_not_closed"
        )
        with self.assertRaisesRegex(SuccessorDataError, "basis.type"):
            validate_candidate_row(broken, repo_root=REPO_ROOT)

        unfinished = self._candidate(
            "unfinished",
            self._labels(),
            summary="Work is still in progress; the integration check is next.",
        )
        validate_candidate_row(unfinished, repo_root=REPO_ROOT)

        conflict_labels = self._labels()
        conflict_labels["internal_consistency"] = "FAIL"
        conflicted = self._candidate(
            "conflicted",
            conflict_labels,
            summary="Work is complete, but investigation is still in progress.",
        )
        validate_candidate_row(conflicted, repo_root=REPO_ROOT)
        self.assertEqual(derive_verdict(conflict_labels), "REWRITE")

        absent_quote = copy.deepcopy(completed)
        absent_quote["continuity_label_basis"]["quote"] = "not in the candidate"
        with self.assertRaisesRegex(SuccessorDataError, "quote is absent"):
            validate_candidate_row(absent_quote, repo_root=REPO_ROOT)

        wrong_field = copy.deepcopy(completed)
        wrong_field["continuity_label_basis"]["field"] = "candidate.handoff"
        with self.assertRaisesRegex(SuccessorDataError, "quote is absent"):
            validate_candidate_row(wrong_field, repo_root=REPO_ROOT)

        old_style = copy.deepcopy(completed)
        old_style["completion_state"] = "completed"
        with self.assertRaisesRegex(SuccessorDataError, "keys differ"):
            validate_candidate_row(old_style, repo_root=REPO_ROOT)

        scalar_packet = copy.deepcopy(completed)
        scalar_packet["packet"]["qualification"]["rubric"]["revision"] = "v1"
        with self.assertRaisesRegex(SuccessorDataError, "rubric.revision"):
            validate_candidate_row(scalar_packet, repo_root=REPO_ROOT)

    def test_rendered_rubric_defines_heads_without_sidecar_values(self) -> None:
        row = self._candidate(
            "candidate-id-supervision-marker",
            self._labels(continuity="N/A"),
            group_id="group-id-supervision-marker",
        )
        rubric = (
            REPO_ROOT / "eval/templates/publication-critic/qualification-rubric-v2.md"
        ).read_text(encoding="utf-8")
        split = SuccessorSplit(name="train", candidates=(row,), pairs=(), rubric=rubric)
        messages = split.model_inputs()[0]["messages"]
        rendered = "\n".join(message["content"] for message in messages)
        for required in (
            "`useful_state_transfer`: `PASS` when",
            "`honest_uncertainty`: `PASS` when",
            "`conditional_continuity`: `N/A` only when",
            "`scope_and_signal`: `PASS` when",
            "`internal_consistency`: `PASS` when",
            "one applicable `FAIL` requires `REWRITE`",
            "soft quality cannot compensate",
        ):
            self.assertIn(required, rendered)
        self.assertNotIn("candidate-id-supervision-marker", rendered)
        self.assertNotIn("group-id-supervision-marker", rendered)
        self.assertNotIn("model_visible_complete_claim", rendered)

    def test_train_consumer_never_opens_validation_or_test_bytes(self) -> None:
        accepted_commit = "a" * 40
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            train_candidates = [
                self._candidate("train-a", self._labels(continuity="N/A"))
            ]
            train_pairs: list[dict] = []
            candidate_bytes = self._jsonl_bytes(train_candidates)
            pair_bytes = self._jsonl_bytes(train_pairs)
            candidate_path = root / "splits/train/candidates.jsonl"
            pair_path = root / "splits/train/pairs.jsonl"
            candidate_path.parent.mkdir(parents=True)
            candidate_path.write_bytes(candidate_bytes)
            pair_path.write_bytes(pair_bytes)
            manifest = self._manifest(
                accepted_commit,
                train_candidate_bytes=candidate_bytes,
                train_pair_bytes=pair_bytes,
            )
            (root / "manifest.json").write_text(
                json.dumps(manifest, indent=2) + "\n",
                encoding="utf-8",
            )

            release = SuccessorRelease.open(
                root,
                expected_accepted_commit=accepted_commit,
                repo_root=REPO_ROOT,
            )
            train = release.load_train()
            self.assertEqual(train.name, "train")
            self.assertEqual(len(train.candidates), 1)
            self.assertIn(
                "candidate is complete",
                train.model_inputs()[0]["messages"][1]["content"],
            )
            self.assertFalse(hasattr(release, "load_test"))
            with self.assertRaisesRegex(SuccessorDataError, "input is missing"):
                release.load_validation()

    def test_old_release_manifest_cannot_masquerade_as_successor(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_text(
                json.dumps(
                    {
                        "schema": "rondo-publication-critic-training-data-release-schema-v2",
                        "dataset_revision": "publication-critic-v8",
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(SuccessorDataError, "manifest keys differ"):
                SuccessorRelease.open(
                    root,
                    expected_accepted_commit="a" * 40,
                    repo_root=REPO_ROOT,
                )

    def test_split_validator_closes_pair_group_and_label_semantics(self) -> None:
        left = self._candidate(
            "q-plus",
            self._labels(),
            group_id="group-boundary",
            summary=(
                "The fix is in progress; focused checks pass, and the next step "
                "is the integration check."
            ),
        )
        right_labels = self._labels()
        right_labels["internal_consistency"] = "FAIL"
        right = self._candidate(
            "q-minus",
            right_labels,
            group_id="group-boundary",
            summary="The fix is complete, but the handoff says investigation continues.",
        )
        pair = {
            "schema": PAIR_SCHEMA,
            "pair_id": "boundary-a",
            "group_id": "group-boundary",
            "kind": "boundary",
            "left_candidate_id": "q-plus",
            "right_candidate_id": "q-minus",
            "target_dimension": "internal_consistency",
            "soft_change": None,
        }
        validate_split("train", [left, right], [pair], repo_root=REPO_ROOT)
        broken = copy.deepcopy(pair)
        broken["group_id"] = "other-group"
        with self.assertRaisesRegex(SuccessorDataError, "crosses group"):
            validate_split("train", [left, right], [broken], repo_root=REPO_ROOT)

        soft_labels = self._labels(continuity="N/A")
        soft_left = self._candidate(
            "soft-left",
            soft_labels,
            group_id="group-soft",
            summary="The focused implementation is complete; targeted checks pass.",
        )
        soft_right = self._candidate(
            "soft-right",
            copy.deepcopy(soft_labels),
            group_id="group-soft",
            summary="The focused implementation is fully complete; targeted checks pass.",
        )
        soft_pair = {
            "schema": PAIR_SCHEMA,
            "pair_id": "soft-only-a",
            "group_id": "group-soft",
            "kind": "soft_only_invariance",
            "left_candidate_id": "soft-left",
            "right_candidate_id": "soft-right",
            "target_dimension": None,
            "soft_change": "Adds a harmless emphasis word without changing hard meaning.",
        }
        self.assertNotEqual(
            soft_left["packet"]["candidate"],
            soft_right["packet"]["candidate"],
        )
        self.assertEqual(derive_verdict(soft_left["labels"]), "PASS")
        self.assertEqual(derive_verdict(soft_right["labels"]), "PASS")
        validate_split(
            "train",
            [soft_left, soft_right],
            [soft_pair],
            repo_root=REPO_ROOT,
        )
        drifted = copy.deepcopy(soft_right)
        drifted["labels"]["scope_and_signal"] = "FAIL"
        with self.assertRaisesRegex(SuccessorDataError, "labels must be identical"):
            validate_split(
                "train",
                [soft_left, drifted],
                [soft_pair],
                repo_root=REPO_ROOT,
            )

    @staticmethod
    def _labels(*, continuity: str = "PASS") -> dict[str, str]:
        return {
            "useful_state_transfer": "PASS",
            "honest_uncertainty": "PASS",
            "conditional_continuity": continuity,
            "scope_and_signal": "PASS",
            "internal_consistency": "PASS",
        }

    @staticmethod
    def _packet(*, summary: str | None = None) -> dict:
        return {
            "qualification": {
                "packet_schema": {
                    "name": "rondo-publication-packet",
                    "revision": "v1",
                },
                "rubric": {
                    "name": "rondo-publication-qualification",
                    "revision": "v2",
                },
            },
            "actor_role": "root",
            "target_kind": "new_event",
            "local_scope": {"title": "Successor contract fixture"},
            "candidate": {
                "summary": summary
                or "The candidate is complete and the focused checks pass.",
                "handoff": None,
            },
            "continuity": {"state": "not_applicable"},
            "evidence_v1": {
                "semantic_entailment": "not_evaluated",
                "candidate_window": "not_frozen_before_commit",
            },
        }

    def _candidate(
        self,
        candidate_id: str,
        labels: dict[str, str],
        *,
        group_id: str = "group-a",
        summary: str | None = None,
    ) -> dict:
        packet = self._packet(summary=summary)
        return {
            "schema": CANDIDATE_SCHEMA,
            "candidate_id": candidate_id,
            "group_id": group_id,
            "packet": packet,
            "labels": labels,
            "continuity_label_basis": {
                "type": (
                    "model_visible_complete_claim"
                    if labels["conditional_continuity"] == "N/A"
                    else "model_visible_unfinished_or_not_closed"
                ),
                "field": "candidate.summary",
                "quote": packet["candidate"]["summary"],
            },
        }

    @staticmethod
    def _structured_output() -> dict:
        heads = {}
        for dimension in HARD_DIMENSIONS:
            classes = list(DIMENSION_CLASSES[dimension])
            logits = [0.1] * len(classes)
            winner = (
                classes.index("N/A") if dimension == "conditional_continuity" else 0
            )
            logits[winner] = 0.9
            heads[dimension] = {"classes": classes, "logits": [logits]}
        return {
            "schema": STRUCTURED_OUTPUT_SCHEMA,
            "backbone_forward_count": 1,
            "batch_size": 1,
            "heads": heads,
        }

    def _manifest(
        self,
        accepted_commit: str,
        *,
        train_candidate_bytes: bytes,
        train_pair_bytes: bytes,
    ) -> dict:
        def binding(path: str, content: bytes, rows: int) -> dict:
            return {
                "path": path,
                "sha256": hashlib.sha256(content).hexdigest(),
                "rows": rows,
            }

        missing = b"not opened by train"
        return {
            "schema": MANIFEST_SCHEMA,
            "task_contract": {
                "name": "rondo-publication-critic-task",
                "version": "v2",
                "content_sha256": task_content_sha256(REPO_ROOT),
                "accepted_commit": accepted_commit,
            },
            "splits": {
                "train": {
                    "candidates": binding(
                        "splits/train/candidates.jsonl",
                        train_candidate_bytes,
                        1,
                    ),
                    "pairs": binding("splits/train/pairs.jsonl", train_pair_bytes, 0),
                },
                "validation": {
                    "candidates": binding(
                        "splits/validation/candidates.jsonl", missing, 1
                    ),
                    "pairs": binding("splits/validation/pairs.jsonl", missing, 1),
                },
                "test": {
                    "candidates": binding("splits/test/candidates.jsonl", missing, 1),
                    "pairs": binding("splits/test/pairs.jsonl", missing, 1),
                },
            },
        }

    @staticmethod
    def _jsonl_bytes(rows: list[dict]) -> bytes:
        return b"".join(
            (json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n").encode(
                "utf-8"
            )
            for row in rows
        )

    @staticmethod
    def _load_json(path: Path) -> dict:
        return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
