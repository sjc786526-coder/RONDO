from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import sys
import tempfile
import unittest


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.training_data.contract import (  # noqa: E402
    TrainingDataError,
)
from rondo_eval.publication_critic.training_data.dedup import (  # noqa: E402
    find_near_duplicate_edges,
)
from rondo_eval.publication_critic.identity import (  # noqa: E402
    canonical_json_bytes,
    sha256_bytes,
)
from rondo_eval.publication_critic.render import build_messages  # noqa: E402
from rondo_eval.publication_critic.training_data.plan064_release import (  # noqa: E402
    _prefreeze_identity,
    _split_assignments_sha256,
    materialize_plan064_release,
    quality_audit_content_sha256,
)
from rondo_eval.publication_critic.training_data.plan064_batch import (  # noqa: E402
    build_plan064_aggregate_review_bindings,
    create_plan064_review_binding,
)
from rondo_eval.publication_critic.training_data.lineage import (  # noqa: E402
    project_v7_release_rows,
)
from rondo_eval.publication_critic.training_data.quality_audit import (  # noqa: E402
    build_plan064_quality_audit_strata,
    plan064_quality_audit_seed,
)


V7_ROOT = REPO_ROOT / "training/publication-critic-v7"
V8_LOCK = (
    REPO_ROOT / "eval/templates/publication-critic/training-data-design-lock-v8.json"
)
REFERENCES = REPO_ROOT / "eval/fixtures/publication-critic-v1/packets.jsonl"
GENERATOR_IDENTITY = {
    "model": "gpt-5.6-sol",
    "reasoning_effort": "high",
    "role": "plan064 generator",
    "prompt_sha256": "a" * 64,
    "date": "2026-08-23",
    "session_identity": "plan064-generator-test",
}
REVIEWER_IDENTITY = {
    "model": "gpt-5.6-sol",
    "reasoning_effort": "xhigh",
    "role": "plan064 independent reviewer",
    "prompt_sha256": "b" * 64,
    "date": "2026-08-23",
    "session_identity": "plan064-reviewer-test",
}


class _FakeTokenizer:
    def __init__(
        self,
        token_count_by_title: dict[str, int] | None = None,
        dropped_by_title: dict[str, int] | None = None,
    ) -> None:
        self.token_count_by_title = token_count_by_title or {}
        self.dropped_by_title = dropped_by_title or {}

    def fit_packet(self, packet: dict[str, object], rubric: str) -> SimpleNamespace:
        candidate = packet["candidate"]
        assert isinstance(candidate, dict)
        visible = str(candidate["summary"]) + str(candidate.get("handoff") or "")
        title = str(packet["local_scope"]["title"])
        default_count = int(
            len(
                json.dumps(
                    packet,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            * 0.8
        )
        token_count = self.token_count_by_title.get(title, default_count)
        dropped = self.dropped_by_title.get(title, 0)
        fitted_packet = deepcopy(packet)
        if dropped:
            del fitted_packet["continuity"]["prior_publications"][:dropped]
        candidate_tokens = min(max(1, len(visible) // 4), token_count)
        policy_tokens = token_count - candidate_tokens
        return SimpleNamespace(
            input_ids=tuple(range(token_count)),
            plan=SimpleNamespace(
                dropped_oldest_publications=dropped,
                messages=build_messages(
                    fitted_packet,
                    rubric,
                    dropped_oldest_publications=dropped,
                ),
            ),
            buckets={"candidate": candidate_tokens, "policy": policy_tokens},
            rendered_chat=f"fake:{visible}",
        )


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


class PublicationCriticPlan064ReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.ignored = self.root / "ignored"
        self.ignored.mkdir(mode=0o700)
        self.delta = self.ignored / "delta"
        self.delta.mkdir(mode=0o700)
        self.design_lock = self.root / "design-lock.json"
        lock = json.loads(V8_LOCK.read_text(encoding="utf-8"))
        lock["base_release"]["v8_membership_projection"] = {
            "policy": "plan064_exact_v7_membership_projection_v1",
            "finding": "unit-test-none",
            "reason": "Generic release fixtures exercise full v7 inheritance.",
            "retained_candidate_count": 72,
            "retained_pair_count": 36,
            "retired_candidate_ids": [],
            "retired_pair_ids": [],
        }
        lock["bounded_scale"]["logical_release_floor"] = 0
        lock["bounded_scale"]["hard_cap"] = 1000
        minimums = lock["coverage_minimums"]
        minimums["formal_total_candidates"] = 0
        minimums["split_candidates"] = {
            "train": 0,
            "validation": 0,
            "unseen_test": 0,
        }
        minimums["split_binary_labels"] = {
            split: {"PASS": 0, "REWRITE": 0}
            for split in ("train", "validation", "unseen_test")
        }
        minimums["publication_classes"]["minimum_scenario_groups_per_value_global"] = 0
        minimums["publication_classes"]["minimum_scenario_groups_per_value_per_split"] = 0
        minimums["boundary_hard_dimensions"]["minimum_pairs_per_value_global"] = 0
        minimums["boundary_hard_dimensions"]["minimum_pairs_per_value_per_split"] = 0
        minimums["natural_mixed_binary_candidates_per_split"] = 0
        minimums["within_pass_pairs_per_split"] = 0
        minimums["roles_per_split"] = []
        minimums["styles_per_split"] = []
        minimums["unicode_scenario_groups_global"] = 0
        minimums["long_input_candidates_per_split"] = 0
        minimums["hard_focus_publication_class_cells"][
            "minimum_scenario_groups_per_cell"
        ] = 0
        minimums["required_boundary_length_buckets_per_hard_dimension"] = []
        minimums["minimum_distinct_soft_preferences"] = 0
        minimums["holdout_feature_requirements"]["splits"] = []
        minimums["priority_slices"] = {
            key: 0 for key in minimums["priority_slices"]
        }
        lock["split_contract"]["candidate_ratio_tolerance"] = 1.0
        lock["split_contract"]["search_attempts"] = 128
        shortcuts = lock["shortcut_checks"]
        shortcuts["metadata_minimum_support"] = 1000
        shortcuts["visible_text_minimum_candidate_support_floor"] = 1000
        shortcuts["conditioned_text_minimum_candidate_support_floor"] = 1000
        shortcuts["candidate_length_minimum_support"] = 1000
        self.design_lock.write_text(
            json.dumps(lock, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        self._write_delta()
        self._write_review_bindings()
        self._write_quality_audit()

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_prefreeze_is_full_but_has_no_formal_outputs(self) -> None:
        output = self.ignored / "prefreeze"
        result = self._run("prefreeze", output)

        self.assertEqual(result["status"], "PREFREEZE_WAITING_APPROVAL")
        self.assertEqual(result["statistics"]["candidate_count"], 73)
        self.assertNotIn("manifest.json", {path.name for path in output.iterdir()})
        self.assertNotIn("DATA_CARD.md", {path.name for path in output.iterdir()})
        self.assertFalse((self.root / "training").exists())
        self.assertEqual(output.stat().st_mode & 0o777, 0o700)
        self.assertTrue(
            all(path.stat().st_mode & 0o777 == 0o600 for path in output.iterdir())
        )
        dispositions = _jsonl(output / "candidate-dispositions.jsonl")
        self.assertEqual(
            sum(row["method"] == "inherited_v7" for row in dispositions), 72
        )
        self.assertEqual(
            sum(row["method"] == "direct_accept" for row in dispositions), 1
        )
        source_binding = json.loads(
            (self.delta / "review-bindings.json").read_text(encoding="utf-8")
        )
        copied_binding = json.loads(
            (output / "review-bindings.json").read_text(encoding="utf-8")
        )
        identity = json.loads(
            (output / "prefreeze-identity.json").read_text(encoding="utf-8")
        )
        self.assertEqual(copied_binding, source_binding)
        self.assertEqual(
            identity["semantic_content_sha256"]["aggregate_review_bindings"],
            sha256_bytes(canonical_json_bytes(source_binding)),
        )

    def test_prefreeze_materializes_exact_v7_membership_projection(self) -> None:
        retired_candidate = "pc059-b-honest-01-qminus"
        retired_pair = "pair-b-honest-01-boundary"
        lock = json.loads(self.design_lock.read_text(encoding="utf-8"))
        lock["base_release"]["v8_membership_projection"] = {
            "policy": "plan064_exact_v7_membership_projection_v1",
            "finding": "unit-test-projection",
            "reason": "Exercise one exact candidate and relation retirement.",
            "retained_candidate_count": 71,
            "retained_pair_count": 35,
            "retired_candidate_ids": [retired_candidate],
            "retired_pair_ids": [retired_pair],
        }
        self.design_lock.write_text(
            json.dumps(lock, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        self._write_quality_audit()

        output = self.ignored / "prefreeze-projection"
        result = self._run("prefreeze", output)

        self.assertEqual(result["statistics"]["candidate_count"], 72)
        dispositions = _jsonl(output / "candidate-dispositions.jsonl")
        disposition_ids = {str(row["candidate_id"]) for row in dispositions}
        self.assertNotIn(retired_candidate, disposition_ids)
        self.assertEqual(
            sum(row["method"] == "inherited_v7" for row in dispositions),
            71,
        )
        pairs = _jsonl(output / "pairs.jsonl")
        self.assertNotIn(retired_pair, {str(row["pair_id"]) for row in pairs})
        lineage = json.loads((output / "lineage.json").read_text(encoding="utf-8"))
        self.assertEqual(lineage["physical_row_counts"]["supervision"], 72)
        self.assertEqual(lineage["verified_row_counts"]["supervision"], 71)

    def test_complete_release_quality_audit_is_bound_and_copied(self) -> None:
        output = self.ignored / "prefreeze-quality-audit"

        self._run("prefreeze", output)

        source = json.loads((self.delta / "quality-audit.json").read_text())
        copied = json.loads((output / "quality-audit.json").read_text())
        report = json.loads((output / "reports.json").read_text())["quality_audit"]
        identity = json.loads((output / "prefreeze-identity.json").read_text())
        expected_sha256 = sha256_bytes(canonical_json_bytes(source))
        self.assertEqual(copied, source)
        self.assertEqual(report["canonical_sha256"], expected_sha256)
        self.assertEqual(
            identity["semantic_content_sha256"]["quality_audit"],
            expected_sha256,
        )
        self.assertEqual(report["summary_counts"]["complete_candidate_count"], 73)
        self.assertEqual(report["summary_counts"]["complete_pair_count"], 36)

    def test_quality_audit_mismatched_complete_universe_fails_closed(self) -> None:
        audit_path = self.delta / "quality-audit.json"
        audit = json.loads(audit_path.read_text())
        audit["universe"]["candidate_ids_sha256"] = "0" * 64
        self._write_json("quality-audit.json", audit)
        output = self.ignored / "prefreeze-quality-universe-drift"

        with self.assertRaisesRegex(
            TrainingDataError,
            "candidate_ids_sha256 does not bind the complete release universe",
        ):
            self._run("prefreeze", output)
        self.assertFalse(output.exists())

    def test_quality_audit_unresolved_finding_fails_closed(self) -> None:
        audit_path = self.delta / "quality-audit.json"
        audit = json.loads(audit_path.read_text())
        audit["unresolved_systemic_findings"] = 1
        self._write_json("quality-audit.json", audit)
        output = self.ignored / "prefreeze-quality-unresolved"

        with self.assertRaisesRegex(
            TrainingDataError,
            "unresolved_systemic_findings must equal zero",
        ):
            self._run("prefreeze", output)
        self.assertFalse(output.exists())

    def test_quality_audit_cannot_be_vacuous(self) -> None:
        audit_path = self.delta / "quality-audit.json"
        audit = json.loads(audit_path.read_text())
        audit["sampled_candidate_ids"] = []
        audit["summary_counts"]["sampled_candidate_count"] = 0
        self._write_json("quality-audit.json", audit)
        output = self.ignored / "prefreeze-quality-vacuous"

        with self.assertRaisesRegex(
            TrainingDataError,
            "must sample at least one candidate",
        ):
            self._run("prefreeze", output)
        self.assertFalse(output.exists())

    def test_quality_audit_cannot_declare_bogus_strata(self) -> None:
        audit_path = self.delta / "quality-audit.json"
        audit = json.loads(audit_path.read_text())
        audit["strata"] = ["bogus-single-stratum"]
        audit["summary_counts"]["stratum_count"] = 1
        self._write_json("quality-audit.json", audit)
        output = self.ignored / "prefreeze-quality-bogus-strata"

        with self.assertRaisesRegex(TrainingDataError, "complete release"):
            self._run("prefreeze", output)
        self.assertFalse(output.exists())

    def test_quality_audit_must_sample_every_represented_stratum(self) -> None:
        audit_path = self.delta / "quality-audit.json"
        audit = json.loads(audit_path.read_text())
        audit["sampled_candidate_ids"].remove("pc064-test-single")
        audit["summary_counts"]["sampled_candidate_count"] -= 1
        self._write_json("quality-audit.json", audit)
        output = self.ignored / "prefreeze-quality-missing-stratum"

        with self.assertRaisesRegex(TrainingDataError, "misses represented strata"):
            self._run("prefreeze", output)
        self.assertFalse(output.exists())

    def test_freeze_requires_exact_approved_prefreeze_identity(self) -> None:
        prefreeze = self.ignored / "prefreeze"
        result = self._run("prefreeze", prefreeze)
        formal = self.root / "formal-v8"

        with self.assertRaisesRegex(TrainingDataError, "approval does not match"):
            self._run("freeze", formal, approved="0" * 64)
        self.assertFalse(formal.exists())

        frozen = self._run(
            "freeze",
            formal,
            approved=result["prefreeze_universe_sha256"],
        )
        self.assertEqual(frozen["status"], "FROZEN")
        self.assertTrue((formal / "manifest.json").is_file())
        self.assertTrue((formal / "DATA_CARD.md").is_file())
        self.assertEqual(
            json.loads((formal / "prefreeze-identity.json").read_text())["universe_sha256"],
            result["prefreeze_universe_sha256"],
        )

    def test_finalizer_rejects_aggregate_candidate_content_drift(self) -> None:
        packets_path = self.delta / "packets.jsonl"
        packets = _jsonl(packets_path)
        packets[0]["packet"]["candidate"]["summary"] += " 语义身份发生变化。"
        self._write_jsonl("packets.jsonl", packets)
        self._write_quality_audit()
        output = self.ignored / "prefreeze-candidate-binding-drift"

        with self.assertRaisesRegex(
            TrainingDataError,
            "aggregate review binding does not match current aggregate content",
        ):
            self._run("prefreeze", output)
        self.assertFalse(output.exists())

    def test_finalizer_rejects_aggregate_review_content_drift(self) -> None:
        reviews = _jsonl(self.delta / "candidate-reviews.jsonl")
        reviews[0]["rationale"] += " Review meaning drifted."
        self._write_jsonl("candidate-reviews.jsonl", reviews)
        output = self.ignored / "prefreeze-review-binding-drift"

        with self.assertRaisesRegex(
            TrainingDataError,
            "aggregate review binding does not match current aggregate content",
        ):
            self._run("prefreeze", output)
        self.assertFalse(output.exists())

    def test_finalizer_requires_aggregate_review_bindings(self) -> None:
        (self.delta / "review-bindings.json").unlink()
        output = self.ignored / "prefreeze-missing-review-bindings"

        with self.assertRaisesRegex(TrainingDataError, "review-bindings.json"):
            self._run("prefreeze", output)
        self.assertFalse(output.exists())

    def test_missing_direct_review_fails_before_creating_output(self) -> None:
        (self.delta / "candidate-reviews.jsonl").write_text("", encoding="utf-8")
        (self.delta / "candidate-reviews.jsonl").chmod(0o600)
        output = self.ignored / "prefreeze"

        with self.assertRaisesRegex(TrainingDataError, "review IDs"):
            self._run("prefreeze", output)
        self.assertFalse(output.exists())

    def test_delta_teacher_prompt_hashes_must_match_tracked_contracts(self) -> None:
        supervision = _jsonl(self.delta / "supervision.jsonl")
        supervision[0]["generator_identity"]["prompt_sha256"] = "0" * 64
        self._write_jsonl("supervision.jsonl", supervision)
        self._refresh_review_bindings()
        self._write_quality_audit()
        output = self.ignored / "prefreeze-generator-prompt-drift"

        with self.assertRaisesRegex(
            TrainingDataError,
            "generator prompt identity drifted",
        ):
            self._run("prefreeze", output)
        self.assertFalse(output.exists())

    def test_grouped_split_pins_v7_reassigns_new_and_binds_final_identity(self) -> None:
        first_output = self.ignored / "prefreeze-split-one"
        second_output = self.ignored / "prefreeze-split-two"

        first = self._run("prefreeze", first_output)
        second = self._run("prefreeze", second_output)

        authored = _jsonl(self.delta / "supervision.jsonl")
        final_rows = _jsonl(first_output / "supervision.jsonl")
        authored_new = next(row for row in authored if row["candidate_id"] == "pc064-test-single")
        final_new = next(row for row in final_rows if row["candidate_id"] == "pc064-test-single")
        self.assertEqual(authored_new["proposed_split"], "validation")
        self.assertEqual(final_new["proposed_split"], "train")

        v7_splits = {
            row["candidate_id"]: row["proposed_split"]
            for row in _jsonl(V7_ROOT / "supervision.jsonl")
        }
        final_splits = {
            row["candidate_id"]: row["proposed_split"] for row in final_rows
        }
        self.assertEqual(
            {candidate_id: final_splits[candidate_id] for candidate_id in v7_splits},
            v7_splits,
        )
        report = json.loads((first_output / "reports.json").read_text())
        self.assertEqual(
            report["split_assignment_summary"],
            {
                "authored_new_changed_count": 1,
                "final_split_counts": {
                    "train": 43,
                    "validation": 16,
                    "unseen_test": 14,
                },
            },
        )
        expected_supervision_sha = sha256_bytes(
            canonical_json_bytes(
                sorted(final_rows, key=lambda row: str(row["candidate_id"]))
            )
        )
        identity = json.loads((first_output / "prefreeze-identity.json").read_text())
        self.assertEqual(
            identity["semantic_content_sha256"]["supervision"],
            expected_supervision_sha,
        )
        self.assertEqual(
            first["prefreeze_universe_sha256"],
            second["prefreeze_universe_sha256"],
        )

    def test_complete_release_group_conflict_fails_closed(self) -> None:
        base_supervision = _jsonl(V7_ROOT / "supervision.jsonl")
        train = next(row for row in base_supervision if row["proposed_split"] == "train")
        validation = next(
            row for row in base_supervision if row["proposed_split"] == "validation"
        )
        scenarios = _jsonl(self.delta / "scenarios.jsonl")
        supervision = _jsonl(self.delta / "supervision.jsonl")
        scenarios[0]["source_group"] = train["source_group"]
        scenarios[0]["scenario_group"] = validation["scenario_group"]
        supervision[0]["source_group"] = train["source_group"]
        supervision[0]["scenario_group"] = validation["scenario_group"]
        self._write_jsonl("scenarios.jsonl", scenarios)
        self._write_jsonl("supervision.jsonl", supervision)
        self._refresh_review_bindings()
        self._write_quality_audit()
        output = self.ignored / "prefreeze-group-conflict"

        with self.assertRaisesRegex(
            TrainingDataError,
            "joins multiple distinct frozen base components",
        ):
            self._run("prefreeze", output)
        self.assertFalse(output.exists())

    def test_complete_release_coverage_fails_closed(self) -> None:
        lock = json.loads(self.design_lock.read_text())
        lock["coverage_minimums"]["formal_total_candidates"] = 74
        self.design_lock.write_text(
            json.dumps(lock, ensure_ascii=False, sort_keys=True), encoding="utf-8"
        )
        output = self.ignored / "prefreeze-coverage-failure"

        with self.assertRaisesRegex(
            TrainingDataError,
            "no grouped split satisfies the design lock",
        ):
            self._run("prefreeze", output)
        self.assertFalse(output.exists())

    def test_length_bucket_contract_accepts_valid_complete_release(self) -> None:
        output = self.ignored / "prefreeze-length-valid"

        self._run("prefreeze", output)

        report = json.loads((output / "reports.json").read_text(encoding="utf-8"))
        check = report["length_bucket_check"]
        self.assertEqual(check["status"], "pass")
        self.assertEqual(check["long_exact_input_min_tokens"], 1000)
        self.assertEqual(check["non_long_exact_input_max_tokens"], 999)
        self.assertEqual(
            check["candidate_counts"],
            {"long": 6, "medium": 60, "short": 7},
        )

    def test_consumer_materializes_exact_whole_oldest_omission(self) -> None:
        title = self._title_with_prior_publications(split="train")
        output = self.ignored / "prefreeze-consumer-omission"

        tokenizer = _FakeTokenizer(dropped_by_title={title: 1})
        prefreeze = self._run(
            "prefreeze",
            output,
            tokenizer=tokenizer,
        )

        census = _jsonl(output / "token-census.jsonl")
        row = next(
            row
            for row in census
            if self._packet_title(str(row["candidate_id"])) == title
        )
        self.assertEqual(row["dropped_oldest_publications"], 1)
        self._run(
            "freeze",
            self.root / "formal-v8",
            approved=str(prefreeze["prefreeze_universe_sha256"]),
            tokenizer=tokenizer,
        )

    def test_length_bucket_contract_rejects_long_too_short(self) -> None:
        long_title = self._title_for_bucket("long")
        output = self.ignored / "prefreeze-long-too-short"

        with self.assertRaisesRegex(TrainingDataError, "long candidate .* only 999"):
            self._run(
                "prefreeze",
                output,
                tokenizer=_FakeTokenizer({long_title: 999}),
            )
        self.assertFalse(output.exists())

    def test_length_bucket_contract_rejects_nonlong_too_long(self) -> None:
        output = self.ignored / "prefreeze-nonlong-too-long"

        with self.assertRaisesRegex(TrainingDataError, "non-long candidate .* 1000"):
            self._run(
                "prefreeze",
                output,
                tokenizer=_FakeTokenizer({"Plan 064 独立测试场景": 1000}),
            )
        self.assertFalse(output.exists())

    def test_prefreeze_identity_ignores_row_serialization_order(self) -> None:
        combined = {
            "scenarios": [{"scenario_id": "b"}, {"scenario_id": "a"}],
            "packets": [{"candidate_id": "b"}, {"candidate_id": "a"}],
            "supervision": [{"candidate_id": "b"}, {"candidate_id": "a"}],
            "pairs": [{"pair_id": "b"}, {"pair_id": "a"}],
        }
        candidate_reviews = [{"candidate_id": "b"}, {"candidate_id": "a"}]
        pair_reviews = [{"pair_id": "b"}, {"pair_id": "a"}]
        candidate_dispositions = [{"candidate_id": "b"}, {"candidate_id": "a"}]
        pair_dispositions = [{"pair_id": "b"}, {"pair_id": "a"}]

        first = _prefreeze_identity(
            design_lock_path=self.design_lock,
            plan054_input_identity={"fixed": True},
            base_manifest_content_sha256="a" * 64,
            combined=combined,
            candidate_reviews=candidate_reviews,
            pair_reviews=pair_reviews,
            candidate_dispositions=candidate_dispositions,
            pair_dispositions=pair_dispositions,
            lineage={"base": "v7"},
            quality_audit_sha256="c" * 64,
            aggregate_review_bindings_sha256="d" * 64,
            mechanical_artifacts_sha256="e" * 64,
        )
        second = _prefreeze_identity(
            design_lock_path=self.design_lock,
            plan054_input_identity={"fixed": True},
            base_manifest_content_sha256="a" * 64,
            combined={key: list(reversed(rows)) for key, rows in combined.items()},
            candidate_reviews=list(reversed(candidate_reviews)),
            pair_reviews=list(reversed(pair_reviews)),
            candidate_dispositions=list(reversed(candidate_dispositions)),
            pair_dispositions=list(reversed(pair_dispositions)),
            lineage={"base": "v7"},
            quality_audit_sha256="c" * 64,
            aggregate_review_bindings_sha256="d" * 64,
            mechanical_artifacts_sha256="e" * 64,
        )

        self.assertEqual(first, second)

    def test_prefreeze_identity_binds_phase_independent_mechanical_artifacts(self) -> None:
        common = {
            "design_lock_path": self.design_lock,
            "plan054_input_identity": {"fixed": True},
            "base_manifest_content_sha256": "a" * 64,
            "combined": {
                "scenarios": [{"scenario_id": "a"}],
                "packets": [{"candidate_id": "a"}],
                "supervision": [{"candidate_id": "a"}],
                "pairs": [{"pair_id": "a"}],
            },
            "candidate_reviews": [{"candidate_id": "a"}],
            "pair_reviews": [{"pair_id": "a"}],
            "candidate_dispositions": [{"candidate_id": "a"}],
            "pair_dispositions": [{"pair_id": "a"}],
            "lineage": {"base": "v7"},
            "quality_audit_sha256": "c" * 64,
            "aggregate_review_bindings_sha256": "d" * 64,
        }

        first = _prefreeze_identity(
            **common,
            mechanical_artifacts_sha256="e" * 64,
        )
        second = _prefreeze_identity(
            **common,
            mechanical_artifacts_sha256="f" * 64,
        )

        self.assertNotEqual(first["universe_sha256"], second["universe_sha256"])

    def test_prefreeze_identity_changes_when_token_report_changes(self) -> None:
        first = self._run("prefreeze", self.ignored / "prefreeze-token-one")
        second = self._run(
            "prefreeze",
            self.ignored / "prefreeze-token-two",
            tokenizer=_FakeTokenizer({"Plan 064 独立测试场景": 900}),
        )

        self.assertNotEqual(
            first["prefreeze_universe_sha256"],
            second["prefreeze_universe_sha256"],
        )

    def test_v7_byte_drift_fails_before_creating_output(self) -> None:
        drifted_base = self.root / "drifted-v7"
        shutil.copytree(V7_ROOT, drifted_base)
        manifest = drifted_base / "manifest.json"
        manifest.write_bytes(manifest.read_bytes() + b"\n")
        output = self.ignored / "prefreeze"

        with self.assertRaisesRegex(TrainingDataError, "directory bytes"):
            self._run("prefreeze", output, base_dir=drifted_base)
        self.assertFalse(output.exists())

    def test_plan054_design_identity_rejects_unverified_semantic_drift(self) -> None:
        original = json.loads(self.design_lock.read_text(encoding="utf-8"))
        mutations = {
            "overflow_policy": "reject",
            "scalar_direction": "lower_is_better",
            "messages": [],
            "source_allowlist": [],
        }
        for field, value in mutations.items():
            with self.subTest(field=field):
                lock = deepcopy(original)
                lock["plan054_input_contract"][field] = value
                self.design_lock.write_text(
                    json.dumps(lock, ensure_ascii=False, sort_keys=True),
                    encoding="utf-8",
                )
                output = self.ignored / f"prefreeze-plan054-{field}"
                with self.assertRaisesRegex(TrainingDataError, field):
                    self._run("prefreeze", output)
                self.assertFalse(output.exists())
        self.design_lock.write_text(
            json.dumps(original, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def _run(
        self,
        phase: str,
        output: Path,
        *,
        approved: str | None = None,
        base_dir: Path = V7_ROOT,
        tokenizer: _FakeTokenizer | None = None,
    ) -> dict[str, object]:
        return materialize_plan064_release(
            phase=phase,  # type: ignore[arg-type]
            base_dir=base_dir,
            delta_dir=self.delta,
            output_dir=output,
            design_lock_path=self.design_lock,
            reference_packets_path=REFERENCES,
            tokenizer=tokenizer or _FakeTokenizer(),
            generation_commit="c" * 40,
            contracts={
                "eval/templates/publication-critic/training-data-generator-prompt-v8.md": "a" * 64,
                "eval/templates/publication-critic/training-data-reviewer-prompt-v2.md": "b" * 64,
            },
            repo_root=REPO_ROOT,
            ignored_namespace=self.ignored,
            formal_release_dir=self.root / "formal-v8",
            approved_prefreeze_identity=approved,
        )

    @staticmethod
    def _title_for_bucket(bucket: str) -> str:
        supervision = _jsonl(V7_ROOT / "supervision.jsonl")
        candidate_id = next(
            row["candidate_id"]
            for row in supervision
            if row["length_bucket"] == bucket
        )
        packets = _jsonl(V7_ROOT / "packets.jsonl")
        packet = next(row for row in packets if row["candidate_id"] == candidate_id)
        return str(packet["packet"]["local_scope"]["title"])

    @staticmethod
    def _title_with_prior_publications(*, split: str) -> str:
        supervision = {
            str(row["candidate_id"]): row
            for row in _jsonl(V7_ROOT / "supervision.jsonl")
        }
        for row in _jsonl(V7_ROOT / "packets.jsonl"):
            candidate_id = str(row["candidate_id"])
            continuity = row["packet"]["continuity"]
            if (
                supervision[candidate_id]["proposed_split"] == split
                and continuity["state"] == "available"
                and continuity["prior_publications"]
            ):
                return str(row["packet"]["local_scope"]["title"])
        raise AssertionError("v7 fixture lacks an eligible continuity packet")

    @staticmethod
    def _packet_title(candidate_id: str) -> str:
        row = next(
            row
            for row in _jsonl(V7_ROOT / "packets.jsonl")
            if row["candidate_id"] == candidate_id
        )
        return str(row["packet"]["local_scope"]["title"])

    def _write_delta(self) -> None:
        scenario = deepcopy(
            next(
                row
                for row in _jsonl(V7_ROOT / "scenarios.jsonl")
                if row["scenario_id"] == "mixed-01"
            )
        )
        packet = deepcopy(
            next(
                row
                for row in _jsonl(V7_ROOT / "packets.jsonl")
                if row["candidate_id"] == "pc059-mixed-01-binary"
            )
        )
        supervision = deepcopy(
            next(
                row
                for row in _jsonl(V7_ROOT / "supervision.jsonl")
                if row["candidate_id"] == "pc059-mixed-01-binary"
            )
        )
        scenario_id = "p064-test-single"
        candidate_id = "pc064-test-single"
        source_group = "plan064-synthetic-product-shaped-v1:test-single"
        scenario.update(
            {
                "scenario_id": scenario_id,
                "source_id": "plan064-synthetic-product-shaped-v1",
                "source_group": source_group,
                "scenario_group": scenario_id,
                "template_group": scenario_id,
            }
        )
        scenario["blueprint"]["local_scope_title"] = "Plan 064 独立测试场景"
        packet["candidate_id"] = candidate_id
        packet["packet"]["local_scope"]["title"] = "Plan 064 独立测试场景"
        packet["packet"]["candidate"]["summary"] = (
            "独立观测只确认回收计数保持稳定，未推断底层调度原因。"
        )
        packet["packet"]["candidate"]["handoff"] = (
            "下一轮比较三种负载下的公开计数趋势。"
        )
        supervision.update(
            {
                "candidate_id": candidate_id,
                "scenario_id": scenario_id,
                "source_group": source_group,
                "scenario_group": scenario_id,
                "template_group": scenario_id,
                "generator_identity": GENERATOR_IDENTITY,
                "reviewer_identity": None,
                "review_status": "pending",
                "proposed_split": "validation",
            }
        )
        candidate_review = {
            "schema_version": 1,
            "candidate_id": candidate_id,
            "decision": "accept",
            "independent_label": supervision["binary_label"],
            "failed_hard_dimensions": [],
            "rationale": "The candidate stays within its public evidence and scope.",
            "reviewer_identity": REVIEWER_IDENTITY,
        }
        self._write_jsonl("scenarios.jsonl", [scenario])
        self._write_jsonl("packets.jsonl", [packet])
        self._write_jsonl("supervision.jsonl", [supervision])
        self._write_jsonl("pairs.jsonl", [])
        self._write_jsonl("candidate-reviews.jsonl", [candidate_review])
        self._write_jsonl("pair-reviews.jsonl", [])

    def _write_quality_audit(self) -> None:
        design_lock = json.loads(self.design_lock.read_text(encoding="utf-8"))
        projection = design_lock["base_release"]["v8_membership_projection"]
        base = project_v7_release_rows(
            v7_scenario_rows=_jsonl(V7_ROOT / "scenarios.jsonl"),
            v7_packet_rows=_jsonl(V7_ROOT / "packets.jsonl"),
            v7_supervision_rows=_jsonl(V7_ROOT / "supervision.jsonl"),
            v7_pair_rows=_jsonl(V7_ROOT / "pairs.jsonl"),
            retired_candidate_ids=projection["retired_candidate_ids"],
            retired_pair_ids=projection["retired_pair_ids"],
        )
        scenarios = [*base["scenarios"], *_jsonl(self.delta / "scenarios.jsonl")]
        packets = [*base["packets"], *_jsonl(self.delta / "packets.jsonl")]
        supervision = [
            *base["supervision"],
            *_jsonl(self.delta / "supervision.jsonl"),
        ]
        pairs = [*base["pairs"], *_jsonl(self.delta / "pairs.jsonl")]
        candidate_ids = sorted(str(row["candidate_id"]) for row in supervision)
        pair_ids = sorted(str(row["pair_id"]) for row in pairs)
        final_assignments = {
            str(row["candidate_id"]): str(row["proposed_split"])
            for row in base["supervision"]
        }
        final_assignments["pc064-test-single"] = "train"
        combined = {
            "scenarios": scenarios,
            "packets": packets,
            "supervision": supervision,
            "pairs": pairs,
        }
        near_edges = find_near_duplicate_edges(
            packets,
            threshold=float(
                design_lock["dedup_contract"]["near_duplicate_threshold"]
            ),
        )
        strata = build_plan064_quality_audit_strata(
            combined=combined,
            assignments=final_assignments,
            base_candidate_ids={
                str(row["candidate_id"])
                for row in base["supervision"]
            },
            base_pair_ids={
                str(row["pair_id"]) for row in base["pairs"]
            },
            near_duplicate_edges=near_edges,
            design_lock=design_lock,
        )
        sampled_candidate_set = set(strata.required_candidate_ids)
        sampled_pair_set = set(strata.required_pair_ids)
        pair_index = {str(row["pair_id"]): row for row in pairs}
        for pair_id in sampled_pair_set:
            pair = pair_index[pair_id]
            sampled_candidate_set.update(
                {
                    str(pair["preferred_candidate_id"]),
                    str(pair["dispreferred_candidate_id"]),
                }
            )
        sampled_candidates = sorted(sampled_candidate_set)
        sampled_pairs = sorted(sampled_pair_set)
        audit = {
            "schema": "rondo-publication-critic-plan064-quality-audit-v1",
            "universe": {
                "candidate_ids_sha256": sha256_bytes(
                    canonical_json_bytes(candidate_ids)
                ),
                "final_split_sha256": _split_assignments_sha256(
                    final_assignments
                ),
                "pair_ids_sha256": sha256_bytes(canonical_json_bytes(pair_ids)),
                "reviewed_content_sha256": quality_audit_content_sha256(combined),
            },
            "sampling_seed": plan064_quality_audit_seed(design_lock),
            "strata": list(strata.names),
            "sampled_candidate_ids": sampled_candidates,
            "sampled_pair_ids": sampled_pairs,
            "summary_counts": {
                "complete_candidate_count": len(candidate_ids),
                "complete_pair_count": len(pair_ids),
                "sampled_candidate_count": len(sampled_candidates),
                "sampled_pair_count": len(sampled_pairs),
                "stratum_count": len(strata.names),
                "finding_count": 0,
            },
            "findings": [],
            "unresolved_systemic_findings": 0,
        }
        self._write_json("quality-audit.json", audit)

    def _write_review_bindings(self) -> None:
        source_binding = create_plan064_review_binding(
            self.delta,
            self.delta,
            namespace=self.ignored,
        )
        aggregate = build_plan064_aggregate_review_bindings(
            [source_binding],
            scenarios=_jsonl(self.delta / "scenarios.jsonl"),
            packets=_jsonl(self.delta / "packets.jsonl"),
            supervision=_jsonl(self.delta / "supervision.jsonl"),
            pairs=_jsonl(self.delta / "pairs.jsonl"),
            candidate_reviews=_jsonl(self.delta / "candidate-reviews.jsonl"),
            pair_reviews=_jsonl(self.delta / "pair-reviews.jsonl"),
        )
        self._write_json("review-bindings.json", aggregate)

    def _refresh_review_bindings(self) -> None:
        for name in ("review-binding.json", "review-bindings.json"):
            path = self.delta / name
            if path.exists():
                path.unlink()
        self._write_review_bindings()

    def _write_json(self, name: str, value: dict[str, object]) -> None:
        path = self.delta / name
        path.write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        path.chmod(0o600)

    def _write_jsonl(self, name: str, rows: list[dict[str, object]]) -> None:
        path = self.delta / name
        content = "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + "\n"
            for row in rows
        )
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)


if __name__ == "__main__":
    unittest.main()
