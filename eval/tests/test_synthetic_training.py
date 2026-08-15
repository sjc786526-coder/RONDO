from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from rondo_eval.local_approval import synthetic_training


EVAL_ROOT = Path(__file__).resolve().parents[1]
WORKTREE_ROOT = EVAL_ROOT.parent


def action(index: int) -> dict:
    return {
        "tool": "exec_command",
        "command": [
            "/usr/bin/bash",
            "-lc",
            f"printf '%s\\n' synthetic-check-{index}",
        ],
        "cwd": f"/workspace/synthetic-project-{index:03d}",
        "sandbox_permissions": "use_default",
        "tty": False,
    }


def candidate(
    index: int,
    *,
    category: str = "clearly_safe",
    outcome: str = "allow",
    group_id: str | None = None,
) -> dict:
    contract = synthetic_training.load_contract_identity(WORKTREE_ROOT)
    return synthetic_training.build_candidate(
        batch_id=synthetic_training.SYNTHETIC_BATCH_ID,
        generated_date="2026-08-15",
        prompt_sha256=contract.prompt_sha256,
        group_id=group_id or f"synthetic-group-{index:03d}",
        category=category,
        context=(
            f"Synthetic scenario {index}: the owner requested a bounded check "
            f"inside synthetic project {index}, with no external publication."
        ),
        evidence=(
            f"Synthetic evidence {index}: the workspace path was inspected, the "
            "target is confined to the project, and no secret value is involved."
        ),
        action=action(index),
        target={
            "outcome": outcome,
            "rationale": (
                "The synthetic evidence supports this bounded action."
                if outcome == "allow"
                else "The synthetic evidence does not support this risky action."
            ),
            "risk_tags": [] if outcome == "allow" else ["synthetic-risk"],
        },
    )


class SeedProjectionTests(unittest.TestCase):
    def test_only_seed_bodies_enter_projection(self) -> None:
        seed = tuple(
            SimpleNamespace(
                semantic_id=f"seed-{index}",
                canonical_payload={"marker": f"seed-body-{index}"},
            )
            for index in range(24)
        )
        holdout = tuple(
            SimpleNamespace(
                semantic_id=f"holdout-{index}",
                canonical_payload={"marker": f"holdout-body-{index}"},
            )
            for index in range(16)
        )
        batch = SimpleNamespace(
            by_partition=lambda name: seed if name == "seed" else holdout
        )
        decisions = {
            item.semantic_id: {
                "outcome": "allow",
                "rationale": "Synthetic fixture target.",
                "risk_tags": [],
            }
            for item in (*seed, *holdout)
        }

        projection = synthetic_training.build_seed_projection(batch, decisions)
        raw = synthetic_training._jsonl_bytes(projection)

        self.assertEqual(len(projection), 24)
        self.assertIn(b"seed-body-23", raw)
        self.assertNotIn(b"holdout-body", raw)
        self.assertTrue(
            all(row["usage"] == "seed_synthesis_reference_only" for row in projection)
        )


class CandidateContractTests(unittest.TestCase):
    def test_static_payload_target_and_identity_are_strict(self) -> None:
        contract = synthetic_training.load_contract_identity(WORKTREE_ROOT)
        row = candidate(1)
        accepted = synthetic_training.validate_candidate(
            row,
            batch_id=synthetic_training.SYNTHETIC_BATCH_ID,
            generated_date="2026-08-15",
            prompt_sha256=contract.prompt_sha256,
        )
        self.assertEqual(accepted["target"]["outcome"], "allow")

        cases = []
        unknown = copy.deepcopy(row)
        unknown["unknown"] = True
        cases.append(unknown)
        bad_target = copy.deepcopy(row)
        bad_target["target"]["outcome"] = "maybe"
        cases.append(bad_target)
        private_transport = copy.deepcopy(row)
        private_transport["input"]["encrypted_content"] = "opaque"
        cases.append(private_transport)
        non_string_group = copy.deepcopy(row)
        non_string_group["group_id"] = 7
        cases.append(non_string_group)
        real_workspace = copy.deepcopy(row)
        real_workspace["input"]["input"][-1]["content"][0]["text"] = (
            real_workspace["input"]["input"][-1]["content"][0]["text"].replace(
                "/workspace/synthetic-project-001", "/home/person/project"
            )
        )
        cases.append(real_workspace)
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(synthetic_training.SyntheticTrainingError):
                    synthetic_training.validate_candidate(
                        value,
                        batch_id=synthetic_training.SYNTHETIC_BATCH_ID,
                        generated_date="2026-08-15",
                        prompt_sha256=contract.prompt_sha256,
                    )

    def test_record_is_private_and_hash_bound(self) -> None:
        contract = synthetic_training.load_contract_identity(WORKTREE_ROOT)
        with tempfile.TemporaryDirectory() as temporary:
            private = Path(temporary) / "batch"
            private.mkdir(mode=0o700)
            prepare = {
                "status": "prepared",
                "batch_id": synthetic_training.SYNTHETIC_BATCH_ID,
                "generated_date": "2026-08-15",
                "prompt_sha256": contract.prompt_sha256,
                "sample_schema_sha256": contract.sample_schema_sha256,
            }
            (private / "prepare-receipt.json").write_bytes(
                synthetic_training._json_file_bytes(prepare)
            )
            os.chmod(private / "prepare-receipt.json", 0o600)

            result = synthetic_training.record_candidates(
                worktree_root=WORKTREE_ROOT,
                private_dir=private,
                candidates=[candidate(1), candidate(2)],
            )

            raw = (private / "candidates-v1.jsonl").read_bytes()
            receipt = json.loads((private / "candidate-receipt.json").read_bytes())
            self.assertEqual(result["unique_candidate_payloads"], 2)
            self.assertEqual(receipt["candidates_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual((private / "candidates-v1.jsonl").stat().st_mode & 0o777, 0o600)
            self.assertEqual((private / "candidate-receipt.json").stat().st_mode & 0o777, 0o600)


class FinalizationTests(unittest.TestCase):
    def _batch(self) -> list[dict]:
        rows = []
        for group in range(30):
            category = synthetic_training.CATEGORIES[group % len(synthetic_training.CATEGORIES)]
            outcome = (
                "allow"
                if category == "clearly_safe"
                or (category == "boundary_ambiguous" and group % 2 == 0)
                else "deny"
            )
            for variant in range(2):
                index = group * 10 + variant
                rows.append(
                    candidate(
                        index,
                        category=category,
                        outcome=outcome,
                        group_id=f"source-family-{group:03d}",
                    )
                )
        return rows

    def test_dedup_holdout_exclusion_and_group_safe_split_are_deterministic(self) -> None:
        rows = self._batch()
        rows.append(copy.deepcopy(rows[-1]))
        holdout_payloads = [rows[0]["input"]]

        first = synthetic_training.finalize_rows(rows, holdout_payloads, minimum=6)
        second = synthetic_training.finalize_rows(
            list(reversed(rows)), holdout_payloads, minimum=6
        )
        train, validation, stats, details = first

        self.assertEqual(first, second)
        self.assertEqual(stats["candidates"]["exact_duplicates_removed"], 1)
        self.assertEqual(stats["holdout_filter"]["excluded"], 1)
        self.assertEqual(stats["final_samples"], 59)
        self.assertTrue(train)
        self.assertTrue(validation)
        self.assertEqual(set(stats["categories"]), set(synthetic_training.CATEGORIES))
        self.assertEqual(set(stats["outcomes"]), {"allow", "deny"})
        self.assertTrue(
            all(set(item) == {"sample_id", "excluded", "reason", "maximum_holdout_score"} for item in details)
        )
        by_source: dict[str, set[tuple[str, str]]] = {}
        for row in (*train, *validation):
            by_source.setdefault(row["group_id"], set()).add(
                (row["split_group_id"], row["split"])
            )
        self.assertTrue(all(len(values) == 1 for values in by_source.values()))
        self.assertFalse(
            {row["sample_id"] for row in train}
            & {row["sample_id"] for row in validation}
        )

    def test_conflicting_targets_for_one_input_fail_closed(self) -> None:
        first = candidate(9, outcome="allow")
        second = copy.deepcopy(first)
        second["target"] = {
            "outcome": "deny",
            "rationale": "Conflicting synthetic target.",
            "risk_tags": ["conflict"],
        }
        with self.assertRaisesRegex(
            synthetic_training.SyntheticTrainingError,
            "duplicate_input_target_conflict",
        ):
            synthetic_training.finalize_rows(
                [first, second], [], minimum=1
            )

    def test_conflicting_bindings_for_one_input_fail_closed(self) -> None:
        first = candidate(10, group_id="source-family-first")
        second = candidate(10, group_id="source-family-second")
        self.assertEqual(first["payload_sha256"], second["payload_sha256"])
        with self.assertRaisesRegex(
            synthetic_training.SyntheticTrainingError,
            "duplicate_input_binding_conflict",
        ):
            synthetic_training.finalize_rows([first, second], [], minimum=1)

    def test_unique_candidate_limit_is_enforced(self) -> None:
        rows = [candidate(1), candidate(2)]
        with mock.patch.object(synthetic_training, "MAX_UNIQUE_CANDIDATES", 1):
            with self.assertRaisesRegex(
                synthetic_training.SyntheticTrainingError,
                "unique_candidate_limit_exceeded",
            ):
                synthetic_training.finalize_rows(rows, [], minimum=1)


if __name__ == "__main__":
    unittest.main()
