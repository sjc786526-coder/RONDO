from __future__ import annotations

from collections import Counter, defaultdict
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.contract import (  # noqa: E402
    PublicationCriticContractError,
    load_fixed_input_contract,
    load_sample_corpus,
)


SUPERVISION_KEYS = {
    "data_role",
    "publication_class",
    "completion_state",
    "expected_verdict",
    "pair_id",
    "pair_direction",
    "slices",
    "rationale_anchor",
    "source_identity",
    "reviewer_identity",
}


class PublicationCriticContractTests(unittest.TestCase):
    def test_loads_frozen_input_and_balanced_atomic_pairs(self) -> None:
        fixed = load_fixed_input_contract(REPO_ROOT)
        self.assertIn("Model-visible allowlist", fixed.input_contract)
        self.assertIn("transcript, reasoning, private context", fixed.input_contract)
        self.assertIn("Useful state transfer", fixed.rubric)
        self.assertIn("Do not claim to verify factual truth", fixed.rubric)
        self.assertEqual(fixed.render_contract["revision"], "v2")
        self.assertEqual(fixed.render_contract["messages"]["system"], "absent")
        self.assertEqual(fixed.render_contract["messages"]["count"], 2)
        self.assertEqual(
            fixed.render_contract["messages"]["user"]["components"]["packet"]["fields"],
            ("qualification", "actor_role", "target_kind", "local_scope.title"),
        )
        self.assertEqual(
            fixed.render_contract["messages"]["assistant"]["fields"],
            ("candidate.summary", "candidate.handoff"),
        )
        self.assertEqual(
            fixed.render_contract["token_accounting"]["canonical_title"],
            {
                "source": "local_scope.title",
                "message_role": "user",
                "render_component": "packet",
                "token_bucket": "candidate",
            },
        )
        self.assertEqual(
            fixed.render_contract["render_compatibility"]["message_roles"],
            ("user", "assistant"),
        )
        self.assertEqual(fixed.render_contract["context"]["adopted_window_tokens"], 16_384)
        self.assertEqual(fixed.render_contract["context"]["candidate_truncation"], "forbidden")
        self.assertEqual(
            fixed.render_contract["context"]["overflow"]["unit"],
            "whole_prior_publication",
        )
        self.assertEqual(fixed.render_contract["padding"]["binding"], "scoring_identity")
        self.assertEqual(fixed.product_limits["title"]["max_scalars"], 213)
        self.assertEqual(fixed.product_limits["summary"]["max_bytes"], 8_015)
        self.assertEqual(fixed.product_limits["max_prior_publications"], 4)

        corpus = load_sample_corpus(REPO_ROOT)
        self.assertEqual(len(corpus.samples), 24)
        self.assertEqual(len(corpus.by_id), 24)
        self.assertEqual(
            Counter(sample.annotation["data_role"] for sample in corpus.samples),
            {"m3a2_calibration": 8, "m3a2_measurement": 16},
        )
        self.assertEqual(
            Counter(sample.annotation["publication_class"] for sample in corpus.samples),
            {
                "new_event_completed": 6,
                "new_event_incomplete": 6,
                "existing_event_completed": 6,
                "existing_event_incomplete": 6,
            },
        )
        self.assertEqual(
            Counter(sample.annotation["expected_verdict"] for sample in corpus.samples),
            {"pass": 12, "rewrite": 12},
        )

        pairs = defaultdict(list)
        for sample in corpus.samples:
            pairs[sample.annotation["pair_id"]].append(sample)
        self.assertEqual(len(pairs), 12)
        for pair in pairs.values():
            self.assertEqual(
                {sample.annotation["expected_verdict"] for sample in pair},
                {"pass", "rewrite"},
            )
            contexts = [
                {key: value for key, value in sample.packet.items() if key != "candidate"}
                for sample in pair
            ]
            self.assertEqual(contexts[0], contexts[1])

    def test_wire_covers_publication_and_evidence_boundaries(self) -> None:
        corpus = load_sample_corpus(REPO_ROOT)
        packets = [sample.packet for sample in corpus.samples]
        annotations = [sample.annotation for sample in corpus.samples]

        self.assertEqual({packet["actor_role"] for packet in packets}, {"root", "member"})
        self.assertEqual({packet["target_kind"] for packet in packets}, {"new_event", "existing_event"})
        self.assertEqual(
            {packet["continuity"]["state"] for packet in packets},
            {"not_applicable", "available", "unavailable"},
        )
        available = [packet["continuity"] for packet in packets if packet["continuity"]["state"] == "available"]
        self.assertEqual(
            {continuity["freshness"] for continuity in available},
            {"current", "known_stale"},
        )
        self.assertEqual(
            {continuity["coverage"]["state"] for continuity in available},
            {"complete", "partial"},
        )

        fact_references = [
            prior["evidence"]["fact_references"]
            for continuity in available
            for prior in continuity["prior_publications"]
        ]
        self.assertIn("none", {reference["state"] for reference in fact_references})
        self.assertIn("present", {reference["state"] for reference in fact_references})
        self.assertTrue(
            any(
                reference["state"] == "present" and reference["count_omitted"]
                for reference in fact_references
            )
        )
        self.assertTrue(any(packet["candidate"]["handoff"] is None for packet in packets))
        self.assertTrue(any(packet["candidate"]["handoff"] == "" for packet in packets))
        self.assertTrue(any("unicode" in annotation["slices"] for annotation in annotations))
        self.assertTrue(any("long" in annotation["slices"] for annotation in annotations))
        self.assertTrue(any("partial" == continuity["coverage"]["state"] for continuity in available))
        self.assertTrue(
            any(
                packet["continuity"]["state"] == "unavailable"
                and packet["continuity"]["freshness"] == "known_stale"
                for packet in packets
            )
        )
        self.assertEqual(
            {annotation["data_role"] for annotation in annotations},
            {"m3a2_calibration", "m3a2_measurement"},
        )

    def test_packets_are_physically_free_of_supervision(self) -> None:
        packet_path = REPO_ROOT / "eval/fixtures/publication-critic-v1/packets.jsonl"
        annotation_path = REPO_ROOT / "eval/fixtures/publication-critic-v1/annotations.jsonl"
        packet_text = packet_path.read_text(encoding="utf-8")
        annotation_text = annotation_path.read_text(encoding="utf-8")
        for key in SUPERVISION_KEYS:
            self.assertNotIn(f'"{key}"', packet_text)
        self.assertIn('"expected_verdict"', annotation_text)
        self.assertNotIn('"packet"', annotation_text)

    def test_rejects_supervision_in_packet(self) -> None:
        with self._copied_repo() as root:
            rows = self._read_jsonl(root / "eval/fixtures/publication-critic-v1/packets.jsonl")
            rows[0]["packet"]["expected_verdict"] = "pass"
            self._write_jsonl(root / "eval/fixtures/publication-critic-v1/packets.jsonl", rows)
            with self.assertRaisesRegex(PublicationCriticContractError, "supervision keys"):
                load_sample_corpus(root)

    def test_rejects_unknown_nested_packet_key(self) -> None:
        with self._copied_repo() as root:
            rows = self._read_jsonl(root / "eval/fixtures/publication-critic-v1/packets.jsonl")
            rows[0]["packet"]["candidate"]["private_trace"] = "forbidden"
            self._write_jsonl(root / "eval/fixtures/publication-critic-v1/packets.jsonl", rows)
            with self.assertRaisesRegex(PublicationCriticContractError, "keys differ"):
                load_sample_corpus(root)

    def test_rejects_packet_annotation_join_mismatch(self) -> None:
        with self._copied_repo() as root:
            path = root / "eval/fixtures/publication-critic-v1/annotations.jsonl"
            rows = self._read_jsonl(path)
            self._write_jsonl(path, rows[:-1])
            with self.assertRaisesRegex(PublicationCriticContractError, "sample_id mismatch"):
                load_sample_corpus(root)

    def test_rejects_boolean_for_integer_field(self) -> None:
        with self._copied_repo() as root:
            path = root / "eval/fixtures/publication-critic-v1/packets.jsonl"
            rows = self._read_jsonl(path)
            row = next(
                row
                for row in rows
                if row["packet"]["continuity"]["state"] == "available"
            )
            row["packet"]["continuity"]["source_team_revision"] = True
            self._write_jsonl(path, rows)
            with self.assertRaisesRegex(PublicationCriticContractError, "non-negative integer"):
                load_sample_corpus(root)

    def test_rejects_render_contract_drift(self) -> None:
        with self._copied_repo() as root:
            path = root / "eval/templates/publication-critic/render-contract-v2.json"
            render = json.loads(path.read_text(encoding="utf-8"))
            render["context"]["adopted_window_tokens"] = 8192
            path.write_text(json.dumps(render), encoding="utf-8")
            with self.assertRaisesRegex(PublicationCriticContractError, "16384"):
                load_fixed_input_contract(root)

    class _CopiedRepo:
        def __init__(self) -> None:
            self.temp = tempfile.TemporaryDirectory()
            self.root = Path(self.temp.name)

        def __enter__(self) -> Path:
            shutil.copytree(
                REPO_ROOT / "eval/fixtures/publication-critic-v1",
                self.root / "eval/fixtures/publication-critic-v1",
            )
            shutil.copytree(
                REPO_ROOT / "eval/templates/publication-critic",
                self.root / "eval/templates/publication-critic",
            )
            return self.root

        def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
            self.temp.cleanup()

    @classmethod
    def _copied_repo(cls) -> _CopiedRepo:
        return cls._CopiedRepo()

    @staticmethod
    def _read_jsonl(path: Path) -> list[dict]:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    @staticmethod
    def _write_jsonl(path: Path, rows: list[dict]) -> None:
        path.write_text(
            "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
            encoding="utf-8",
        )


if __name__ == "__main__":
    unittest.main()
