from __future__ import annotations

import sys
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.training_data.contract import (  # noqa: E402
    TrainingDataError,
)
from rondo_eval.publication_critic.training_data.shortcuts import (  # noqa: E402
    conditioned_model_visible_text_shortcut_findings,
    model_visible_text_shortcut_findings,
)


def _packet(
    *,
    title: str,
    summary: str,
    handoff: str | None,
    continuity: dict | None = None,
) -> dict:
    return {
        "actor_role": "member",
        "target_kind": "handoff",
        "local_scope": {"title": title},
        "qualification": {
            "packet_schema": "rondo-publication-packet@v1",
            "rubric": "rondo-publication-qualification@v1",
        },
        "continuity": continuity
        or {"state": "not_applicable"},
        "evidence_v1": [],
        "candidate": {"summary": summary, "handoff": handoff},
    }


class Plan064ConditionedShortcutTests(unittest.TestCase):
    def test_conditioned_check_finds_cue_hidden_by_global_labels(self) -> None:
        packets = []
        supervision = []
        for focus, label, marker in (
            ("conditional_continuity", "PASS", "restart-anchor"),
            ("conditional_continuity", "PASS", "restart-anchor"),
            ("conditional_continuity", "PASS", "restart-anchor"),
            ("conditional_continuity", "PASS", "restart-anchor"),
            ("scope_and_signal", "REWRITE", "restart-anchor"),
            ("scope_and_signal", "REWRITE", "restart-anchor"),
            ("scope_and_signal", "REWRITE", "restart-anchor"),
            ("scope_and_signal", "REWRITE", "restart-anchor"),
        ):
            index = len(packets)
            candidate_id = f"candidate-{index}"
            packets.append(
                {
                    "candidate_id": candidate_id,
                    "packet": _packet(
                        title=f"balanced title {index % 2}",
                        summary=f"{marker} variant {index}",
                        handoff=None,
                    ),
                }
            )
            supervision.append(
                {
                    "candidate_id": candidate_id,
                    "binary_label": label,
                    "proposed_split": "train" if index % 2 == 0 else "validation",
                    "hard_focus": focus,
                }
            )

        findings = conditioned_model_visible_text_shortcut_findings(
            packets,
            supervision,
            condition_field="hard_focus",
        )

        self.assertTrue(
            any(
                finding["condition_value"] == "conditional_continuity"
                and finding["label"] == "PASS"
                for finding in findings
            )
        )
        self.assertTrue(
            any(
                finding["condition_value"] == "scope_and_signal"
                and finding["label"] == "REWRITE"
                for finding in findings
            )
        )

    def test_global_check_includes_model_visible_local_title(self) -> None:
        packets = []
        supervision = []
        for index in range(16):
            label = "REWRITE" if index < 8 else "PASS"
            candidate_id = f"title-candidate-{index}"
            marker = "rewrite-cue" if label == "REWRITE" else "neutral-title"
            packets.append(
                {
                    "candidate_id": candidate_id,
                    "packet": _packet(
                        title=f"{marker} {index}",
                        summary=f"balanced summary {index % 4}",
                        handoff=None,
                    ),
                }
            )
            supervision.append(
                {
                    "candidate_id": candidate_id,
                    "binary_label": label,
                    "proposed_split": "train" if index % 2 == 0 else "validation",
                }
            )

        findings = model_visible_text_shortcut_findings(
            packets,
            supervision,
            minimum_candidate_support=8,
        )

        self.assertTrue(
            any(
                finding["fragment"] == "rewr"
                and finding["label"] == "REWRITE"
                and finding["support"] == 8
                for finding in findings
            )
        )

    def test_global_check_includes_model_visible_continuity_history(self) -> None:
        packets = []
        supervision = []
        for index in range(16):
            label = "REWRITE" if index < 8 else "PASS"
            candidate_id = f"continuity-candidate-{index}"
            prior_marker = "prior-cue" if label == "REWRITE" else "neutral-history"
            packets.append(
                {
                    "candidate_id": candidate_id,
                    "packet": _packet(
                        title=f"balanced title {index % 4}",
                        summary=f"balanced summary {index % 4}",
                        handoff="balanced next step",
                        continuity={
                            "state": "available",
                            "source_team_revision": 12,
                            "freshness": "current",
                            "coverage": "complete",
                            "prior_publications": [
                                {
                                    "summary": f"{prior_marker} {index}",
                                    "handoff": "same handoff",
                                    "evidence": [],
                                }
                            ],
                        },
                    ),
                }
            )
            supervision.append(
                {
                    "candidate_id": candidate_id,
                    "binary_label": label,
                    "proposed_split": "train" if index % 2 == 0 else "validation",
                }
            )

        findings = model_visible_text_shortcut_findings(
            packets,
            supervision,
            minimum_candidate_support=8,
        )

        self.assertTrue(
            any(
                finding["fragment"] == "-cue"
                and finding["label"] == "REWRITE"
                and finding["support"] == 8
                for finding in findings
            )
        )

    def test_global_check_includes_short_visible_revision_values(self) -> None:
        packets = []
        supervision = []
        for index in range(16):
            label = "REWRITE" if index < 8 else "PASS"
            candidate_id = f"revision-candidate-{index}"
            packets.append(
                {
                    "candidate_id": candidate_id,
                    "packet": _packet(
                        title=f"balanced title {index % 4}",
                        summary=f"balanced summary {index % 4}",
                        handoff="balanced next step",
                        continuity={
                            "state": "available",
                            "source_team_revision": 12 if label == "REWRITE" else 34,
                            "freshness": "current",
                            "coverage": "complete",
                            "prior_publications": [],
                        },
                    ),
                }
            )
            supervision.append(
                {
                    "candidate_id": candidate_id,
                    "binary_label": label,
                    "proposed_split": "train" if index % 2 == 0 else "validation",
                }
            )

        findings = model_visible_text_shortcut_findings(
            packets,
            supervision,
            minimum_candidate_support=8,
        )

        self.assertTrue(
            any(
                finding["fragment"] == "12"
                and finding["label"] == "REWRITE"
                and finding["support"] == 8
                for finding in findings
            )
        )

    def test_global_check_uses_exact_post_omission_continuity_surface(self) -> None:
        packets = []
        supervision = []
        omissions = {}
        for index in range(16):
            label = "REWRITE" if index < 8 else "PASS"
            candidate_id = f"omission-candidate-{index}"
            dropped = 1 if label == "REWRITE" else 0
            omissions[candidate_id] = dropped
            packets.append(
                {
                    "candidate_id": candidate_id,
                    "packet": _packet(
                        title=f"balanced title {index % 4}",
                        summary=f"balanced summary {index % 4}",
                        handoff="balanced next step",
                        continuity={
                            "state": "available",
                            "source_team_revision": index + 100,
                            "freshness": "current",
                            "coverage": "complete",
                            "prior_publications": [
                                {
                                    "summary": (
                                        "omitted-only-marker"
                                        if label == "REWRITE"
                                        else "neutral-oldest"
                                    ),
                                    "handoff": "old",
                                    "evidence": [],
                                },
                                {
                                    "summary": f"retained history {index}",
                                    "handoff": "current",
                                    "evidence": [],
                                },
                            ],
                        },
                    ),
                }
            )
            supervision.append(
                {
                    "candidate_id": candidate_id,
                    "binary_label": label,
                    "proposed_split": "train" if index % 2 == 0 else "validation",
                }
            )

        findings = model_visible_text_shortcut_findings(
            packets,
            supervision,
            minimum_candidate_support=8,
            dropped_oldest_publications=omissions,
        )

        self.assertTrue(
            any(
                finding["fragment"] == "1"
                and finding["label"] == "REWRITE"
                for finding in findings
            )
        )
        self.assertFalse(
            any(finding["fragment"] == "omit" for finding in findings)
        )

    def test_condition_field_and_candidate_universe_are_strict(self) -> None:
        with self.assertRaisesRegex(TrainingDataError, "field must be non-empty"):
            conditioned_model_visible_text_shortcut_findings(
                [],
                [],
                condition_field="",
            )
        with self.assertRaisesRegex(TrainingDataError, "candidate IDs differ"):
            conditioned_model_visible_text_shortcut_findings(
                [{"candidate_id": "packet-only", "packet": {}}],
                [],
                condition_field="hard_focus",
            )


if __name__ == "__main__":
    unittest.main()
