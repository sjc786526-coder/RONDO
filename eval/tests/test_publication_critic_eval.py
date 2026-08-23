from __future__ import annotations

import json
import math
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.archive import ArchiveError, RunArchive  # noqa: E402
from rondo_eval.publication_critic.boundaries import build_token_boundary_packets  # noqa: E402
from rondo_eval.publication_critic.contract import load_fixed_input_contract, load_sample_corpus  # noqa: E402
from rondo_eval.publication_critic.render import (  # noqa: E402
    InputOverflowError,
    build_messages,
    canonical_title_span,
    component_spans,
    fit_to_window,
)
from rondo_eval.publication_critic.runner import (  # noqa: E402
    CALIBRATION_SCHEMA,
    DECLARED_SLICES,
    FREEZE_SCHEMA,
    MEASUREMENT_METRICS,
    MODEL_REVISION,
    RunnerError,
    _IMPLEMENTATION_FILES,
    _INPUT_FILES,
    _require_committed_freeze,
    _frozen_runtime_identity,
    _validate_declared_measurement_slices,
    _validate_declared_quality_slices,
    _verify_scalar_parity,
    body_free_runner_exception,
    build_parser,
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
from rondo_eval.publication_critic.tokenization import ExactTokenizer  # noqa: E402


class _CharacterOffsetTokenizer:
    """Tiny tokenizer double with exact one-character offsets plus one special token."""

    pad_token_id = 151654
    bos_token_id = None
    eos_token_id = 151645
    all_special_ids = (151645, 151654)
    padding_side = "left"

    @staticmethod
    def apply_chat_template(
        messages: list[dict[str, str]],
        *,
        tokenize: bool,
        add_generation_prompt: bool,
    ) -> str:
        if tokenize or add_generation_prompt:
            raise AssertionError("test tokenizer received the wrong chat-template options")
        return "".join(
            f"<|{message['role']}|>\n{message['content']}\n"
            for message in messages
        )

    @staticmethod
    def __call__(
        rendered: str,
        *,
        add_special_tokens: bool,
        truncation: bool,
        return_attention_mask: bool,
        return_offsets_mapping: bool,
    ) -> dict[str, list]:
        if add_special_tokens or truncation or not return_attention_mask or not return_offsets_mapping:
            raise AssertionError("test tokenizer received the wrong encoding options")
        return {
            "input_ids": [151645, *range(200_000, 200_000 + len(rendered))],
            "attention_mask": [1] * (len(rendered) + 1),
            "offset_mapping": [(0, 0), *((index, index + 1) for index in range(len(rendered)))],
        }


class _StableScalarBackend:
    def __init__(self, *, batch_drift: float = 0.0) -> None:
        self.batch_drift = batch_drift

    def score(self, inputs: list[SimpleNamespace], *, padding_side: str) -> list[SimpleNamespace]:
        drift = self.batch_drift if len(inputs) > 1 and padding_side == "right" else 0.0
        return [
            SimpleNamespace(
                score=item.score + drift,
                raw_logit=item.score,
                latency_ms=1.0,
            )
            for item in inputs
        ]


class PublicationCriticEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixed = load_fixed_input_contract(REPO_ROOT)
        cls.corpus = load_sample_corpus(REPO_ROOT)

    def _valid_freeze(self) -> tuple[dict, Path]:
        asset_lock = (
            REPO_ROOT
            / "eval/model-locks/publication-critic/skywork-reward-v2-qwen3-1.7b-e51ea3e0.json"
        )
        inputs = file_manifest(REPO_ROOT, _INPUT_FILES)
        implementation = file_manifest(REPO_ROOT, _IMPLEMENTATION_FILES)
        sample_files = {
            relative: inputs[relative]
            for relative in (
                "eval/fixtures/publication-critic-v1/packets.jsonl",
                "eval/fixtures/publication-critic-v1/annotations.jsonl",
            )
        }
        freeze = {
            "schema": FREEZE_SCHEMA,
            "purpose": "Plan 054 M3-A2 exact Skywork base-model measurement freeze v3",
            "cohort_scope": "representative_and_boundary_examples_not_future_unseen_test",
            "supersedes": "rondo-publication-critic-measurement-freeze-v2",
            "asset_lock_sha256": sha256_file(asset_lock),
            "environment_lock_sha256": inputs[
                "eval/environments/publication-critic-plan054/uv.lock"
            ],
            "input_manifest": inputs,
            "input_manifest_sha256": combined_manifest_sha256(inputs),
            "implementation_manifest": implementation,
            "implementation_manifest_sha256": combined_manifest_sha256(implementation),
            "qualification_identity": {
                "packet_schema": {"name": "rondo-publication-packet", "revision": "v1"},
                "rubric": {
                    "name": "rondo-publication-qualification",
                    "revision": "v1",
                },
            },
            "model_identity": {
                "model": {
                    "name": "skywork-reward-v2-qwen3-1.7b",
                    "revision": MODEL_REVISION,
                },
                "tokenizer": {
                    "name": "skywork-reward-v2-qwen3-1.7b-tokenizer",
                    "revision": MODEL_REVISION,
                },
            },
            "scoring_identity": {
                "definition": {
                    "name": "skywork-reward-scalar-higher-better",
                    "revision": f"{MODEL_REVISION}-fp32-v3",
                },
                "input_template": {
                    "name": "rondo-publication-packet-render",
                    "revision": "v2-sha256-"
                    + inputs[
                        "eval/templates/publication-critic/render-contract-v2.json"
                    ],
                },
                "scalar_projection": {
                    "name": "stable-sigmoid-logits-index-0",
                    "revision": "v1",
                },
                "domain": {"min": 0.0, "max": 1.0},
                "threshold": 0.5,
                "pass_rule": "score_greater_than_or_equal_to_threshold",
            },
            "inference_contract": _frozen_runtime_identity(),
            "adopted_window_tokens": 16_384,
            "window_facts": {
                "model_card_training_and_recommended_inference_tokens": 16384,
                "model_config_max_position_embeddings": 40960,
                "tokenizer_model_max_length": 131072,
                "verified_context_forward_tokens": 16384,
                "overflow_policy": "drop_whole_oldest_prior_publications_then_explicitly_encode_additional_omission",
                "required_content_overflow": "typed_input_failure",
                "implicit_tokenizer_truncation": False,
            },
            "sample_identity": {
                "name": "rondo-publication-critic-m3a2-cohort",
                "revision": "v2-sha256-" + combined_manifest_sha256(sample_files),
                "calibration_count": 8,
                "measurement_count": 16,
                "token_census_only_count": 2,
                "class_counts": {
                    "new_event_completed": 6,
                    "new_event_incomplete": 6,
                    "existing_event_completed": 6,
                    "existing_event_incomplete": 6,
                },
                "label_counts": {"pass": 12, "rewrite": 12},
                "future_m3_b1a_unseen_test": False,
            },
            "temporary_threshold_source": {
                "run_id": "plan054-20260823T030000Z-calibration-v2",
                "calibration_result_sha256": "1" * 64,
                "rule": "maximize_balanced_accuracy_then_minimize_false_pass_then_maximize_threshold_v1",
                "rule_sha256": inputs[
                    "eval/templates/publication-critic/temporary-threshold-rule-v1.json"
                ],
                "measurement_labels_used": False,
            },
            "measurement_metrics": list(MEASUREMENT_METRICS),
            "declared_slices": list(DECLARED_SLICES),
        }
        return freeze, asset_lock

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
        self.assertNotIn("local_scope_title:", messages[1]["content"])
        self.assertNotIn("summary:", messages[0]["content"])

    def test_title_tokens_are_candidate_semantics_inside_user_packet_component(self) -> None:
        sample = self.corpus.by_id["pc-v1-meas-nc-b-pass"]
        tokenizer = ExactTokenizer(_CharacterOffsetTokenizer())
        tokenized = tokenizer.fit_packet(sample.packet, self.fixed.rubric)
        rendered = tokenized.rendered_chat

        spans = component_spans(rendered)
        title_start, title_end = canonical_title_span(rendered)
        packet_start, packet_end = spans["packet"]
        candidate_start, candidate_end = spans["candidate"]
        self.assertLessEqual(packet_start, title_start)
        self.assertEqual(title_end, packet_end)
        self.assertEqual(
            json.loads(rendered[title_start:title_end]),
            sample.packet["local_scope"]["title"],
        )
        self.assertEqual(
            tokenized.buckets["candidate"],
            (title_end - title_start) + (candidate_end - candidate_start),
        )
        self.assertEqual(
            tokenized.buckets["packet_framing"],
            (packet_end - packet_start) - (title_end - title_start),
        )
        self.assertEqual(tokenized.buckets["special_tokens"], 1)
        self.assertEqual(sum(tokenized.buckets.values()), len(tokenized.input_ids))

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

    def test_scalar_parity_covers_every_row_and_rejects_batch_drift(self) -> None:
        rows = [
            {"sample_id": "one", "tokenized": SimpleNamespace(score=0.2)},
            {"sample_id": "two", "tokenized": SimpleNamespace(score=0.8)},
            {"sample_id": "three", "tokenized": SimpleNamespace(score=0.6)},
        ]
        evidence, outputs = _verify_scalar_parity(
            _StableScalarBackend(),
            rows,
            batch_size=2,
        )
        self.assertEqual(evidence["row_count"], 3)
        self.assertEqual(len(evidence["rows"]), 3)
        self.assertEqual(evidence["max_absolute_projected_delta"], 0.0)
        self.assertEqual([output.score for output in outputs], [0.2, 0.8, 0.6])
        with self.assertRaisesRegex(RunnerError, "single versus standard_right_batch"):
            _verify_scalar_parity(
                _StableScalarBackend(batch_drift=0.01),
                rows,
                batch_size=2,
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
        freeze, asset_lock = self._valid_freeze()
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

    def test_measurement_freeze_rejects_identity_and_runtime_drift(self) -> None:
        runtime = {
            "device": "cpu",
            "dtype": "float32",
            "cpu_threads": 4,
            "batch_size": 4,
        }
        freeze, asset_lock = self._valid_freeze()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "freeze.json"
            path.write_text(json.dumps(freeze), encoding="utf-8")
            self.assertEqual(
                verify_measurement_freeze(path, REPO_ROOT, asset_lock, runtime)[
                    "schema"
                ],
                FREEZE_SCHEMA,
            )

            freeze["qualification_identity"]["rubric"]["revision"] = "v1-sha256-wrong"
            path.write_text(json.dumps(freeze), encoding="utf-8")
            with self.assertRaisesRegex(RunnerError, "qualification identity drifted"):
                verify_measurement_freeze(path, REPO_ROOT, asset_lock, runtime)

            freeze, _ = self._valid_freeze()
            freeze["inference_contract"]["output_shape"] = [1]
            path.write_text(json.dumps(freeze), encoding="utf-8")
            with self.assertRaisesRegex(RunnerError, "inference identity drifted"):
                verify_measurement_freeze(path, REPO_ROOT, asset_lock, runtime)

            freeze, _ = self._valid_freeze()
            path.write_text(json.dumps(freeze), encoding="utf-8")
            drifted_runtime = {**runtime, "batch_size": 2}
            with self.assertRaisesRegex(RunnerError, "CLI runtime differs"):
                verify_measurement_freeze(
                    path,
                    REPO_ROOT,
                    asset_lock,
                    drifted_runtime,
                )

    def test_measurement_freeze_binds_actual_calibration_result(self) -> None:
        freeze, asset_lock = self._valid_freeze()
        calibration = {
            "schema": CALIBRATION_SCHEMA,
            "run_id": freeze["temporary_threshold_source"]["run_id"],
            "model_revision": MODEL_REVISION,
            "input_manifest_sha256": freeze["input_manifest_sha256"],
            "temporary_threshold": {
                "rule": freeze["temporary_threshold_source"]["rule"],
                "threshold": freeze["scoring_identity"]["threshold"],
                "calibration_count": 8,
            },
        }
        runtime = {
            "device": "cpu",
            "dtype": "float32",
            "cpu_threads": 4,
            "batch_size": 4,
        }
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            freeze_path = root / "freeze.json"
            calibration_path = root / "calibration-result.json"
            calibration_path.write_text(json.dumps(calibration), encoding="utf-8")
            freeze["temporary_threshold_source"]["calibration_result_sha256"] = (
                sha256_file(calibration_path)
            )
            freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
            self.assertEqual(
                verify_measurement_freeze(
                    freeze_path,
                    REPO_ROOT,
                    asset_lock,
                    runtime,
                    calibration_path,
                )["schema"],
                FREEZE_SCHEMA,
            )

            calibration["temporary_threshold"]["threshold"] = 0.75
            calibration_path.write_text(json.dumps(calibration), encoding="utf-8")
            freeze["temporary_threshold_source"]["calibration_result_sha256"] = (
                sha256_file(calibration_path)
            )
            freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
            with self.assertRaisesRegex(RunnerError, "calibration result identity drifted"):
                verify_measurement_freeze(
                    freeze_path,
                    REPO_ROOT,
                    asset_lock,
                    runtime,
                    calibration_path,
                )

    def test_v2_cli_defaults_match_frozen_runtime(self) -> None:
        common = [
            "--snapshot",
            "/tmp/model",
            "--asset-lock",
            "/tmp/lock.json",
            "--archive-root",
            "/tmp/archive",
            "--run-id",
            "plan054-test",
        ]
        calibration = build_parser().parse_args(["calibrate", *common])
        measurement = build_parser().parse_args(
            [
                "measure",
                *common,
                "--freeze",
                "/tmp/freeze.json",
                "--calibration-result",
                "/tmp/calibration.json",
                "--tracked-result",
                "/tmp/result.json",
            ]
        )
        for parsed in (calibration, measurement):
            self.assertEqual(parsed.device, "cpu")
            self.assertEqual(parsed.dtype, "float32")
            self.assertEqual(parsed.cpu_threads, 4)
            self.assertEqual(parsed.batch_size, 4)

    def test_measurement_rejects_noncanonical_freeze_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            external = Path(temporary) / "measurement-freeze-v3.json"
            external.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(RunnerError, "canonical tracked path"):
                _require_committed_freeze(REPO_ROOT, external)

    def test_declared_measurement_slices_exist_in_cohort_and_quality(self) -> None:
        measurement = [
            {"sample": sample}
            for sample in self.corpus.samples
            if sample.annotation["data_role"] == "m3a2_measurement"
        ]
        _validate_declared_measurement_slices(measurement)
        quality = {"by_slice": {name: {} for name in DECLARED_SLICES}}
        _validate_declared_quality_slices(quality)

        absent = SimpleNamespace(annotation={"slices": []})
        with self.assertRaisesRegex(RunnerError, "absent from the frozen cohort"):
            _validate_declared_measurement_slices([{"sample": absent}])
        quality["by_slice"].pop(DECLARED_SLICES[-1])
        with self.assertRaisesRegex(RunnerError, "absent from the quality result"):
            _validate_declared_quality_slices(quality)


if __name__ == "__main__":
    unittest.main()
