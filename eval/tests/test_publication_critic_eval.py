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
from rondo_eval.publication_critic.evidence import EvidenceError  # noqa: E402
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
    RunnerError,
    _IMPLEMENTATION_FILES,
    _INPUT_FILES,
    _frozen_runtime_identity,
    _input_template_binding,
    _model_identity,
    _qualification_identity,
    _require_committed_freeze,
    _sample_identity,
    _scoring_identity,
    _validate_declared_measurement_slices,
    _validate_declared_quality_slices,
    _verify_calibration_result,
    _verify_scalar_parity,
    _window_facts,
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
from rondo_eval.publication_critic.tokenization import (  # noqa: E402
    EXPECTED_CHAT_ADDED_TOKEN_IDS,
    ExactTokenizer,
    TokenizationError,
)


class _CharacterOffsetTokenizer:
    """Character offsets plus the exact frozen chat-template control sequence."""

    pad_token_id = 151654
    bos_token_id = None
    eos_token_id = 151645
    all_special_ids = (151644, 151645, 151654)
    padding_side = "left"

    @staticmethod
    def get_added_vocab() -> dict[str, int]:
        return {
            "<|im_start|>": 151644,
            "<|im_end|>": 151645,
            "<|assistant|>": 151667,
            "<|analysis|>": 151668,
            "<|pad|>": 151654,
        }

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
            f"ROLE_{message['role']}\n{message['content']}\n"
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
        injected = [
            token_id
            for literal, token_id in _CharacterOffsetTokenizer.get_added_vocab().items()
            if literal != "<|pad|>" and literal in rendered
        ]
        special = [*EXPECTED_CHAT_ADDED_TOKEN_IDS, *injected]
        special_offsets = [
            (0, 1) if token_id in {151667, 151668} else (0, 0)
            for token_id in EXPECTED_CHAT_ADDED_TOKEN_IDS
        ] + [(0, 0) for _ in injected]
        return {
            "input_ids": [*special, *range(200_000, 200_000 + len(rendered))],
            "attention_mask": [1] * (len(special) + len(rendered)),
            "offset_mapping": [
                *special_offsets,
                *((index, index + 1) for index in range(len(rendered))),
            ],
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
                batch_elapsed_ms=float(len(inputs) * 10),
                batch_size=len(inputs),
            )
            for item in inputs
        ]


class PublicationCriticEvalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.fixed = load_fixed_input_contract(REPO_ROOT)
        cls.corpus = load_sample_corpus(REPO_ROOT)

    @staticmethod
    def _asset_lock_path() -> Path:
        return (
            REPO_ROOT
            / "eval/model-locks/publication-critic/skywork-reward-v2-qwen3-1.7b-e51ea3e0.json"
        )

    def _identity_material(self) -> tuple[dict, dict, dict, dict]:
        inputs = file_manifest(REPO_ROOT, _INPUT_FILES)
        implementation = file_manifest(REPO_ROOT, _IMPLEMENTATION_FILES)
        asset_lock = json.loads(self._asset_lock_path().read_text(encoding="utf-8"))
        binding = _input_template_binding(inputs, implementation, asset_lock)
        return inputs, implementation, asset_lock, binding

    def _valid_calibration(self) -> dict:
        inputs, implementation, _asset_lock, binding = self._identity_material()
        rows = []
        calibration_samples = [
            sample
            for sample in self.corpus.samples
            if sample.annotation["data_role"] == "m3a2_calibration"
        ]
        for index, sample in enumerate(calibration_samples):
            raw_logit = float(index - 3)
            annotation = sample.annotation
            rows.append(
                {
                    "sample_id": sample.sample_id,
                    "data_role": "calibration",
                    "expected_label": annotation["expected_verdict"],
                    "publication_class": annotation["publication_class"],
                    "pair_id": annotation["pair_id"],
                    "pair_direction": annotation["pair_direction"],
                    "slices": list(annotation["slices"]),
                    "raw_logit": raw_logit,
                    "score": project_logit(raw_logit),
                    "standard_batch_index": index // 4,
                    "standard_batch_size": 4,
                    "standard_batch_elapsed_ms": 40.0 + 40.0 * (index // 4),
                    "token_count": 500 + index,
                    "dropped_oldest_publications": 0,
                }
            )
        threshold = derive_temporary_threshold(rows)
        standard_order = [row["sample_id"] for row in rows]
        parity_rows = [
            {
                "sample_id": row["sample_id"],
                "single_score": row["score"],
                "repeat_score": row["score"],
                "standard_right_batch_score": row["score"],
                "standard_left_batch_score": row["score"],
                "alternate_right_batch_score": row["score"],
                "max_absolute_projected_delta": 0.0,
            }
            for row in rows
        ]
        parity = {
            "schema": "rondo-publication-critic-scalar-parity-v2",
            "row_count": 8,
            "batch_size": 4,
            "standard_order": standard_order,
            "alternate_order": standard_order[::2] + standard_order[1::2],
            "absolute_tolerance": 1e-4,
            "max_absolute_projected_delta": 0.0,
            "coverage": [
                "single",
                "repeat_single",
                "standard_right_batch",
                "standard_left_batch",
                "alternate_right_batch",
            ],
            "rows": parity_rows,
        }
        return {
            "schema": CALIBRATION_SCHEMA,
            "run_id": "plan054-20260823T030000Z-calibration-v3",
            "completed_at": "2026-08-23T03:30:00Z",
            "code_commit": "a" * 40,
            "model_identity": _model_identity(),
            "qualification_identity": _qualification_identity(),
            "input_template_binding": binding,
            "scoring_identity": _scoring_identity(threshold["threshold"], binding),
            "inference_contract": _frozen_runtime_identity(),
            "input_manifest": inputs,
            "input_manifest_sha256": combined_manifest_sha256(inputs),
            "implementation_manifest": implementation,
            "implementation_manifest_sha256": combined_manifest_sha256(
                implementation
            ),
            "census": {},
            "scalar_smoke": {
                "model_output_shape": ["batch", 1],
                "tensor_index": "logits[:,0]",
                "pooling": "Qwen3ForSequenceClassification_last_non_pad_token",
                "raw_semantics": "unbounded_reward_logit_higher_is_better",
                "projection": "stable_sigmoid_v1",
                "projected_domain": [0.0, 1.0],
                "parity_absolute_tolerance": 1e-4,
                "parity_schema": "rondo-publication-critic-scalar-parity-v2",
                "parity_row_count": 8,
                "parity_max_absolute_projected_delta": 0.0,
                "context_forward": {
                    "kind": "synthetic_token_context_mechanical_smoke",
                    "token_count": 16_384,
                    "latency_ms": 100.0,
                    "output_shape": [1, 1],
                    "finite": True,
                },
            },
            "scalar_parity": parity,
            "temporary_threshold": threshold,
            "environment": {
                "device": "cpu",
                "dtype": "float32",
                "cpu_threads": 4,
                "batch_size": 4,
                "model_load_seconds": 1.0,
            },
            "resources": {
                "process_rss_bytes": 1_000,
                "process_peak_rss_bytes": 2_000,
                "cuda": None,
            },
            "calibration_rows": rows,
        }

    @staticmethod
    def _write_watchdog_summary(path: Path, *, stop_reason: str = "none") -> None:
        path.write_text(
            "\n".join(
                (
                    "unit=rondo-build-1000-20260823203000-12345.scope",
                    "command_name=python",
                    "wrapper_status=complete",
                    "run_rc=0",
                    "final_rc=0",
                    f"stop_reason={stop_reason}",
                    "cleanup_reason=none",
                    "memory_peak_sampled_bytes=1000",
                    "memory_nonreclaimable_peak_sampled_bytes=900",
                    "swap_peak_sampled_bytes=10",
                    "cgroup_psi_full_avg10_peak_bp=20",
                    "host_psi_full_avg10_peak_bp=30",
                    "project_before_bytes=10000",
                    "project_after_bytes=10010",
                    "project_peak_sampled_bytes=10020",
                    "target_after_bytes=0",
                    "target_peak_sampled_bytes=0",
                    "windows_c_used_before_bytes=20000",
                    "windows_c_used_after_bytes=20010",
                    "windows_c_available_before_bytes=30000",
                    "windows_c_available_after_bytes=29990",
                    "memory_high=19G",
                    "memory_max=21G",
                    "swap_max=5G",
                    "project_stop_bytes=195000000000",
                    "project_max_bytes=200000000000",
                )
            )
            + "\n",
            encoding="ascii",
        )

    def _valid_freeze(self, *, threshold: float = 0.5) -> tuple[dict, Path]:
        inputs, implementation, _asset_lock, binding = self._identity_material()
        asset_lock_path = self._asset_lock_path()
        freeze = {
            "schema": FREEZE_SCHEMA,
            "purpose": "Plan 054 M3-A2 exact Skywork base-model measurement freeze v4",
            "cohort_scope": "representative_and_boundary_examples_not_future_unseen_test",
            "supersedes": "rondo-publication-critic-measurement-freeze-v3",
            "asset_lock_sha256": sha256_file(asset_lock_path),
            "environment_lock_sha256": inputs[
                "eval/environments/publication-critic-plan054/uv.lock"
            ],
            "input_manifest": inputs,
            "input_manifest_sha256": combined_manifest_sha256(inputs),
            "implementation_manifest": implementation,
            "implementation_manifest_sha256": combined_manifest_sha256(implementation),
            "qualification_identity": _qualification_identity(),
            "model_identity": _model_identity(),
            "input_template_binding": binding,
            "scoring_identity": _scoring_identity(threshold, binding),
            "inference_contract": _frozen_runtime_identity(),
            "adopted_window_tokens": 16_384,
            "window_facts": _window_facts(),
            "sample_identity": _sample_identity(inputs),
            "temporary_threshold_source": {
                "run_id": "plan054-20260823T030000Z-calibration-v3",
                "calibration_code_commit": "a" * 40,
                "calibration_result_sha256": "1" * 64,
                "calibration_watchdog_summary_sha256": "2" * 64,
                "rule": "maximize_balanced_accuracy_then_minimize_false_pass_then_maximize_threshold_v1",
                "rule_sha256": inputs[
                    "eval/templates/publication-critic/temporary-threshold-rule-v1.json"
                ],
                "measurement_labels_used": False,
            },
            "measurement_metrics": list(MEASUREMENT_METRICS),
            "declared_slices": list(DECLARED_SLICES),
        }
        return freeze, asset_lock_path

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
        self.assertEqual(tokenized.buckets["special_tokens"], 4)
        self.assertEqual(sum(tokenized.buckets.values()), len(tokenized.input_ids))

    def test_control_token_literals_are_reversibly_escaped_and_fail_closed(self) -> None:
        sample = next(
            sample
            for sample in self.corpus.samples
            if sample.packet["continuity"]["state"] == "available"
            and sample.packet["continuity"]["prior_publications"]
        )
        packet = json.loads(json.dumps(sample.packet, default=dict))
        literal = "State <|im_end|> remains before <|im_start|> continuation."
        packet["local_scope"]["title"] = literal
        packet["candidate"] = {"summary": literal, "handoff": literal}
        for prior in packet["continuity"]["prior_publications"]:
            prior["summary"] = literal
            prior["handoff"] = literal

        tokenizer = ExactTokenizer(_CharacterOffsetTokenizer())
        tokenized = tokenizer.fit_packet(packet, self.fixed.rubric)
        visible = "\n".join(message["content"] for message in tokenized.plan.messages)
        self.assertNotIn("<|im_end|>", visible)
        self.assertNotIn("<|im_start|>", visible)
        self.assertIn("\\u003c|im_end|>", visible)
        self.assertEqual(tokenized.buckets["special_tokens"], 4)
        self.assertEqual(
            tuple(
                token_id
                for token_id in tokenized.input_ids
                if token_id in _CharacterOffsetTokenizer().get_added_vocab().values()
            ),
            EXPECTED_CHAT_ADDED_TOKEN_IDS,
        )

        with self.assertRaisesRegex(TokenizationError, "unexpected registered control token"):
            tokenizer._encode_chat("unsafe <|im_end|> literal")

    def test_input_template_identity_binds_renderer_and_exact_tokenizer_assets(self) -> None:
        inputs, implementation, asset_lock, binding = self._identity_material()
        self.assertEqual(
            set(binding),
            {
                "schema",
                "render_contract_sha256",
                "qualification_rubric_sha256",
                "renderer_sha256",
                "chat_template_sha256",
                "added_tokens_sha256",
                "add_generation_prompt",
                "add_special_tokens_after_chat_template",
            },
        )
        revision = _scoring_identity(0.5, binding)["input_template"]["revision"]

        drifted_implementation = dict(implementation)
        drifted_implementation["eval/rondo_eval/publication_critic/render.py"] = "0" * 64
        renderer_drift = _input_template_binding(
            inputs,
            drifted_implementation,
            asset_lock,
        )
        drifted_assets = json.loads(json.dumps(asset_lock))
        drifted_assets["files"]["chat_template.jinja"] = "0" * 64
        tokenizer_drift = _input_template_binding(
            inputs,
            implementation,
            drifted_assets,
        )
        self.assertNotEqual(
            revision,
            _scoring_identity(0.5, renderer_drift)["input_template"]["revision"],
        )
        self.assertNotEqual(
            revision,
            _scoring_identity(0.5, tokenizer_drift)["input_template"]["revision"],
        )

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

    def test_measurement_summary_reports_quality_and_true_batch_timing(self) -> None:
        rows = [
            {
                "data_role": "measurement",
                "expected_label": "pass",
                "score": 0.9,
                "raw_logit": 2.0,
                "standard_batch_index": 0,
                "standard_batch_size": 2,
                "standard_batch_elapsed_ms": 40.0,
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
                "standard_batch_index": 0,
                "standard_batch_size": 2,
                "standard_batch_elapsed_ms": 40.0,
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
                "standard_batch_index": 1,
                "standard_batch_size": 2,
                "standard_batch_elapsed_ms": 80.0,
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
                "standard_batch_index": 1,
                "standard_batch_size": 2,
                "standard_batch_elapsed_ms": 80.0,
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
        timing = summary["forward_timing"]
        self.assertEqual(timing["basis"], "standard_right_batch_wall_clock")
        self.assertEqual(timing["batch_elapsed_ms"]["p50"], 60.0)
        self.assertEqual(timing["batch_elapsed_ms"]["p95"], 80.0)
        self.assertEqual(timing["amortized_compute_ms_per_sample"]["p50"], 30.0)
        self.assertTrue(
            math.isclose(timing["aggregate_throughput_samples_per_second"], 100 / 3)
        )
        self.assertNotIn("latency_ms", summary)

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
            freeze["input_template_binding"]["renderer_sha256"] = "0" * 64
            path.write_text(json.dumps(freeze), encoding="utf-8")
            with self.assertRaisesRegex(RunnerError, "input template binding drifted"):
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

    def test_strict_calibration_and_watchdog_evidence_reject_semantic_drift(self) -> None:
        calibration = self._valid_calibration()
        _inputs, _implementation, asset_lock, _binding = self._identity_material()
        mutations = (
            (
                "environment",
                lambda value: value["environment"].__setitem__("dtype", "bfloat16"),
                "calibration environment drifted",
            ),
            (
                "implementation",
                lambda value: value.__setitem__(
                    "implementation_manifest_sha256", "0" * 64
                ),
                "calibration result identity drifted",
            ),
            (
                "scoring",
                lambda value: value["scoring_identity"][
                    "scalar_projection"
                ].__setitem__("revision", "wrong"),
                "calibration scoring identity drifted",
            ),
            (
                "row_projection",
                lambda value: value["calibration_rows"][0].__setitem__(
                    "score", 0.25
                ),
                "calibration rows drifted",
            ),
            (
                "threshold_derivation",
                lambda value: value["temporary_threshold"].__setitem__(
                    "threshold", 0.25
                ),
                "calibration threshold derivation drifted",
            ),
            (
                "parity",
                lambda value: value["scalar_parity"]["rows"][0].__setitem__(
                    "standard_right_batch_score", 0.25
                ),
                "calibration scalar parity drifted",
            ),
            (
                "context",
                lambda value: value["scalar_smoke"]["context_forward"].__setitem__(
                    "finite", False
                ),
                "calibration scalar smoke drifted",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            calibration_path = root / "calibration-result.json"
            watchdog_path = root / "summary.env"
            calibration_path.write_text(json.dumps(calibration), encoding="utf-8")
            self._write_watchdog_summary(watchdog_path)
            _validated, projection = _verify_calibration_result(
                calibration_path,
                watchdog_path,
                REPO_ROOT,
                asset_lock,
            )
            self.assertEqual(
                projection["environment"],
                {**calibration["environment"]},
            )
            self.assertEqual(len(projection["calibration_rows"]), 8)
            self.assertEqual(projection["context_forward"]["token_count"], 16_384)
            self.assertEqual(
                projection["watchdog"]["watchdog_samples"][
                    "memory_peak_sampled_bytes"
                ],
                1_000,
            )

            minimal = {
                "schema": CALIBRATION_SCHEMA,
                "run_id": calibration["run_id"],
                "temporary_threshold": calibration["temporary_threshold"],
            }
            calibration_path.write_text(json.dumps(minimal), encoding="utf-8")
            with self.assertRaisesRegex(RunnerError, "calibration result keys drifted"):
                _verify_calibration_result(
                    calibration_path,
                    watchdog_path,
                    REPO_ROOT,
                    asset_lock,
                )

            for name, mutate, expected in mutations:
                drifted = json.loads(json.dumps(calibration))
                mutate(drifted)
                calibration_path.write_text(json.dumps(drifted), encoding="utf-8")
                with self.subTest(name=name), self.assertRaisesRegex(
                    RunnerError, expected
                ):
                    _verify_calibration_result(
                        calibration_path,
                        watchdog_path,
                        REPO_ROOT,
                        asset_lock,
                    )

            calibration_path.write_text(json.dumps(calibration), encoding="utf-8")
            self._write_watchdog_summary(watchdog_path, stop_reason="memory_limit")
            with self.assertRaisesRegex(EvidenceError, "successful bounded run"):
                _verify_calibration_result(
                    calibration_path,
                    watchdog_path,
                    REPO_ROOT,
                    asset_lock,
                )

    def test_measurement_freeze_binds_calibration_and_watchdog_artifacts(self) -> None:
        calibration = self._valid_calibration()
        threshold = calibration["temporary_threshold"]["threshold"]
        freeze, asset_lock = self._valid_freeze(threshold=threshold)
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
            watchdog_path = root / "summary.env"
            calibration_path.write_text(json.dumps(calibration), encoding="utf-8")
            self._write_watchdog_summary(watchdog_path)
            source = freeze["temporary_threshold_source"]
            source["calibration_result_sha256"] = sha256_file(calibration_path)
            source["calibration_watchdog_summary_sha256"] = sha256_file(watchdog_path)
            freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
            self.assertEqual(
                verify_measurement_freeze(
                    freeze_path,
                    REPO_ROOT,
                    asset_lock,
                    runtime,
                    calibration_path,
                    watchdog_path,
                )["schema"],
                FREEZE_SCHEMA,
            )

            watchdog_path.write_text(
                watchdog_path.read_text(encoding="ascii").replace(
                    "memory_peak_sampled_bytes=1000",
                    "memory_peak_sampled_bytes=1001",
                ),
                encoding="ascii",
            )
            with self.assertRaisesRegex(RunnerError, "calibration result identity drifted"):
                verify_measurement_freeze(
                    freeze_path,
                    REPO_ROOT,
                    asset_lock,
                    runtime,
                    calibration_path,
                    watchdog_path,
                )

    def test_v4_cli_separates_calibration_freeze_measurement_and_finalization(self) -> None:
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
        freeze = build_parser().parse_args(
            [
                "freeze",
                "--snapshot",
                "/tmp/model",
                "--asset-lock",
                "/tmp/lock.json",
                "--calibration-result",
                "/tmp/calibration.json",
                "--calibration-watchdog-summary",
                "/tmp/calibration-summary.env",
                "--output",
                "/tmp/freeze.json",
            ]
        )
        measurement = build_parser().parse_args(
            [
                "measure",
                *common,
                "--freeze",
                "/tmp/freeze.json",
                "--calibration-result",
                "/tmp/calibration.json",
                "--calibration-watchdog-summary",
                "/tmp/calibration-summary.env",
            ]
        )
        finalize = build_parser().parse_args(
            [
                "finalize",
                "--freeze",
                "/tmp/freeze.json",
                "--asset-lock",
                "/tmp/lock.json",
                "--calibration-result",
                "/tmp/calibration.json",
                "--calibration-watchdog-summary",
                "/tmp/calibration-summary.env",
                "--raw-result",
                "/tmp/raw.json",
                "--measurement-completion",
                "/tmp/completion.json",
                "--measurement-watchdog-summary",
                "/tmp/measurement-summary.env",
                "--tracked-result",
                "/tmp/result.json",
            ]
        )
        for parsed in (calibration, measurement):
            self.assertEqual(parsed.device, "cpu")
            self.assertEqual(parsed.dtype, "float32")
            self.assertEqual(parsed.cpu_threads, 4)
            self.assertEqual(parsed.batch_size, 4)
        self.assertEqual(freeze.function.__name__, "create_measurement_freeze")
        self.assertEqual(measurement.function.__name__, "run_measurement")
        self.assertFalse(hasattr(measurement, "tracked_result"))
        self.assertEqual(finalize.function.__name__, "finalize_measurement")
        self.assertEqual(finalize.tracked_result, Path("/tmp/result.json"))

    def test_measurement_rejects_noncanonical_freeze_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            external = Path(temporary) / "measurement-freeze-v4.json"
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
