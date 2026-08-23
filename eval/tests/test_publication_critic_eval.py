from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.archive import ArchiveError, RunArchive  # noqa: E402
from rondo_eval.publication_critic.boundaries import build_token_boundary_packets  # noqa: E402
from rondo_eval.publication_critic.contract import load_fixed_input_contract, load_sample_corpus  # noqa: E402
from rondo_eval.publication_critic.render import (  # noqa: E402
    InputOverflowError,
    build_messages,
    fit_to_window,
)
from rondo_eval.publication_critic.runner import (  # noqa: E402
    FREEZE_SCHEMA,
    RunnerError,
    _IMPLEMENTATION_FILES,
    _INPUT_FILES,
    body_free_runner_exception,
    combined_manifest_sha256,
    file_manifest,
    verify_measurement_freeze,
)
from rondo_eval.publication_critic.identity import sha256_file  # noqa: E402
from rondo_eval.publication_critic.scoring import (  # noqa: E402
    derive_temporary_threshold,
    project_logit,
    summarize_measurement,
)


class PublicationCriticEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixed = load_fixed_input_contract(REPO_ROOT)
        cls.corpus = load_sample_corpus(REPO_ROOT)

    def test_renderer_has_no_system_or_supervision_and_complete_candidate(self) -> None:
        sample = self.corpus.samples[0]
        messages = build_messages(sample.packet, self.fixed.rubric)
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])
        rendered = json.dumps(messages, ensure_ascii=False)
        for forbidden in (
            "expected_verdict",
            "data_role",
            "pair_direction",
            "rationale_anchor",
            sample.sample_id,
        ):
            self.assertNotIn(forbidden, rendered)
        self.assertIn(sample.packet["local_scope"]["title"], messages[0]["content"])
        self.assertIn(sample.packet["candidate"]["summary"], messages[1]["content"])

    def test_overflow_drops_only_whole_oldest_publications(self) -> None:
        sample = next(
            sample
            for sample in self.corpus.samples
            if sample.packet["continuity"]["state"] == "available"
            and len(sample.packet["continuity"]["prior_publications"]) >= 2
        )
        original = sample.packet["continuity"]["prior_publications"]

        def bounded_count(messages: object) -> int:
            rendered = json.dumps(messages, ensure_ascii=False)
            return 200 if original[0]["summary"] in rendered else 100

        plan = fit_to_window(sample.packet, self.fixed.rubric, bounded_count, adopted_window=150)
        rendered = json.dumps(plan.messages, ensure_ascii=False)
        self.assertEqual(plan.dropped_oldest_publications, 1)
        self.assertNotIn(original[0]["summary"], rendered)
        self.assertIn(original[1]["summary"], rendered)
        self.assertIn("model_window_additional_oldest_omitted: 1", rendered)
        self.assertIn(sample.packet["candidate"]["summary"], rendered)

    def test_required_content_overflow_is_typed_failure(self) -> None:
        sample = next(
            sample
            for sample in self.corpus.samples
            if sample.packet["continuity"]["state"] == "not_applicable"
        )
        with self.assertRaises(InputOverflowError):
            fit_to_window(sample.packet, self.fixed.rubric, lambda _messages: 2, adopted_window=1)

    def test_census_boundaries_hit_product_scalar_and_byte_caps(self) -> None:
        boundaries = build_token_boundary_packets(
            [sample.packet for sample in self.corpus.samples],
            self.fixed.product_limits,
        )
        scalar, byte = boundaries
        for field, value in (
            ("title", scalar.packet["local_scope"]["title"]),
            ("summary", scalar.packet["candidate"]["summary"]),
            ("handoff", scalar.packet["candidate"]["handoff"]),
        ):
            self.assertEqual(len(value), self.fixed.product_limits[field]["max_scalars"])
        for field, value in (
            ("title", byte.packet["local_scope"]["title"]),
            ("summary", byte.packet["candidate"]["summary"]),
            ("handoff", byte.packet["candidate"]["handoff"]),
        ):
            self.assertEqual(
                len(value.encode("utf-8")),
                self.fixed.product_limits[field]["max_bytes"],
            )
            self.assertLessEqual(len(value), self.fixed.product_limits[field]["max_scalars"])
        self.assertEqual(
            len(byte.packet["continuity"]["prior_publications"]),
            self.fixed.product_limits["max_prior_publications"],
        )

    def test_stable_sigmoid_and_calibration_only_threshold(self) -> None:
        self.assertEqual(project_logit(0.0), 0.5)
        self.assertTrue(math.isclose(project_logit(1000.0), 1.0))
        self.assertTrue(math.isclose(project_logit(-1000.0), 0.0))
        rows = [
            {"data_role": "calibration", "expected_label": "rewrite", "score": 0.1},
            {"data_role": "calibration", "expected_label": "rewrite", "score": 0.3},
            {"data_role": "calibration", "expected_label": "pass", "score": 0.7},
            {"data_role": "calibration", "expected_label": "pass", "score": 0.9},
        ]
        threshold = derive_temporary_threshold(rows)
        self.assertEqual(threshold["threshold"], 0.7)
        self.assertEqual(threshold["balanced_accuracy"], 1.0)
        with self.assertRaisesRegex(ValueError, "calibration"):
            derive_temporary_threshold([{**rows[0], "data_role": "measurement"}])

    def test_measurement_summary_reports_threshold_free_and_error_metrics(self) -> None:
        rows = [
            {
                "data_role": "measurement",
                "expected_label": "pass",
                "score": 0.9,
                "raw_logit": 2.0,
                "latency_ms": 10.0,
                "sample_id": "pass-1",
                "publication_class": "new_event_completed",
                "pair_id": "pair-1",
                "slices": ["new"],
            },
            {
                "data_role": "measurement",
                "expected_label": "rewrite",
                "score": 0.8,
                "raw_logit": 1.0,
                "latency_ms": 20.0,
                "sample_id": "rewrite-1",
                "publication_class": "new_event_completed",
                "pair_id": "pair-1",
                "slices": ["existing"],
            },
            {
                "data_role": "measurement",
                "expected_label": "pass",
                "score": 0.85,
                "raw_logit": 0.5,
                "latency_ms": 30.0,
                "sample_id": "pass-2",
                "publication_class": "existing_event_incomplete",
                "pair_id": "pair-2",
                "slices": ["new"],
            },
            {
                "data_role": "measurement",
                "expected_label": "rewrite",
                "score": 0.2,
                "raw_logit": -1.0,
                "latency_ms": 40.0,
                "sample_id": "rewrite-2",
                "publication_class": "existing_event_incomplete",
                "pair_id": "pair-2",
                "slices": ["new"],
            },
        ]
        summary = summarize_measurement(rows, 0.5)
        self.assertEqual(summary["overall"]["confusion"]["false_pass"], 1)
        self.assertEqual(summary["overall"]["roc_auc"], 1.0)
        self.assertEqual(set(summary["by_slice"]), {"existing", "new"})
        self.assertEqual(summary["boundary_pairs"]["strict_wins"], 2)
        self.assertEqual(summary["latency_ms"]["p95"], 40.0)

    def test_archive_is_write_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run = RunArchive(root, "plan054-20260822T120000Z-unit").create()
            path = run.write_json("result.json", {"finite": True})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(ArchiveError):
                run.write_json("result.json", {"finite": False})
            with self.assertRaises(ArchiveError):
                RunArchive(root, run.run_id).create()

    def test_runner_failure_projection_exposes_only_fixed_runner_errors(self) -> None:
        self.assertEqual(
            body_free_runner_exception(RunnerError("scalar parity failed: repeat")),
            {
                "failure_kind": "RunnerError",
                "message": "scalar parity failed: repeat",
            },
        )
        self.assertEqual(
            body_free_runner_exception(ValueError("packet body must stay hidden")),
            {
                "failure_kind": "ValueError",
                "message": "unexpected model runner failure",
            },
        )

    def test_freeze_manifests_cover_inputs_and_implementation(self) -> None:
        inputs = file_manifest(REPO_ROOT, _INPUT_FILES)
        implementation = file_manifest(REPO_ROOT, _IMPLEMENTATION_FILES)
        self.assertEqual(set(inputs), set(_INPUT_FILES))
        self.assertEqual(set(implementation), set(_IMPLEMENTATION_FILES))
        self.assertRegex(combined_manifest_sha256(inputs), r"^[0-9a-f]{64}$")

    def test_measurement_freeze_rejects_implementation_drift(self) -> None:
        asset_lock = (
            REPO_ROOT
            / "eval/model-locks/publication-critic/skywork-reward-v2-qwen3-1.7b-e51ea3e0.json"
        )
        freeze = {
            "schema": FREEZE_SCHEMA,
            "input_manifest": file_manifest(REPO_ROOT, _INPUT_FILES),
            "implementation_manifest": file_manifest(REPO_ROOT, _IMPLEMENTATION_FILES),
            "asset_lock_sha256": sha256_file(asset_lock),
            "adopted_window_tokens": 16_384,
            "scoring_identity": {
                "threshold": 0.5,
                "pass_rule": "score_greater_than_or_equal_to_threshold",
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "freeze.json"
            path.write_text(json.dumps(freeze), encoding="utf-8")
            self.assertEqual(
                verify_measurement_freeze(path, REPO_ROOT, asset_lock)["schema"],
                FREEZE_SCHEMA,
            )
            first = next(iter(freeze["implementation_manifest"]))
            freeze["implementation_manifest"][first] = "0" * 64
            path.write_text(json.dumps(freeze), encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "implementation manifest drifted"):
                verify_measurement_freeze(path, REPO_ROOT, asset_lock)


if __name__ == "__main__":
    unittest.main()
