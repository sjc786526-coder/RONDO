from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.training_data.contract import (  # noqa: E402
    TrainingDataError,
)
from rondo_eval.publication_critic.training_data.lineage import (  # noqa: E402
    validate_v7_lineage,
)


V7_ROOT = REPO_ROOT / "training/publication-critic-v7"


def _jsonl(name: str) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in (V7_ROOT / name).read_text(encoding="utf-8").splitlines()
        if line
    ]


def _v7() -> dict[str, object]:
    return {
        "scenarios": _jsonl("scenarios.jsonl"),
        "packets": _jsonl("packets.jsonl"),
        "supervision": _jsonl("supervision.jsonl"),
        "pairs": _jsonl("pairs.jsonl"),
        "membership": json.loads(
            (V7_ROOT / "membership.json").read_text(encoding="utf-8")
        ),
    }


def _validate(
    v7: dict[str, object],
    *,
    combined: dict[str, object] | None = None,
) -> dict[str, object]:
    release = v7 if combined is None else combined
    return validate_v7_lineage(
        v7_scenario_rows=v7["scenarios"],  # type: ignore[arg-type]
        v7_packet_rows=v7["packets"],  # type: ignore[arg-type]
        v7_supervision_rows=v7["supervision"],  # type: ignore[arg-type]
        v7_pair_rows=v7["pairs"],  # type: ignore[arg-type]
        v7_membership=v7["membership"],  # type: ignore[arg-type]
        combined_scenario_rows=release["scenarios"],  # type: ignore[arg-type]
        combined_packet_rows=release["packets"],  # type: ignore[arg-type]
        combined_supervision_rows=release["supervision"],  # type: ignore[arg-type]
        combined_pair_rows=release["pairs"],  # type: ignore[arg-type]
    )


class PublicationCriticPlan064LineageTests(unittest.TestCase):
    def test_frozen_v7_returns_deterministic_pinned_summary(self) -> None:
        v7 = _v7()
        first = _validate(v7)
        reordered = deepcopy(v7)
        for key in ("scenarios", "packets", "supervision", "pairs"):
            reordered[key] = list(reversed(reordered[key]))  # type: ignore[arg-type]
        second = _validate(reordered)

        self.assertEqual(first, second)
        self.assertEqual(first["verified_row_counts"], {
            "packets": 72,
            "pairs": 36,
            "scenarios": 36,
            "supervision": 72,
        })
        self.assertEqual(first["added_row_counts"], {
            "packets": 0,
            "pairs": 0,
            "scenarios": 0,
            "supervision": 0,
        })
        pinned = first["pinned_candidate_splits"]
        self.assertEqual(len(pinned), 72)
        self.assertEqual(
            {split: list(pinned.values()).count(split) for split in set(pinned.values())},
            {"train": 42, "validation": 16, "unseen_test": 14},
        )

    def test_additive_rows_do_not_change_v7_lineage(self) -> None:
        v7 = _v7()
        combined = deepcopy(v7)
        combined["scenarios"].append({"scenario_id": "p064-additional"})  # type: ignore[union-attr]
        combined["packets"].append({"candidate_id": "pc064-additional"})  # type: ignore[union-attr]
        combined["supervision"].append(  # type: ignore[union-attr]
            {"candidate_id": "pc064-additional", "proposed_split": "train"}
        )
        combined["pairs"].append({"pair_id": "pair-p064-additional"})  # type: ignore[union-attr]

        summary = _validate(v7, combined=combined)

        self.assertEqual(summary["added_row_counts"], {
            "packets": 1,
            "pairs": 1,
            "scenarios": 1,
            "supervision": 1,
        })

    def test_missing_v7_row_fails_closed(self) -> None:
        v7 = _v7()
        combined = deepcopy(v7)
        missing = combined["packets"].pop()  # type: ignore[union-attr]
        with self.assertRaisesRegex(
            TrainingDataError,
            f"missing v7 row: {missing['candidate_id']}",
        ):
            _validate(v7, combined=combined)

    def test_duplicate_combined_id_fails_closed(self) -> None:
        v7 = _v7()
        combined = deepcopy(v7)
        duplicate = deepcopy(combined["scenarios"][0])  # type: ignore[index]
        combined["scenarios"].append(duplicate)  # type: ignore[union-attr]
        with self.assertRaisesRegex(TrainingDataError, "duplicate scenario_id"):
            _validate(v7, combined=combined)

    def test_rewritten_v7_row_fails_closed(self) -> None:
        v7 = _v7()
        combined = deepcopy(v7)
        combined["packets"][0]["packet"]["candidate"]["summary"] += " drift"  # type: ignore[index]
        candidate_id = combined["packets"][0]["candidate_id"]  # type: ignore[index]
        with self.assertRaisesRegex(
            TrainingDataError,
            f"rewrites v7 row: {candidate_id}",
        ):
            _validate(v7, combined=combined)

    def test_v7_split_drift_fails_before_generic_rewrite(self) -> None:
        v7 = _v7()
        combined = deepcopy(v7)
        row = next(
            item
            for item in combined["supervision"]  # type: ignore[union-attr]
            if item["proposed_split"] == "validation"
        )
        row["proposed_split"] = "train"
        with self.assertRaisesRegex(
            TrainingDataError,
            f"v7 candidate split drifted: {row['candidate_id']}",
        ):
            _validate(v7, combined=combined)

    def test_v7_membership_cannot_move_holdout_into_train(self) -> None:
        v7 = _v7()
        holdout_id = next(
            row["candidate_id"]
            for row in v7["supervision"]  # type: ignore[union-attr]
            if row["proposed_split"] == "unseen_test"
        )
        stages = v7["membership"]["stages"]  # type: ignore[index]
        for stage in stages.values():
            stage["candidate_ids"].append(holdout_id)
            stage["candidate_ids"].sort()
        with self.assertRaisesRegex(TrainingDataError, "membership"):
            _validate(v7)


if __name__ == "__main__":
    unittest.main()
