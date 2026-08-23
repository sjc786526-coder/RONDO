from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.training_data import (  # noqa: E402
    TrainingDataError,
    validate_generation_batch,
)
from rondo_eval.publication_critic.training_data.input_identity import (  # noqa: E402
    load_plan054_training_input,
)


def _load_script(name: str, relative: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / relative)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load test module: {relative}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


generator = _load_script(
    "plan059_generator_v6_test_module",
    "eval/tools/generate_publication_critic_training_data.py",
)
finalizer = _load_script(
    "plan059_finalizer_v6_test_module",
    "eval/tools/finalize_publication_critic_training_data.py",
)


class PublicationCriticTrainingV6Tests(unittest.TestCase):
    def test_design_lock_input_identity_is_verified_plan054_identity(self) -> None:
        lock = finalizer._load_design_lock()
        verified = load_plan054_training_input(REPO_ROOT)
        self.assertEqual(lock["dataset_revision"], "v6")
        self.assertEqual(lock["input_identity"], dict(verified.input_identity))

    def test_continuity_negatives_do_not_treat_optional_handoff_as_the_defect(self) -> None:
        identity = {
            "model": "gpt-5.6-sol",
            "reasoning_effort": "xhigh",
            "role": "test",
            "prompt_sha256": "a" * 64,
            "date": "2026-08-23",
            "session_identity": "test",
        }
        specs = {
            spec.scenario_id: spec
            for spec in generator.BOUNDARY_SPECS
            if spec.hard_focus == "conditional_continuity"
        }
        self.assertEqual(len(specs), 6)
        for scenario_id, spec in specs.items():
            packets, supervision, pairs, _scenario = generator._boundary_records(spec, identity)
            packet_by_id = {row["candidate_id"]: row["packet"] for row in packets}
            pair = next(row for row in pairs if row["kind"] == "boundary")
            preferred = packet_by_id[pair["preferred_candidate_id"]]
            dispreferred = packet_by_id[pair["dispreferred_candidate_id"]]
            self.assertNotEqual(
                preferred["candidate"]["summary"],
                dispreferred["candidate"]["summary"],
                scenario_id,
            )
            self.assertIsNotNone(preferred["candidate"]["handoff"], scenario_id)
            self.assertIsNone(dispreferred["candidate"]["handoff"], scenario_id)
            self.assertEqual(
                {key: value for key, value in preferred.items() if key != "candidate"},
                {key: value for key, value in dispreferred.items() if key != "candidate"},
                scenario_id,
            )
            rewrite = next(row for row in supervision if row["binary_label"] == "REWRITE")
            self.assertEqual(rewrite["defects"], ["conditional_continuity"])

    def test_continuity_negatives_do_not_share_a_cross_scenario_failure_phrase(self) -> None:
        negative_summaries = [
            generator.NEGATIVE_CANDIDATES[f"b-continuity-{index:02d}"][0]
            for index in range(1, 7)
        ]
        pass_text = "".join(
            spec.concrete_state + (spec.next_step or "")
            for spec in generator.BOUNDARY_SPECS
            if spec.hard_focus == "conditional_continuity"
        )
        support: dict[str, int] = {}
        for summary in negative_summaries:
            for start in range(max(0, len(summary) - 3)):
                fragment = summary[start : start + 4]
                support[fragment] = support.get(fragment, 0) + 1
        exclusive = sorted(
            fragment
            for fragment, count in support.items()
            if count >= 4 and fragment not in pass_text
        )
        self.assertEqual(exclusive, [])

    def test_scope_negatives_have_no_cross_scenario_diary_markers(self) -> None:
        forbidden = ("记录 1", "记录 2", "无关", "最终结论")
        summaries = [
            generator.NEGATIVE_CANDIDATES[f"b-scope-{index:02d}"][0]
            for index in range(1, 7)
        ]
        self.assertEqual(len(set(summaries)), 6)
        for summary in summaries:
            self.assertFalse(any(marker in summary for marker in forbidden), summary)

    def test_scope_negatives_do_not_share_the_rejected_desktop_ui_topic(self) -> None:
        desktop_ui_terms = {
            "配色", "颜色", "透明度", "阴影", "图标", "字号", "字体", "缩放",
            "光标", "行号", "自动换行", "书签", "截图", "窗口", "侧栏", "提示音",
            "提示符动画", "任务栏", "通知区域", "桌面快捷方式", "鼠标停留", "键盘布局",
        }
        summaries = [
            generator.NEGATIVE_CANDIDATES[f"b-scope-{index:02d}"][0]
            for index in range(1, 7)
        ]
        self.assertTrue(all(sum(term in summary for term in desktop_ui_terms) < 3 for summary in summaries))

    def test_authored_candidate_character_length_is_not_a_global_label_proxy(self) -> None:
        identity = {
            "model": "gpt-5.6-sol",
            "reasoning_effort": "xhigh",
            "role": "test",
            "prompt_sha256": "a" * 64,
            "date": "2026-08-23",
            "session_identity": "test",
        }
        rows: list[tuple[int, str]] = []
        for spec in generator.BOUNDARY_SPECS:
            packets, supervision, _pairs, _scenario = generator._boundary_records(
                spec, identity
            )
            labels = {row["candidate_id"]: row["binary_label"] for row in supervision}
            for row in packets:
                candidate = row["packet"]["candidate"]
                rows.append(
                    (
                        len(candidate["summary"]) + len(candidate["handoff"] or ""),
                        labels[row["candidate_id"]],
                    )
                )
        for raw in generator.MIXED_SPECS:
            packet, supervision, _scenario = generator._mixed_record(raw, identity)
            candidate = packet["packet"]["candidate"]
            rows.append(
                (
                    len(candidate["summary"]) + len(candidate["handoff"] or ""),
                    supervision["binary_label"],
                )
            )
        for threshold in {length for length, _label in rows}:
            for selected in (
                [label for length, label in rows if length <= threshold],
                [label for length, label in rows if length >= threshold],
            ):
                if len(selected) >= 6:
                    self.assertGreater(len(set(selected)), 1, (threshold, selected))

    def test_long_bucket_is_scenario_scoped_and_has_distinct_public_history(self) -> None:
        identity = {
            "model": "gpt-5.6-sol",
            "reasoning_effort": "xhigh",
            "role": "test",
            "prompt_sha256": "a" * 64,
            "date": "2026-08-23",
            "session_identity": "test",
        }
        long_specs = [spec for spec in generator.BOUNDARY_SPECS if spec.long_input]
        self.assertEqual(
            {spec.scenario_id for spec in long_specs},
            {"b-honest-04", "b-consistency-03", "b-consistency-06"},
        )
        for spec in long_specs:
            packets, supervision, _pairs, scenario = generator._boundary_records(spec, identity)
            self.assertEqual(scenario["length_bucket"], "long")
            self.assertEqual({row["length_bucket"] for row in supervision}, {"long"})
            self.assertTrue(all("long_input" in row["slices"] for row in supervision))
            for row in packets:
                history = row["packet"]["continuity"]["prior_publications"]
                self.assertEqual(len(history), 4)
                self.assertEqual(len({entry["summary"] for entry in history}), 4)

    def test_generation_contract_rejects_candidate_scenario_length_drift(self) -> None:
        identity = {
            "model": "gpt-5.6-sol",
            "reasoning_effort": "xhigh",
            "role": "test",
            "prompt_sha256": "a" * 64,
            "date": "2026-08-23",
            "session_identity": "test",
        }
        spec = next(
            row for row in generator.BOUNDARY_SPECS if row.scenario_id == "b-honest-04"
        )
        packets, supervision, pairs, scenario = generator._boundary_records(spec, identity)
        scenario["length_bucket"] = "medium"
        with self.assertRaisesRegex(TrainingDataError, "Scenario field length_bucket"):
            validate_generation_batch(
                [scenario],
                packets,
                supervision,
                pairs,
                allowed_source_ids={generator.SYNTHETIC_SOURCE},
                repo_root=REPO_ROOT,
            )

    def test_exact_length_bucket_contract_is_fail_closed(self) -> None:
        contract = {
            "long_exact_input_min_tokens": 1000,
            "non_long_exact_input_max_tokens": 999,
        }
        finalizer._validate_exact_length_buckets(
            [{"candidate_id": "long", "length_bucket": "long"}],
            [{"candidate_id": "long", "token_count": 1000}],
            contract,
        )
        with self.assertRaisesRegex(TrainingDataError, "long but has only 999"):
            finalizer._validate_exact_length_buckets(
                [{"candidate_id": "long", "length_bucket": "long"}],
                [{"candidate_id": "long", "token_count": 999}],
                contract,
            )
        with self.assertRaisesRegex(TrainingDataError, "non-long but has 1000"):
            finalizer._validate_exact_length_buckets(
                [{"candidate_id": "medium", "length_bucket": "medium"}],
                [{"candidate_id": "medium", "token_count": 1000}],
                contract,
            )

    def test_data_card_rejects_human_ground_truth_claim(self) -> None:
        card = finalizer._data_card(
            "v6",
            "formal",
            {
                "candidate_count": 72,
                "binary_counts": {"PASS": 39, "REWRITE": 33},
                "pair_counts": {"boundary": 30, "within_pass": 6},
                "split_counts": {"train": 42, "validation": 16, "unseen_test": 14},
                "token_census": {
                    "token_total": 1,
                    "token_min": 1,
                    "token_max": 1,
                    "dropped_oldest_publications_total": 0,
                },
            },
            {
                "generator": {
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": "xhigh",
                    "session_identity": "generator",
                    "prompt_sha256": "a" * 64,
                },
                "reviewer": {
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": "xhigh",
                    "session_identity": "reviewer",
                    "prompt_sha256": "b" * 64,
                },
            },
            {
                "near_duplicate_edges": [],
                "plan054_reference_matches": [],
                "model_visible_text_shortcuts": [],
                "model_visible_candidate_length_shortcuts": [],
                "source_composition": {
                    "synthetic_scenarios": 34,
                    "tracked_public_anchor_scenarios": 2,
                },
            },
        )
        self.assertIn("not human-labelled ground truth", card)
        self.assertIn("34 synthetic product-shaped Scenarios", card)


if __name__ == "__main__":
    unittest.main()
