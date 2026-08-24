from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.training_data.contract import (  # noqa: E402
    TrainingDataError,
)
from rondo_eval.publication_critic.training_data.review_policy import (  # noqa: E402
    validate_plan064_review_dispositions,
)


GENERATOR_IDENTITY = {
    "model": "gpt-5.6-sol",
    "reasoning_effort": "high",
    "role": "generator",
    "prompt_sha256": "a" * 64,
    "date": "2026-08-23",
    "session_identity": "generator-session",
}
REVIEWER_IDENTITY = {
    "model": "gpt-5.6-sol",
    "reasoning_effort": "xhigh",
    "role": "independent reviewer",
    "prompt_sha256": "b" * 64,
    "date": "2026-08-23",
    "session_identity": "reviewer-session",
}


class Plan064ReviewPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.supervision = [
            self._supervision("v7-pass", "PASS"),
            self._supervision("v7-rewrite", "REWRITE"),
            self._supervision("new-pass", "PASS"),
            self._supervision("new-rewrite", "REWRITE"),
        ]
        self.pairs = [
            self._pair("v7-pair", "v7-pass", "v7-rewrite"),
            self._pair("new-pair", "new-pass", "new-rewrite"),
        ]
        self.candidate_reviews = [
            self._candidate_review("new-pass", "PASS"),
            self._candidate_review("new-rewrite", "REWRITE"),
        ]
        self.pair_reviews = [self._pair_review("new-pair")]
        self.candidate_dispositions = [
            self._candidate_disposition("v7-pass", "inherited_v7"),
            self._candidate_disposition("v7-rewrite", "inherited_v7"),
            self._candidate_disposition("new-pass", "direct_accept"),
            self._candidate_disposition("new-rewrite", "direct_accept"),
        ]
        self.pair_dispositions = [
            self._pair_disposition("v7-pair", "inherited_v7"),
            self._pair_disposition("new-pair", "direct_accept"),
        ]

    def test_v7_inheritance_and_new_direct_reviews_close_the_release(self) -> None:
        self._validate()

    def test_disposition_ids_must_exactly_match_release_ids(self) -> None:
        missing = copy.deepcopy(self.candidate_dispositions[:-1])
        with self.assertRaisesRegex(TrainingDataError, "missing=.*new-rewrite"):
            self._validate(candidate_dispositions=missing)

        extra = copy.deepcopy(self.pair_dispositions)
        extra.append(self._pair_disposition("outside-pair", "direct_accept"))
        with self.assertRaisesRegex(TrainingDataError, "extra=.*outside-pair"):
            self._validate(pair_dispositions=extra)

    def test_new_member_cannot_forge_v7_inheritance_or_unknown_method(self) -> None:
        forged = copy.deepcopy(self.candidate_dispositions)
        forged[2]["method"] = "inherited_v7"
        with self.assertRaisesRegex(TrainingDataError, "new-pass must use direct_accept"):
            self._validate(candidate_dispositions=forged)

        unknown = copy.deepcopy(self.candidate_dispositions)
        unknown[2]["method"] = "sampling_policy_accept"
        with self.assertRaisesRegex(TrainingDataError, "unknown method"):
            self._validate(candidate_dispositions=unknown)

    def test_new_candidate_requires_terminal_independent_direct_review(self) -> None:
        with self.assertRaisesRegex(TrainingDataError, "new-rewrite lacks a direct review"):
            self._validate(candidate_reviews=self.candidate_reviews[:-1])

        not_independent = copy.deepcopy(self.candidate_reviews)
        not_independent[0]["reviewer_identity"] = GENERATOR_IDENTITY
        supervision = copy.deepcopy(self.supervision)
        supervision[2]["reviewer_identity"] = GENERATOR_IDENTITY
        with self.assertRaisesRegex(TrainingDataError, "not independent"):
            self._validate(
                supervision=supervision,
                candidate_reviews=not_independent,
            )

    def test_new_candidate_review_must_confirm_complete_defect_set(self) -> None:
        mismatched = copy.deepcopy(self.candidate_reviews)
        mismatched[1]["failed_hard_dimensions"] = ["internal_consistency"]
        with self.assertRaisesRegex(TrainingDataError, "direct review defects differ"):
            self._validate(candidate_reviews=mismatched)

    def test_new_pair_requires_terminal_direct_review(self) -> None:
        with self.assertRaisesRegex(TrainingDataError, "new-pair lacks a direct review"):
            self._validate(pair_reviews=[])

        weak = copy.deepcopy(self.pair_reviews)
        weak[0]["atomicity_confirmed"] = False
        with self.assertRaisesRegex(TrainingDataError, "confirm atomicity"):
            self._validate(pair_reviews=weak)

    def _validate(self, **overrides: object) -> None:
        validate_plan064_review_dispositions(
            overrides.get("supervision", self.supervision),  # type: ignore[arg-type]
            overrides.get("pairs", self.pairs),  # type: ignore[arg-type]
            overrides.get("candidate_reviews", self.candidate_reviews),  # type: ignore[arg-type]
            overrides.get("pair_reviews", self.pair_reviews),  # type: ignore[arg-type]
            overrides.get("candidate_dispositions", self.candidate_dispositions),  # type: ignore[arg-type]
            overrides.get("pair_dispositions", self.pair_dispositions),  # type: ignore[arg-type]
            inherited_v7_candidate_ids={"v7-pass", "v7-rewrite"},
            inherited_v7_pair_ids={"v7-pair"},
        )

    @staticmethod
    def _supervision(candidate_id: str, label: str) -> dict[str, object]:
        return {
            "candidate_id": candidate_id,
            "binary_label": label,
            "defects": [] if label == "PASS" else ["scope_and_signal"],
            "generator_identity": GENERATOR_IDENTITY,
            "reviewer_identity": REVIEWER_IDENTITY,
            "review_status": "accept",
        }

    @staticmethod
    def _pair(pair_id: str, preferred: str, dispreferred: str) -> dict[str, object]:
        return {
            "pair_id": pair_id,
            "kind": "boundary",
            "preferred_candidate_id": preferred,
            "dispreferred_candidate_id": dispreferred,
            "review_status": "accept",
        }

    @staticmethod
    def _candidate_review(candidate_id: str, label: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "candidate_id": candidate_id,
            "decision": "accept",
            "independent_label": label,
            "failed_hard_dimensions": [] if label == "PASS" else ["scope_and_signal"],
            "rationale": "Independent judgment of the current candidate.",
            "reviewer_identity": REVIEWER_IDENTITY,
        }

    @staticmethod
    def _pair_review(pair_id: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "pair_id": pair_id,
            "decision": "accept",
            "direction_confirmed": True,
            "context_equal": True,
            "omission_equal": True,
            "atomicity_confirmed": True,
            "soft_only_confirmed": False,
            "rationale": "The pair differs only on the target hard dimension.",
            "reviewer_identity": REVIEWER_IDENTITY,
        }

    @staticmethod
    def _candidate_disposition(candidate_id: str, method: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "candidate_id": candidate_id,
            "method": method,
        }

    @staticmethod
    def _pair_disposition(pair_id: str, method: str) -> dict[str, object]:
        return {
            "schema_version": 1,
            "pair_id": pair_id,
            "method": method,
        }


if __name__ == "__main__":
    unittest.main()
