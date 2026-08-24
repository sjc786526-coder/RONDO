from collections import Counter
import sys
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.training_data import (  # noqa: E402
    TrainingDataError,
    coverage_failures,
    deterministic_grouped_stratified_split,
    validate_group_closure,
    validate_new_to_base_component_closure,
)


class Plan064FixedSplitTests(unittest.TestCase):
    def test_combined_component_cannot_join_distinct_v7_components(self) -> None:
        with self.assertRaisesRegex(
            TrainingDataError,
            "joins multiple distinct frozen base components",
        ):
            validate_new_to_base_component_closure(
                {
                    "v7-a": "combined",
                    "v7-b": "combined",
                    "new": "combined",
                },
                {"v7-a": "base-a", "v7-b": "base-b"},
            )

    def test_combined_component_may_extend_one_v7_component(self) -> None:
        validate_new_to_base_component_closure(
            {
                "v7-a": "combined",
                "v7-a-peer": "combined",
                "new": "combined",
            },
            {"v7-a": "base-a", "v7-a-peer": "base-a"},
        )

    def test_empty_fixed_assignments_preserve_default_behavior(self) -> None:
        rows = self._rows(12)
        components = self._singleton_components(rows)
        lock = self._design_lock(total=12, ratio_tolerance=0.26)

        original = deterministic_grouped_stratified_split(components, rows, [], lock)
        explicit_empty = deterministic_grouped_stratified_split(
            components,
            rows,
            [],
            lock,
            fixed_assignments={},
        )

        self.assertEqual(original, explicit_empty)

    def test_conflicting_fixed_splits_inside_component_fail_closed(self) -> None:
        rows = self._rows(2)
        components = {"candidate-00": "shared", "candidate-01": "shared"}

        with self.assertRaisesRegex(
            TrainingDataError,
            "fixed split assignments conflict within group component",
        ):
            deterministic_grouped_stratified_split(
                components,
                rows,
                [],
                self._design_lock(total=2, ratio_tolerance=1.0),
                fixed_assignments={
                    "candidate-00": "train",
                    "candidate-01": "validation",
                },
            )

    def test_fixed_candidate_pins_its_complete_component(self) -> None:
        rows = self._rows(6)
        components = self._singleton_components(rows)
        components["candidate-00"] = "shared"
        components["candidate-01"] = "shared"
        lock = self._design_lock(total=6, ratio_tolerance=1.0)

        assignments = deterministic_grouped_stratified_split(
            components,
            rows,
            [],
            lock,
            fixed_assignments={"candidate-00": "unseen_test"},
        )

        self.assertEqual(assignments["candidate-00"], "unseen_test")
        self.assertEqual(assignments["candidate-01"], "unseen_test")
        validate_group_closure(components, assignments)

    def test_unfixed_components_remain_deterministic(self) -> None:
        rows = self._rows(12)
        components = self._singleton_components(rows)
        lock = self._design_lock(total=12, ratio_tolerance=0.26)
        fixed = {"candidate-00": "train"}

        first = deterministic_grouped_stratified_split(
            components,
            rows,
            [],
            lock,
            fixed_assignments=fixed,
        )
        second = deterministic_grouped_stratified_split(
            components,
            rows,
            [],
            lock,
            fixed_assignments=fixed,
        )

        self.assertEqual(first, second)
        self.assertEqual(first["candidate-00"], "train")

    def test_complete_release_coverage_and_ratios_include_fixed_rows(self) -> None:
        rows = self._rows(12)
        components = self._singleton_components(rows)
        lock = self._design_lock(total=12, ratio_tolerance=0.0)
        fixed = {
            "candidate-00": "train",
            "candidate-01": "validation",
            "candidate-02": "unseen_test",
        }

        assignments = deterministic_grouped_stratified_split(
            components,
            rows,
            [],
            lock,
            fixed_assignments=fixed,
        )

        self.assertEqual(
            Counter(assignments.values()),
            {"train": 6, "validation": 3, "unseen_test": 3},
        )
        self.assertEqual(coverage_failures(assignments, rows, [], lock), ())
        validate_group_closure(components, assignments)

    def test_sparse_cell_length_soft_and_holdout_requirements_fail_closed(self) -> None:
        rows = self._rows(6)
        rows[0]["hard_focus"] = "scope_and_signal"
        rows[0]["publication_class"] = "new_event_completed"
        assignments = {
            row["candidate_id"]: split
            for row, split in zip(
                rows,
                ("train", "train", "validation", "validation", "unseen_test", "unseen_test"),
            )
        }
        lock = self._design_lock(total=6, ratio_tolerance=1.0)
        minimums = lock["coverage_minimums"]
        minimums["publication_classes"]["values"] = ["new_event_completed"]
        minimums["boundary_hard_dimensions"]["values"] = ["scope_and_signal"]
        minimums["hard_focus_publication_class_cells"] = {
            "minimum_scenario_groups_per_cell": 2,
            "conditional_continuity_publication_classes": [],
        }
        minimums["required_boundary_length_buckets_per_hard_dimension"] = [
            "long"
        ]
        minimums["minimum_distinct_soft_preferences"] = 1
        minimums["holdout_feature_requirements"] = {
            "splits": ["validation", "unseen_test"],
            "unicode_values": [True, False],
            "continuity_slices": ["continuity_unavailable"],
            "evidence_slices": ["evidence_present"],
            "natural_mixed_labels": ["PASS", "REWRITE"],
        }

        failures = coverage_failures(assignments, rows, [], lock)

        self.assertIn(
            "hard_focus_publication_class.scope_and_signal.new_event_completed",
            failures,
        )
        self.assertIn("boundary_length.scope_and_signal.long", failures)
        self.assertIn("within_pass.distinct_soft_preferences", failures)
        self.assertIn("holdout.validation.continuity_unavailable", failures)
        self.assertIn("holdout.unseen_test.natural_mixed.PASS", failures)

    @staticmethod
    def _rows(count: int) -> list[dict]:
        return [
            {
                "candidate_id": f"candidate-{index:02d}",
                "binary_label": "PASS" if index % 2 == 0 else "REWRITE",
                "publication_class": "new_event_completed",
                "scenario_group": f"scenario-{index:02d}",
                "slices": [],
                "actor_role": "root",
                "style": "formal",
                "length_bucket": "short",
                "unicode": False,
                "defects": [],
            }
            for index in range(count)
        ]

    @staticmethod
    def _singleton_components(rows: list[dict]) -> dict[str, str]:
        return {row["candidate_id"]: f"group-{index:02d}" for index, row in enumerate(rows)}

    @staticmethod
    def _design_lock(*, total: int, ratio_tolerance: float) -> dict:
        return {
            "split_contract": {
                "names": ["train", "validation", "unseen_test"],
                "target_candidate_ratios": {
                    "train": 0.5,
                    "validation": 0.25,
                    "unseen_test": 0.25,
                },
                "candidate_ratio_tolerance": ratio_tolerance,
                "seed": "plan064-fixed-split-test",
                "search_attempts": 500,
            },
            "coverage_minimums": {
                "formal_total_candidates": total,
                "split_candidates": {
                    "train": 0,
                    "validation": 0,
                    "unseen_test": 0,
                },
                "split_binary_labels": {
                    split: {"PASS": 0, "REWRITE": 0}
                    for split in ("train", "validation", "unseen_test")
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
                "within_pass_pairs_per_split": 0,
                "natural_mixed_binary_candidates_per_split": 0,
                "roles_per_split": [],
                "styles_per_split": [],
                "long_input_candidates_per_split": 0,
                "unicode_scenario_groups_global": 0,
            },
        }


if __name__ == "__main__":
    unittest.main()
