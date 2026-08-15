from __future__ import annotations

import copy
import hashlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval import artifacts  # noqa: E402
from rondo_eval.artifacts import ArtifactError, ArtifactWriter  # noqa: E402
from rondo_eval.config import RepoPaths, RuntimeConfig  # noqa: E402
from rondo_eval.local_approval import shadow_replay, teacher_labels  # noqa: E402
from rondo_eval.local_approval.client import (  # noqa: E402
    ServiceUnavailableError,
    StructuredOutputError,
)
from rondo_eval.local_approval.launcher import (  # noqa: E402
    CHAT_TEMPLATE_RELATIVE_PATH,
    CHAT_TEMPLATE_REPO,
    CHAT_TEMPLATE_REVISION,
    CHAT_TEMPLATE_SHA256,
    CHAT_TEMPLATE_SIZE_BYTES,
    CHAT_TEMPLATE_SOURCE_FILE,
    GPU_MODEL_SERVING_CAPABILITY,
    RuntimeInspection,
)
from rondo_eval.local_approval import model_backed  # noqa: E402
from rondo_eval import runtime_bridge  # noqa: E402


TEACHER_DIRECTORY = "eval-data/teacher-labels/20260815-sol-teacher-labels-v1"


def semantic_id(index: int) -> str:
    return hashlib.sha256(f"sample-{index}".encode()).hexdigest()


def payload_for(identifier: str) -> dict:
    """A minimal canonical payload whose digest is derived, never invented."""

    return {"guardian_policy": f"policy-{identifier}", "input": []}


def payload_sha256(identifier: str) -> str:
    return hashlib.sha256(
        shadow_replay.canonical_bytes(payload_for(identifier))
    ).hexdigest()


def outcome_row(
    index: int,
    *,
    partition: str = "seed",
    terminal_state: str = shadow_replay.DECIDED_ALLOW,
    teacher_outcome: str = "allow",
    latency_ms: float = 1000.0,
    input_tokens: int = 6000,
    output_tokens: int | None = 60,
    attempts: int = 1,
    retry_reason: str | None = None,
) -> dict:
    decision = shadow_replay.DECISION_BY_STATE.get(terminal_state)
    usage = (
        None
        if output_tokens is None
        else {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
        }
    )
    return {
        "semantic_id": semantic_id(index),
        "partition": partition,
        "e_final_sha256": hashlib.sha256(f"e-{index}".encode()).hexdigest(),
        "static_payload_sha256": payload_sha256(semantic_id(index)),
        "terminal_state": terminal_state,
        "decision_outcome": decision,
        "teacher_outcome": teacher_outcome,
        "teacher_match": None if decision is None else decision == teacher_outcome,
        "latency_ms": latency_ms,
        "attempts": attempts,
        "retry_reason": retry_reason,
        "failure_code": None if decision is not None else "synthetic_failure",
        "input_tokens": input_tokens,
        "usage": usage,
    }


def teacher_sample(row: dict) -> shadow_replay.TeacherSample:
    return shadow_replay.TeacherSample(
        semantic_id=row["semantic_id"],
        partition=row["partition"],
        usage=(
            "evaluation and future synthesis reference; real evidence itself is not training data"
            if row["partition"] == "seed"
            else "evaluation only; forbidden from synthesis context, synthesis prompt, synthesis-time reference, and training"
        ),
        e_final_sha256=row["e_final_sha256"],
        static_payload_sha256=row["static_payload_sha256"],
        input_tokens=row["input_tokens"],
        request_shape="responses_lite",
        teacher_outcome=row["teacher_outcome"],
        canonical_payload=payload_for(row["semantic_id"]),
    )


def synthetic_rows() -> list[dict]:
    """24 seed and 16 holdout rows covering all five terminal states."""

    rows = [
        outcome_row(index, partition="seed", latency_ms=100.0 * (index + 1))
        for index in range(20)
    ]
    rows.append(
        outcome_row(
            20,
            partition="seed",
            terminal_state=shadow_replay.DECIDED_DENY,
            teacher_outcome="deny",
            latency_ms=2100.0,
        )
    )
    rows.append(
        outcome_row(
            21,
            partition="seed",
            terminal_state=shadow_replay.DECIDED_DENY,
            teacher_outcome="allow",
            latency_ms=2200.0,
        )
    )
    rows.append(
        outcome_row(
            22,
            partition="seed",
            terminal_state=shadow_replay.STRUCTURED_OUTPUT_FAILED,
            teacher_outcome="deny",
            latency_ms=2300.0,
            output_tokens=512,
        )
    )
    rows.append(
        outcome_row(
            23,
            partition="seed",
            terminal_state=shadow_replay.TIMED_OUT,
            teacher_outcome="deny",
            latency_ms=120_000.0,
            output_tokens=None,
        )
    )
    for index in range(24, 39):
        rows.append(
            outcome_row(
                index,
                partition="holdout",
                terminal_state=(
                    shadow_replay.DECIDED_DENY if index % 2 else shadow_replay.DECIDED_ALLOW
                ),
                teacher_outcome="deny" if index % 3 else "allow",
                latency_ms=50.0 * (index + 1),
            )
        )
    rows.append(
        outcome_row(
            39,
            partition="holdout",
            terminal_state=shadow_replay.INFRA_FAILED,
            teacher_outcome="allow",
            latency_ms=900.0,
            output_tokens=None,
            attempts=2,
            retry_reason="infra_retry",
        )
    )
    return rows


def teacher_batch(rows: list[dict]) -> shadow_replay.TeacherBatch:
    samples = tuple(
        sorted(
            (teacher_sample(row) for row in rows), key=lambda item: item.semantic_id
        )
    )
    summary = {
        "batch_id": shadow_replay.TEACHER_BATCH_ID,
        "ready_for_l3": True,
        "counts": {
            "selected_labels": len(samples),
            "selected_partitions": shadow_replay.EXPECTED_PARTITION_COUNTS,
        },
        "contracts": {
            "label_schema_version": 1,
            "static_payload_schema_version": 3,
            "static_decision_schema_name": "rondo_static_approval_v1",
            "identity_rule_version": "rondo_guardian_semantic_v1",
            "representative_rule_version": "frozen_e_final_sha256_lexicographic_v1",
        },
        "label_schema_sha256": "1" * 64,
        "prompt": {"version": "rondo_sol_teacher_prompt_v1", "sha256": "2" * 64},
        "teacher": {
            "model": "gpt-5.6-sol",
            "generated_dates": ["2026-08-15"],
            "nature": "point_in_time_sol_distillation_target_not_human_ground_truth",
        },
        "private_artifacts": {
            "relative_directory": TEACHER_DIRECTORY,
            "labels_sha256": shadow_replay.TEACHER_LABELS_SHA256,
            "import_metadata_sha256": "3" * 64,
        },
    }
    return shadow_replay.TeacherBatch(
        batch_id=shadow_replay.TEACHER_BATCH_ID, summary=summary, samples=samples
    )


def run_document(rows: list[dict], batch: shadow_replay.TeacherBatch) -> dict:
    return {
        "schema_version": shadow_replay.RUN_SCHEMA_VERSION,
        "kind": "l3_local_static_replay",
        "run_uid": "0123456789abcdef",
        "started_at": "2026-08-15T10:00:00+08:00",
        "finished_at": "2026-08-15T10:20:00+08:00",
        "harness": {"eval_harness_commit": "a" * 40, "git_dirty": False},
        "teacher": shadow_replay.batch_identity(batch),
        "service": {
            "model_id": "rondo-local-approval",
            "model_relative_path": "eval-data/models/model.gguf",
            "model_sha256": "b" * 64,
            "quantization": "Q4_K_M",
            "fine_tuned": False,
            "runtime_relative_path": "eval-data/tools/llama-b10333-cuda-linux-x64",
            "runtime_identity_sha256": "c" * 64,
            "service_build_info": "b1-0865990",
            "serve_config_sha256": "d" * 64,
            "request_contract_sha256": "e" * 64,
            "chat_template_sha256": "f" * 64,
            "context_size": 12288,
            "max_output_tokens": 512,
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": 42,
            "qualification_capability": "gpu_model_serving_validated",
            "qualification_evidence_relative_path": "eval/locks/evidence.json",
            "static_payload_schema_version": 3,
            "static_decision_schema_name": "rondo_static_approval_v1",
        },
        "vram": {
            "baseline_bytes": 1_000,
            "peak_bytes": 7_000_000_000,
            "delta_bytes": 6_999_999_000,
            "samples": 512,
            "complete": True,
            "method": shadow_replay.VRAM_METHOD,
            "scope": "peak bytes across the whole local batch lifecycle",
        },
        "cleanup": {
            "server_stopped": True,
            "port_released": True,
            "receipt_cleared": True,
        },
        "attempts_sha256": "9" * 64,
        "outcomes": list(shadow_replay.validate_outcome_rows(rows)),
    }


class MetricContractTests(unittest.TestCase):
    def test_tracked_template_is_the_frozen_code_contract(self) -> None:
        self.assertEqual(
            shadow_replay.load_metric_contract(EVAL_ROOT.parent),
            shadow_replay.metric_contract_document(),
        )
        document = shadow_replay.metric_contract_document()
        self.assertEqual(document["terminal_states"], list(shadow_replay.TERMINAL_STATES))
        self.assertNotIn("false_allow", json.dumps(document))
        self.assertNotIn("false_deny", json.dumps(document))

    def test_metric_contract_drift_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / shadow_replay.METRIC_CONTRACT_RELATIVE_PATH
            path.parent.mkdir(parents=True)
            drifted = shadow_replay.metric_contract_document()
            drifted["percentile_method"] = "linear interpolation"
            path.write_text(json.dumps(drifted), encoding="utf-8")
            with self.assertRaises(shadow_replay.ShadowReplayError):
                shadow_replay.load_metric_contract(root)

    def test_percentile_is_nearest_rank_one_based(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0]
        self.assertEqual(shadow_replay.percentile(values, 50), 2.0)
        self.assertEqual(shadow_replay.percentile(values, 95), 4.0)
        self.assertEqual(shadow_replay.percentile([7.0], 50), 7.0)
        self.assertEqual(shadow_replay.percentile([7.0], 95), 7.0)
        self.assertIsNone(shadow_replay.percentile([], 50))
        # index = ceil(p/100*n) on the ascending list, never an average.
        ten = [float(value) for value in range(1, 11)]
        self.assertEqual(shadow_replay.percentile(ten, 50), 5.0)
        self.assertEqual(shadow_replay.percentile(ten, 95), 10.0)

    def test_every_sample_lands_in_exactly_one_terminal_state(self) -> None:
        rows = synthetic_rows()
        block = shadow_replay.summarize(rows, scope="overall")
        self.assertEqual(sum(block["terminal_states"].values()), len(rows))
        self.assertEqual(set(block["terminal_states"]), set(shadow_replay.TERMINAL_STATES))
        self.assertEqual(block["terminal_states"][shadow_replay.TIMED_OUT], 1)
        self.assertEqual(block["terminal_states"][shadow_replay.INFRA_FAILED], 1)
        self.assertEqual(
            block["terminal_states"][shadow_replay.STRUCTURED_OUTPUT_FAILED], 1
        )

    def test_fail_closed_counts_failures_and_never_a_compliant_deny(self) -> None:
        block = shadow_replay.summarize(synthetic_rows(), scope="overall")
        self.assertEqual(block["fail_closed"]["total"], 3)
        self.assertEqual(
            block["fail_closed"]["total"],
            block["fail_closed"]["structured_output_failed"]
            + block["fail_closed"]["timed_out"]
            + block["fail_closed"]["infra_failed"],
        )
        denies = block["terminal_states"][shadow_replay.DECIDED_DENY]
        self.assertGreater(denies, 0)
        self.assertEqual(block["local_decisions"]["deny"], denies)
        self.assertEqual(
            block["local_decisions"]["allow"] + block["local_decisions"]["deny"],
            block["comparable_decision_count"],
        )

    def test_teacher_agreement_denominator_is_comparable_decisions_only(self) -> None:
        rows = synthetic_rows()
        block = shadow_replay.summarize(rows, scope="overall")
        comparable = sum(
            1 for row in rows if row["terminal_state"] in shadow_replay.DECISION_BY_STATE
        )
        agreed = sum(1 for row in rows if row["teacher_match"] is True)
        self.assertEqual(block["comparable_decision_count"], comparable)
        self.assertEqual(block["teacher_agreement"]["denominator"], comparable)
        self.assertEqual(block["teacher_agreement"]["numerator"], agreed)
        self.assertAlmostEqual(block["teacher_agreement"]["rate"], agreed / comparable)
        self.assertEqual(
            block["teacher_disagreement_count"], comparable - agreed
        )
        self.assertEqual(block["effective_decision_coverage"]["denominator"], len(rows))
        self.assertAlmostEqual(
            block["effective_decision_coverage"]["ratio"], comparable / len(rows)
        )

    def test_zero_comparable_decisions_reports_null_not_zero_percent(self) -> None:
        rows = [
            outcome_row(
                index,
                terminal_state=shadow_replay.TIMED_OUT,
                output_tokens=None,
                latency_ms=10.0,
            )
            for index in range(3)
        ]
        block = shadow_replay.summarize(rows, scope="overall")
        self.assertEqual(block["comparable_decision_count"], 0)
        self.assertIsNone(block["teacher_agreement"]["rate"])
        self.assertEqual(block["teacher_agreement"]["numerator"], 0)
        self.assertEqual(block["local_decisions"], {"allow": 0, "deny": 0})
        self.assertEqual(block["fail_closed"]["total"], 3)
        self.assertIsNone(block["tokens"]["output"]["p50"])
        self.assertEqual(block["tokens"]["output"]["missing"], 3)

    def test_missing_usage_is_counted_not_filled_with_zero(self) -> None:
        rows = synthetic_rows()
        block = shadow_replay.summarize(rows, scope="overall")
        missing = sum(1 for row in rows if row["usage"] is None)
        self.assertEqual(block["tokens"]["output"]["missing"], missing)
        self.assertEqual(block["tokens"]["output"]["observed"], len(rows) - missing)
        self.assertEqual(block["tokens"]["total"]["missing"], missing)
        # Input tokens come from the frozen census, so they are never missing.
        self.assertEqual(block["tokens"]["input"]["observed"], len(rows))
        self.assertEqual(block["tokens"]["input"]["missing"], 0)
        self.assertEqual(
            block["tokens"]["input"]["source"], shadow_replay.INPUT_TOKEN_SOURCE
        )
        self.assertEqual(
            block["tokens"]["output"]["source"], shadow_replay.USAGE_TOKEN_SOURCE
        )
        self.assertGreater(block["tokens"]["output"]["p50"], 0)

    def test_service_input_usage_disagreement_is_reported(self) -> None:
        rows = [outcome_row(index) for index in range(3)]
        rows[0]["usage"] = {
            "input_tokens": 1,
            "output_tokens": 2,
            "total_tokens": 3,
        }
        block = shadow_replay.summarize(rows, scope="overall")
        self.assertEqual(
            block["tokens"]["input_usage_check"],
            {"matching": 2, "differing": 1, "missing": 0},
        )

    def test_latency_percentiles_use_the_declared_method_and_unit(self) -> None:
        rows = [
            outcome_row(index, latency_ms=float(index + 1) * 10.0) for index in range(10)
        ]
        block = shadow_replay.summarize(rows, scope="overall")
        self.assertEqual(block["latency_ms"]["p50"], 50.0)
        self.assertEqual(block["latency_ms"]["p95"], 100.0)
        self.assertEqual(block["latency_ms"]["unit"], "milliseconds")
        self.assertEqual(
            block["latency_ms"]["percentile_method"], shadow_replay.PERCENTILE_METHOD
        )
        self.assertEqual(block["latency_ms"]["observed"], 10)

    def test_recomputation_is_idempotent_and_order_independent(self) -> None:
        rows = synthetic_rows()
        first = shadow_replay.summarize_all(rows)
        second = shadow_replay.summarize_all(list(reversed(rows)))
        self.assertEqual(first, second)
        self.assertEqual(
            first["overall"], shadow_replay.summarize(rows, scope="overall")
        )
        self.assertEqual(
            first["seed"]["sample_count"] + first["holdout"]["sample_count"],
            first["overall"]["sample_count"],
        )
        self.assertEqual(
            first["seed"]["comparable_decision_count"]
            + first["holdout"]["comparable_decision_count"],
            first["overall"]["comparable_decision_count"],
        )

    def test_outcome_rows_reject_contradictory_or_incomplete_records(self) -> None:
        base = outcome_row(1)
        cases = {
            "unknown_field": {**base, "extra": 1},
            "unknown_state": {**base, "terminal_state": "decided_maybe"},
            "decision_without_state": {
                **base,
                "terminal_state": shadow_replay.TIMED_OUT,
                "failure_code": "inference_timeout",
            },
            "failure_code_on_decision": {**base, "failure_code": "why"},
            "match_contradiction": {**base, "teacher_match": False},
            "retry_without_attempt": {**base, "retry_reason": "infra_retry"},
            "attempt_without_reason": {**base, "attempts": 2},
            "three_attempts": {**base, "attempts": 3, "retry_reason": "infra_retry"},
            "negative_latency": {**base, "latency_ms": -1.0},
            "inconsistent_usage": {
                **base,
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 9},
            },
        }
        for name, row in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(shadow_replay.ShadowReplayError):
                    shadow_replay.validate_outcome_rows([row])
        with self.assertRaises(shadow_replay.ShadowReplayError):
            shadow_replay.validate_outcome_rows([base, dict(base)])
        self.assertEqual(len(shadow_replay.validate_outcome_rows([base])), 1)


class TeacherImportTests(unittest.TestCase):
    """Cover the strict frozen-batch import with a mocked Plan 032 verifier."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.private = self.root / "batch"
        self.private.mkdir(mode=0o700)
        self.rows = synthetic_rows()
        self.batch = teacher_batch(self.rows)
        self.summary = copy.deepcopy(dict(self.batch.summary))
        lock = self.root / shadow_replay.TEACHER_LOCK_RELATIVE_PATH
        lock.parent.mkdir(parents=True)
        lock.write_text(json.dumps(self.summary), encoding="utf-8")
        self.labels = [
            {
                "batch_id": shadow_replay.TEACHER_BATCH_ID,
                "semantic_id": sample.semantic_id,
                "representative_e_final_sha256": sample.e_final_sha256,
                "static_payload_sha256": sample.static_payload_sha256,
                "partition": sample.partition,
                "usage": sample.usage,
                "teacher_model": "gpt-5.6-sol",
                "prompt_version": "rondo_sol_teacher_prompt_v1",
                "prompt_sha256": "2" * 64,
                "decision": {
                    "outcome": sample.teacher_outcome,
                    "rationale": "synthetic",
                    "risk_tags": [],
                },
            }
            for sample in self.batch.samples
        ]
        self.selected = {
            sample.semantic_id: {
                "e_final_sha256": sample.e_final_sha256,
                "static_payload_sha256": sample.static_payload_sha256,
                "partition": sample.partition,
                "usage": sample.usage,
                "input_tokens": sample.input_tokens,
                "request_shape": sample.request_shape,
            }
            for sample in self.batch.samples
        }
        self.outbound = [
            {
                "semantic_id": sample.semantic_id,
                "canonical_payload": dict(sample.canonical_payload),
            }
            for sample in self.batch.samples
        ]
        self.manifest = {
            "prompt_version": "rondo_sol_teacher_prompt_v1",
            "prompt_sha256": "2" * 64,
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _run(self, *, labels=None, selected=None, outbound=None, lock=None):
        labels = self.labels if labels is None else labels
        raw = b"".join(
            json.dumps(row, sort_keys=True).encode() + b"\n" for row in labels
        )
        digest = hashlib.sha256(raw).hexdigest()
        summary = copy.deepcopy(self.summary)
        summary["private_artifacts"]["labels_sha256"] = digest
        (self.root / shadow_replay.TEACHER_LOCK_RELATIVE_PATH).write_text(
            json.dumps(summary if lock is None else lock), encoding="utf-8"
        )
        frozen = (
            self.manifest,
            b"",
            self.selected if selected is None else selected,
            self.outbound if outbound is None else outbound,
            b"",
            b"",
        )
        with mock.patch.object(
            teacher_labels, "build_summary", return_value=summary
        ), mock.patch.object(
            teacher_labels, "_validate_frozen_batch", return_value=frozen
        ), mock.patch.object(
            teacher_labels, "_load_jsonl", return_value=(labels, raw)
        ), mock.patch.object(
            shadow_replay, "TEACHER_LABELS_SHA256", digest
        ):
            return shadow_replay.load_teacher_batch(
                worktree_root=self.root, private_dir=self.private
            )

    def test_complete_frozen_set_is_imported_with_matching_identities(self) -> None:
        batch = self._run()
        self.assertEqual(len(batch.samples), shadow_replay.EXPECTED_SAMPLE_COUNT)
        self.assertEqual(len(batch.by_partition("seed")), 24)
        self.assertEqual(len(batch.by_partition("holdout")), 16)
        identity = shadow_replay.batch_identity(batch)
        self.assertEqual(identity["sample_count"], 40)
        self.assertEqual(identity["artifacts"], TEACHER_DIRECTORY)
        self.assertNotEqual(
            identity["seed_sample_set_sha256"], identity["holdout_sample_set_sha256"]
        )

    def test_missing_extra_and_cross_partition_labels_are_refused(self) -> None:
        cases = {
            "missing": self.labels[:-1],
            "duplicate": self.labels + [self.labels[0]],
            "unknown_identity": [
                {**self.labels[0], "semantic_id": "f" * 64},
                *self.labels[1:],
            ],
            "cross_partition": [
                {
                    **self.labels[0],
                    "partition": (
                        "holdout" if self.labels[0]["partition"] == "seed" else "seed"
                    ),
                },
                *self.labels[1:],
            ],
            "payload_drift": [
                {**self.labels[0], "static_payload_sha256": "0" * 64},
                *self.labels[1:],
            ],
            "invalid_decision": [
                {**self.labels[0], "decision": {"outcome": "maybe"}},
                *self.labels[1:],
            ],
        }
        for name, labels in cases.items():
            with self.subTest(case=name):
                with self.assertRaises(shadow_replay.ShadowReplayError):
                    self._run(labels=labels)

    def test_tracked_lock_must_equal_the_private_batch_summary(self) -> None:
        drifted = copy.deepcopy(self.summary)
        drifted["counts"]["selected_labels"] = 39
        with self.assertRaises(shadow_replay.ShadowReplayError):
            self._run(lock=drifted)


class _FakeSettings:
    model_id = "rondo-local-approval"


class _FakeClient:
    """Drive `_replay_sample` without any network or launcher."""

    def __init__(self, script):
        self.script = list(script)
        self.settings = _FakeSettings()
        self.identity_checks = 0
        self.sent = 0
        self.identity_alive = True

    def post_decision_request(self, request, identity):
        self.sent += 1
        action = self.script.pop(0)
        if isinstance(action, Exception):
            raise action
        return action

    def require_service_identity(self):
        self.identity_checks += 1
        if not self.identity_alive:
            raise ServiceUnavailableError("gone")
        return object()


def envelope(outcome: str, *, output_tokens: int = 40) -> dict:
    return {
        "status": "completed",
        "model": "rondo-local-approval",
        "output": [
            {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": json.dumps(
                            {
                                "outcome": outcome,
                                "rationale": "private rationale",
                                "risk_tags": ["private"],
                            }
                        ),
                    }
                ],
            }
        ],
        "usage": {
            "input_tokens": 6000,
            "output_tokens": output_tokens,
            "total_tokens": 6000 + output_tokens,
        },
    }


class ReplayLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.sample = teacher_sample(outcome_row(1))
        self.clock = iter(float(value) for value in range(0, 400))

    def _replay(self, script):
        client = _FakeClient(script)
        row, attempts = shadow_replay._replay_sample(
            client, self.sample, {"model": "x"}, object(), lambda: next(self.clock)
        )
        return client, row, attempts

    def test_compliant_decisions_become_allow_and_deny_terminal_states(self) -> None:
        for outcome, state in (
            ("allow", shadow_replay.DECIDED_ALLOW),
            ("deny", shadow_replay.DECIDED_DENY),
        ):
            with self.subTest(outcome=outcome):
                self.clock = iter(float(value) for value in range(0, 400))
                _client, row, attempts = self._replay([envelope(outcome)])
                self.assertEqual(row["terminal_state"], state)
                self.assertEqual(row["decision_outcome"], outcome)
                self.assertEqual(row["attempts"], 1)
                self.assertIsNone(row["retry_reason"])
                self.assertIsNone(row["failure_code"])
                self.assertEqual(row["usage"]["output_tokens"], 40)
                self.assertEqual(len(attempts), 1)

    def test_one_infra_failure_is_retried_once_with_the_same_input(self) -> None:
        client, row, attempts = self._replay(
            [ServiceUnavailableError("down"), envelope("deny")]
        )
        self.assertEqual(client.sent, 2)
        self.assertEqual(row["terminal_state"], shadow_replay.DECIDED_DENY)
        self.assertEqual(row["attempts"], 2)
        self.assertEqual(row["retry_reason"], "infra_retry")
        self.assertEqual(attempts[0]["outcome"], shadow_replay.INFRA_FAILED)
        self.assertEqual(attempts[1]["outcome"], shadow_replay.DECIDED_DENY)

    def test_two_infra_failures_end_as_infra_failed(self) -> None:
        client, row, _attempts = self._replay(
            [ServiceUnavailableError("down"), ServiceUnavailableError("down")]
        )
        self.assertEqual(client.sent, 2)
        self.assertEqual(row["terminal_state"], shadow_replay.INFRA_FAILED)
        self.assertEqual(row["attempts"], 2)
        self.assertIsNone(row["usage"])

    def test_inference_timeout_is_a_result_and_is_never_retried(self) -> None:
        error = ServiceUnavailableError("timeout")
        error.__cause__ = TimeoutError("read timed out")
        client, row, _attempts = self._replay([error, envelope("allow")])
        self.assertEqual(client.sent, 1)
        self.assertEqual(row["terminal_state"], shadow_replay.TIMED_OUT)
        self.assertEqual(row["attempts"], 1)
        self.assertEqual(row["failure_code"], "inference_timeout")

    def test_structured_output_failure_is_a_result_and_is_never_retried(self) -> None:
        client, row, _attempts = self._replay(
            [StructuredOutputError("bad"), envelope("allow")]
        )
        self.assertEqual(client.sent, 1)
        self.assertEqual(row["terminal_state"], shadow_replay.STRUCTURED_OUTPUT_FAILED)
        self.assertEqual(row["attempts"], 1)

    def test_a_model_response_that_fails_the_schema_is_not_retried(self) -> None:
        broken = envelope("allow")
        broken["output"][0]["content"][0]["text"] = json.dumps({"outcome": "maybe"})
        client, row, attempts = self._replay([broken, envelope("allow")])
        self.assertEqual(client.sent, 1)
        self.assertEqual(row["terminal_state"], shadow_replay.STRUCTURED_OUTPUT_FAILED)
        self.assertEqual(row["failure_code"], "structured_decision_invalid")
        # Usage that did arrive is still measured, the decision is not invented.
        self.assertEqual(row["usage"]["output_tokens"], 40)
        self.assertIn("raw_envelope", attempts[0])

    def test_a_lost_service_identity_stops_the_batch(self) -> None:
        client = _FakeClient([ServiceUnavailableError("down")])
        client.identity_alive = False
        with self.assertRaises(ServiceUnavailableError):
            shadow_replay._replay_sample(
                client, self.sample, {"model": "x"}, object(), lambda: next(self.clock)
            )

    def test_usage_is_only_read_when_it_is_internally_consistent(self) -> None:
        self.assertIsNone(shadow_replay.extract_usage({"usage": {}}))
        self.assertIsNone(shadow_replay.extract_usage({}))
        self.assertIsNone(
            shadow_replay.extract_usage(
                {"usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 3}}
            )
        )
        self.assertIsNone(
            shadow_replay.extract_usage(
                {"usage": {"input_tokens": 1, "output_tokens": 0, "total_tokens": 1}}
            )
        )
        self.assertEqual(
            shadow_replay.extract_usage(
                {"usage": {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7}}
            ),
            {"input_tokens": 5, "output_tokens": 2, "total_tokens": 7},
        )


def _install_template_fixture(root: Path) -> None:
    source = EVAL_ROOT.parent / CHAT_TEMPLATE_RELATIVE_PATH
    target = root / CHAT_TEMPLATE_RELATIVE_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())
    lock = root / "eval/locks/ministral-3-8b-instruct-2512-chat-template.json"
    lock.parent.mkdir(parents=True, exist_ok=True)
    lock.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "repo": CHAT_TEMPLATE_REPO,
                "revision": CHAT_TEMPLATE_REVISION,
                "source_file": CHAT_TEMPLATE_SOURCE_FILE,
                "installed": {
                    "relative_path": CHAT_TEMPLATE_RELATIVE_PATH,
                    "size_bytes": CHAT_TEMPLATE_SIZE_BYTES,
                    "sha256": CHAT_TEMPLATE_SHA256,
                },
            }
        ),
        encoding="utf-8",
    )


def _local_data(port: int, *, model_path: str, model_sha256: str) -> dict:
    return {
        "local_model": {
            "runtime": "llama_cpp",
            "api": "responses",
            "base_url": f"http://127.0.0.1:{port}/v1",
            "model_id": "rondo-local-approval",
            "model_path": model_path,
            "model_sha256": model_sha256,
            "format": "gguf",
            "quantization": "Q4_K_M",
            "server": {
                "binary": model_backed.CUDA_SERVER_RELATIVE_PATH,
                "host": "127.0.0.1",
                "port": port,
                "context_size": 12288,
                "gpu_layers": "auto",
                "fit": "on",
                "batch_size": 512,
                "ubatch_size": 256,
                "cache_type_k": "f16",
                "cache_type_v": "f16",
                "no_mmproj": True,
                "chat_template_file": CHAT_TEMPLATE_RELATIVE_PATH,
                "chat_template_sha256": CHAT_TEMPLATE_SHA256,
                "jinja": True,
                "flash_attention": "on",
                "parallel": 1,
                "metrics": True,
                "slots": True,
                "web_ui": False,
                "tools": False,
            },
            "request": {
                "stream": False,
                "temperature": 0.0,
                "top_p": 1.0,
                "seed": 42,
                "max_output_tokens": 512,
                "timeout_seconds": 2,
                "max_retries": 0,
                "structured_output": True,
            },
        }
    }


class _FakeServerProcess:
    def __init__(self) -> None:
        self.pid = os.getpid()
        self.terminated = False
        self.popen_kwargs: dict = {}
        self._exited = False

    def __call__(self, command, **kwargs):
        self.popen_kwargs = dict(kwargs)
        self.command = list(command)
        return self

    def poll(self):
        return 0 if self._exited else None

    def terminate(self):
        self.terminated = True
        self._exited = True

    def kill(self):
        self._exited = True

    def wait(self, timeout=None):
        if not self._exited:
            raise subprocess.TimeoutExpired(cmd="llama-server", timeout=timeout or 0)
        return 0


class _FakeSampler:
    def __init__(self) -> None:
        self.calls = 0

    def used_bytes(self) -> int:
        self.calls += 1
        return 1_000_000 + self.calls

    def compute_process_pids(self) -> list[int]:
        return []


class ReplayLifecycleTests(unittest.TestCase):
    """One fully mocked lifecycle: no real model, no GPU, no network."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = RepoPaths(self.root, self.root)
        _install_template_fixture(self.root)
        contract = self.root / shadow_replay.METRIC_CONTRACT_RELATIVE_PATH
        contract.parent.mkdir(parents=True, exist_ok=True)
        contract.write_text(
            json.dumps(shadow_replay.metric_contract_document()), encoding="utf-8"
        )
        self.model = self.root / "eval-data/models/fixture.gguf"
        self.model.parent.mkdir(parents=True)
        self.model.write_bytes(b"GGUFshadow-replay-fixture")
        self.model_sha256 = hashlib.sha256(self.model.read_bytes()).hexdigest()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("127.0.0.1", 0))
            port = int(listener.getsockname()[1])
        self.config = RuntimeConfig(
            self.paths,
            _local_data(
                port,
                model_path="eval-data/models/fixture.gguf",
                model_sha256=self.model_sha256,
            ),
            "0" * 64,
        )
        self.rows = synthetic_rows()
        self.batch = teacher_batch(self.rows)
        self.script = {
            sample.semantic_id: envelope(sample.teacher_outcome)
            for sample in self.batch.samples
        }
        self.by_request = {
            hashlib.sha256(
                shadow_replay.canonical_bytes(sample.canonical_payload)
            ).hexdigest(): sample.semantic_id
            for sample in self.batch.samples
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _client_factory(self, config):
        outer = self

        class _Client:
            settings = _FakeSettings()

            def build_request(self, payload):
                return {
                    "payload_sha256": hashlib.sha256(payload.canonical_bytes).hexdigest()
                }

            def require_service_identity(self):
                return object()

            def post_decision_request(self, request, identity):
                action = outer.script[outer.by_request[request["payload_sha256"]]]
                if isinstance(action, list):
                    action = action.pop(0)
                if isinstance(action, Exception):
                    raise action
                return action

        return _Client()

    def _run(self, **overrides):
        lease = runtime_bridge.WatchdogLease(token="e" * 48)
        guard = mock.Mock()
        guard.is_held.return_value = True
        process = _FakeServerProcess()

        def http_get(url: str, *, timeout: float):
            if url.endswith("/health"):
                return {"status": "ok"}
            if url.endswith("/props"):
                return {
                    "build_info": model_backed.CUDA_SERVICE_BUILD_INFO,
                    "default_generation_settings": {"n_ctx": 12288},
                    "total_slots": 1,
                }
            raise AssertionError(f"unexpected probe: {url}")

        arguments = {
            "teacher_private_dir": self.root / TEACHER_DIRECTORY,
            "popen": process,
            "watchdog_factory": lambda: runtime_bridge.WatchdogProof(
                lease=lease, guard=guard
            ),
            "gpu_sampler": _FakeSampler(),
            "identity_publisher": mock.Mock(return_value=mock.sentinel.identity),
            "identity_clearer": mock.Mock(),
            "verify_identity": mock.Mock(),
            "http_get": http_get,
        }
        arguments.update(overrides)
        with mock.patch.object(
            shadow_replay, "load_teacher_batch", return_value=self.batch
        ), mock.patch.object(
            shadow_replay,
            "harness_state",
            return_value={"eval_harness_commit": "a" * 40, "git_dirty": False},
        ), mock.patch.object(
            shadow_replay, "resolve_model", return_value=self.model
        ), mock.patch.object(
            shadow_replay,
            "build_serve_command",
            return_value=["/fake/llama-server", "--verbosity", "3"],
        ), mock.patch.object(
            shadow_replay, "serve_config_sha256", return_value="d" * 64
        ), mock.patch.object(
            shadow_replay, "serve_environment", return_value={}
        ), mock.patch.object(
            shadow_replay, "LocalApprovalClient", self._client_factory
        ), mock.patch.object(
            shadow_replay,
            "inspect_runtime",
            return_value=RuntimeInspection(
                "runtime_ready",
                Path("/fake/llama-server"),
                "fixture CUDA runtime",
                "c" * 64,
                GPU_MODEL_SERVING_CAPABILITY,
                model_backed.MODEL_BACKED_VALIDATED,
            ),
        ), mock.patch.object(
            model_backed, "require_qualification_contract", lambda *a, **k: None
        ), mock.patch.object(
            model_backed, "load_model_backed_evidence", lambda _config: object()
        ):
            return shadow_replay.run_replay(self.config, **arguments), process

    def test_one_lifecycle_gives_every_sample_a_terminal_state(self) -> None:
        summary, process = self._run()
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["samples"], shadow_replay.EXPECTED_SAMPLE_COUNT)
        self.assertTrue(all(summary["cleanup"].values()))
        self.assertTrue(process.terminated)
        private = (
            self.root / shadow_replay.PRIVATE_ROOT / summary["private_run_directory"]
        )
        self.assertEqual(private.stat().st_mode & 0o777, 0o700)
        for name in ("run.json", "attempts.jsonl", "server.log"):
            self.assertEqual((private / name).stat().st_mode & 0o777, 0o600)
        document = shadow_replay.load_private_run(private)
        self.assertEqual(len(document["outcomes"]), 40)
        block = shadow_replay.summarize(document["outcomes"], scope="overall")
        self.assertEqual(sum(block["terminal_states"].values()), 40)
        self.assertEqual(block["teacher_agreement"]["rate"], 1.0)
        self.assertTrue(document["vram"]["complete"])
        self.assertGreater(document["vram"]["samples"], 0)

    def test_raw_model_output_stays_in_the_private_attempts_file(self) -> None:
        summary, _process = self._run()
        private = (
            self.root / shadow_replay.PRIVATE_ROOT / summary["private_run_directory"]
        )
        attempts = (private / "attempts.jsonl").read_text()
        self.assertIn("private rationale", attempts)
        run_text = (private / "run.json").read_text()
        self.assertNotIn("private rationale", run_text)
        self.assertNotIn("risk_tags", run_text)
        self.assertNotIn("private rationale", json.dumps(summary))

    def test_a_dirty_harness_refuses_to_start_the_model(self) -> None:
        with mock.patch.object(
            shadow_replay,
            "harness_state",
            return_value={"eval_harness_commit": "a" * 40, "git_dirty": True},
        ), mock.patch.object(
            model_backed, "require_qualification_contract", lambda *a, **k: None
        ), mock.patch.object(
            model_backed, "load_model_backed_evidence", lambda _config: object()
        ):
            popen = mock.Mock()
            with self.assertRaises(shadow_replay.ShadowReplayError) as raised:
                shadow_replay.run_replay(
                    self.config,
                    teacher_private_dir=self.root / TEACHER_DIRECTORY,
                    popen=popen,
                )
            self.assertEqual(raised.exception.code, "harness_not_clean")
            popen.assert_not_called()

    def test_an_aborted_batch_keeps_its_attempts_and_writes_no_run_document(self) -> None:
        guard = mock.Mock()
        guard.is_held.side_effect = [True, True, True, False] + [False] * 20
        with self.assertRaises(shadow_replay.ShadowReplayError) as raised:
            self._run(
                watchdog_factory=lambda: runtime_bridge.WatchdogProof(
                    lease=runtime_bridge.WatchdogLease(token="e" * 48), guard=guard
                )
            )
        self.assertIn("samples_with_terminal_state", raised.exception.facts)
        directories = list(
            (self.root / shadow_replay.PRIVATE_ROOT).glob(
                f"{shadow_replay.PRIVATE_RUN_PREFIX}-*"
            )
        )
        self.assertEqual(len(directories), 1)
        self.assertTrue((directories[0] / "attempts.jsonl").exists())
        self.assertFalse((directories[0] / "run.json").exists())

    def test_a_transport_failure_is_retried_once_inside_the_real_loop(self) -> None:
        target = self.batch.samples[0].semantic_id
        self.script[target] = [
            ServiceUnavailableError("down"),
            envelope(self.batch.samples[0].teacher_outcome),
        ]
        summary, _process = self._run()
        private = (
            self.root / shadow_replay.PRIVATE_ROOT / summary["private_run_directory"]
        )
        document = shadow_replay.load_private_run(private)
        row = next(
            item for item in document["outcomes"] if item["semantic_id"] == target
        )
        self.assertEqual(row["attempts"], 2)
        self.assertEqual(row["retry_reason"], "infra_retry")
        self.assertIn(row["terminal_state"], shadow_replay.DECISION_BY_STATE)
        attempts = [
            json.loads(line)
            for line in (private / "attempts.jsonl").read_text().splitlines()
            if json.loads(line)["semantic_id"] == target
        ]
        self.assertEqual(len(attempts), 2)
        self.assertEqual(attempts[0]["outcome"], shadow_replay.INFRA_FAILED)


class PublicationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = RepoPaths(self.root, self.root)
        self.config = RuntimeConfig(self.paths, {}, "0" * 64)
        contract = self.root / shadow_replay.METRIC_CONTRACT_RELATIVE_PATH
        contract.parent.mkdir(parents=True)
        contract.write_text(
            json.dumps(shadow_replay.metric_contract_document()), encoding="utf-8"
        )
        (self.root / TEACHER_DIRECTORY).mkdir(parents=True)
        self.rows = synthetic_rows()
        self.batch = teacher_batch(self.rows)
        self.document = run_document(self.rows, self.batch)
        self.private_run = self.root / "eval-data" / "local-approval" / "l3-replay-x"
        self.private_run.mkdir(parents=True, mode=0o700)
        shadow_replay._write_private_json(self.private_run / "run.json", self.document)
        self.harness = dict(self.document["harness"])

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _publish(self, *, in_history: bool = True):
        def ancestry(_root, commit):
            if not in_history:
                raise shadow_replay.ShadowReplayError("harness_commit_not_in_history")

        with mock.patch.object(
            shadow_replay, "load_teacher_batch", return_value=self.batch
        ), mock.patch.object(
            shadow_replay, "require_run_commit_in_history", ancestry
        ):
            return shadow_replay.publish(
                self.config,
                private_run_dir=self.private_run,
                teacher_private_dir=self.root / TEACHER_DIRECTORY,
            )

    def _rows(self) -> list[dict]:
        path = self.root / "eval" / "results" / "runs.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()]

    def test_four_records_carry_the_imported_and_auto_contracts(self) -> None:
        result = self._publish()
        self.assertEqual(result["status"], "published")
        rows = self._rows()
        self.assertEqual(len(rows), 4)
        by_key = {(row["side"], row["config"]["partition"]): row for row in rows}
        self.assertEqual(
            set(by_key),
            {
                ("sol-static", "seed"),
                ("local-static", "seed"),
                ("sol-static", "holdout"),
                ("local-static", "holdout"),
            },
        )
        for (side, partition), row in by_key.items():
            with self.subTest(side=side, partition=partition):
                self.assertEqual(row["track"], "shadow")
                self.assertEqual(row["outcome"], "completed")
                self.assertEqual(row["cost"], {"estimated_usd": 0.0, "actual_usd": None})
                if side == "sol-static":
                    self.assertEqual(row["source"], "imported")
                    self.assertIsNone(row["binary_sha256"])
                    self.assertIsNone(row["metrics"])
                    self.assertNotIn("product", row)
                    self.assertEqual(row["artifacts"], TEACHER_DIRECTORY)
                    self.assertEqual(row["config"]["teacher_model"], "gpt-5.6-sol")
                    self.assertEqual(row["config"]["generated_at"], "2026-08-15")
                    self.assertEqual(
                        row["config"]["prompt_version"], "rondo_sol_teacher_prompt_v1"
                    )
                else:
                    self.assertEqual(row["source"], "auto")
                    self.assertEqual(row["product"], "rondo-local")
                    self.assertEqual(row["config"]["binary_product"], "rondo-local")
                    self.assertEqual(row["binary_sha256"], "b" * 64)
                    self.assertEqual(
                        row["metrics"]["metric_contract"],
                        shadow_replay.METRIC_CONTRACT_NAME,
                    )
                    self.assertEqual(row["metrics"]["vram"]["peak_bytes"], 7_000_000_000)
                    self.assertNotIn("auto_review_config", row["config"])
                    self.assertEqual(
                        row["artifacts"], f"eval-data/runs/{row['run_id']}"
                    )

    def test_paired_records_share_batch_partition_and_sample_set(self) -> None:
        self._publish()
        rows = self._rows()
        for partition in ("seed", "holdout"):
            pair = [row for row in rows if row["config"]["partition"] == partition]
            self.assertEqual(len(pair), 2)
            self.assertEqual(
                {row["config"]["teacher_batch_id"] for row in pair},
                {shadow_replay.TEACHER_BATCH_ID},
            )
            self.assertEqual(len({row["config"]["sample_set_sha256"] for row in pair}), 1)
            self.assertEqual(len({row["config"]["sample_count"] for row in pair}), 1)
        self.assertEqual(len({row["run_id"] for row in rows}), 4)

    def test_holdout_rows_are_summary_only_and_leak_no_sample(self) -> None:
        self._publish()
        holdout_ids = {
            sample.semantic_id for sample in self.batch.by_partition("holdout")
        }
        for row in self._rows():
            if row["config"]["partition"] != "holdout":
                continue
            self.assertIsNone(row["tasks"])
            serialized = json.dumps(row, sort_keys=True)
            for identifier in holdout_ids:
                self.assertNotIn(identifier, serialized)
        baseline = json.loads(
            (self.root / shadow_replay.BASELINE_RELATIVE_PATH).read_text()
        )
        serialized = json.dumps(baseline, sort_keys=True)
        for identifier in holdout_ids:
            self.assertNotIn(identifier, serialized)
        self.assertNotIn("rationale", serialized)
        self.assertNotIn("risk_tags", serialized)

    def test_seed_tasks_are_body_free_and_recompute_the_public_numbers(self) -> None:
        self._publish()
        rows = self._rows()
        auto = next(
            row
            for row in rows
            if row["side"] == "local-static" and row["config"]["partition"] == "seed"
        )
        self.assertEqual(len(auto["tasks"]), 24)
        agreed = sum(1 for task in auto["tasks"] if task["teacher_match"] is True)
        comparable = sum(1 for task in auto["tasks"] if task["decision"] is not None)
        self.assertEqual(
            auto["metrics"]["teacher_agreement"], {
                "numerator": agreed,
                "denominator": comparable,
                "rate": agreed / comparable,
            }
        )
        for task in auto["tasks"]:
            self.assertEqual(
                set(task),
                {
                    "task_id",
                    "outcome",
                    "decision",
                    "teacher_match",
                    "duration_ms",
                    "tokens_in",
                    "tokens_out",
                },
            )
        imported = next(
            row
            for row in rows
            if row["side"] == "sol-static" and row["config"]["partition"] == "seed"
        )
        self.assertEqual(
            {task["task_id"] for task in imported["tasks"]},
            {task["task_id"] for task in auto["tasks"]},
        )

    def test_baseline_recomputes_from_the_frozen_private_batch(self) -> None:
        first = self._publish()
        baseline = json.loads(
            (self.root / shadow_replay.BASELINE_RELATIVE_PATH).read_text()
        )
        expected = shadow_replay.summarize_all(self.document["outcomes"])
        self.assertEqual(baseline["metrics"], expected)
        self.assertEqual(baseline["metric_contract"], shadow_replay.METRIC_CONTRACT_NAME)
        self.assertEqual(len(baseline["runs"]), 4)
        second = self._publish()
        self.assertEqual(second["newly_published"], [])
        self.assertEqual(second["records"], first["records"])
        self.assertEqual(len(self._rows()), 4)
        self.assertEqual(
            first["baseline_sha256"],
            hashlib.sha256(
                (self.root / shadow_replay.BASELINE_RELATIVE_PATH).read_bytes()
            ).hexdigest(),
        )

    def test_publication_resumes_without_new_run_ids_after_an_interruption(self) -> None:
        real = shadow_replay._publish_record
        calls = {"count": 0}

        def stop_after_two(config, record, document):
            calls["count"] += 1
            if calls["count"] == 3:
                raise shadow_replay.ShadowReplayError("synthetic_interrupt")
            return real(config, record, document)

        with mock.patch.object(shadow_replay, "_publish_record", stop_after_two):
            with self.assertRaises(shadow_replay.ShadowReplayError):
                self._publish()
        self.assertEqual(len(self._rows()), 2)
        planned = json.loads(
            (self.private_run / "publication.json").read_text()
        )["records"]
        self._publish()
        rows = self._rows()
        self.assertEqual(len(rows), 4)
        self.assertEqual(
            [row["run_id"] for row in rows], [entry["run_id"] for entry in planned]
        )

    def test_a_drifted_private_batch_cannot_be_published(self) -> None:
        drifted = copy.deepcopy(self.document)
        drifted["outcomes"][0]["teacher_outcome"] = (
            "deny" if drifted["outcomes"][0]["teacher_outcome"] == "allow" else "allow"
        )
        drifted["outcomes"][0]["teacher_match"] = (
            None
            if drifted["outcomes"][0]["decision_outcome"] is None
            else drifted["outcomes"][0]["decision_outcome"]
            == drifted["outcomes"][0]["teacher_outcome"]
        )
        (self.private_run / "run.json").unlink()
        shadow_replay._write_private_json(self.private_run / "run.json", drifted)
        with self.assertRaises(shadow_replay.ShadowReplayError):
            self._publish()
        self.assertFalse((self.root / "eval" / "results" / "runs.jsonl").exists())

    def test_a_rewritten_harness_history_refuses_publication(self) -> None:
        with self.assertRaises(shadow_replay.ShadowReplayError):
            self._publish(in_history=False)
        self.assertFalse((self.root / "eval" / "results" / "runs.jsonl").exists())

    def test_publication_stays_reproducible_after_later_commits(self) -> None:
        """The delivered state must still recompute and republish as a no-op.

        `HEAD` necessarily moves after the run (results and documentation are
        commits of their own), so publication binds the recorded run commit by
        ancestry instead of equality.
        """

        repo = self.root / "history"
        repo.mkdir()
        def git(*args):
            return subprocess.run(
                ("git", "-C", str(repo), *args),
                check=True, capture_output=True, text=True,
                env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                     "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                     "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"},
            ).stdout.strip()

        git("init", "-q", "-b", "main")
        (repo / "harness.txt").write_text("frozen", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "harness")
        run_commit = git("rev-parse", "HEAD")
        (repo / "results.txt").write_text("published", encoding="utf-8")
        git("add", "-A")
        git("commit", "-q", "-m", "results")
        moved = git("rev-parse", "HEAD")

        self.assertNotEqual(run_commit, moved)
        shadow_replay.require_run_commit_in_history(repo, run_commit)
        with self.assertRaises(shadow_replay.ShadowReplayError):
            shadow_replay.require_run_commit_in_history(repo, "b" * 40)
        with self.assertRaises(shadow_replay.ShadowReplayError):
            shadow_replay.require_run_commit_in_history(repo, "not-a-commit")

    def test_an_incomplete_vram_window_blocks_publication(self) -> None:
        broken = copy.deepcopy(self.document)
        broken["vram"]["complete"] = False
        (self.private_run / "run.json").unlink()
        shadow_replay._write_private_json(self.private_run / "run.json", broken)
        with self.assertRaises(shadow_replay.ShadowReplayError):
            self._publish()


class ImportedRowContractTests(unittest.TestCase):
    """The tracked index itself has to understand the imported contract."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.paths = RepoPaths(self.root, self.root)
        (self.root / TEACHER_DIRECTORY).mkdir(parents=True)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _imported(self, run_id: str) -> dict:
        return {
            "schema_version": 1,
            "run_id": run_id,
            "created_at": "2026-08-15T10:00:00+08:00",
            "track": "shadow",
            "side": "sol-static",
            "source": "imported",
            "git_commit": "a" * 40,
            "git_dirty": False,
            "binary_sha256": None,
            "upstream_codex": {
                "tag": "rust-v0.147.0",
                "commit": "be6e8eac029b183056b7e4402879f15d2c85f61b",
                "workspace_lock_normalization": "135 workspace packages: 0.0.0 -> 0.147.0",
            },
            "config": {
                "teacher_model": "gpt-5.6-sol",
                "generated_at": "2026-08-15",
                "prompt_version": "rondo_sol_teacher_prompt_v1",
                "prompt_sha256": "2" * 64,
            },
            "outcome": "completed",
            "summary": {"samples": 24},
            "tasks": None,
            "metrics": None,
            "cost": {"estimated_usd": 0.0, "actual_usd": None},
            "artifacts": TEACHER_DIRECTORY,
            "notes": "",
        }

    def test_imported_row_publishes_without_claiming_a_run_tree(self) -> None:
        run_id = "20260815-100000001-shadow-sol-static-r1"
        record = self._imported(run_id)
        writer = ArtifactWriter(
            self.paths, run_id, artifacts_reference=TEACHER_DIRECTORY
        ).start()
        writer.finalize(record, secrets=())
        self.assertFalse((self.root / "eval-data" / "runs" / run_id).exists())
        rows = [
            json.loads(line)
            for line in (self.root / "eval/results/runs.jsonl").read_text().splitlines()
        ]
        self.assertEqual(rows, [record])
        with self.assertRaises(ArtifactError):
            ArtifactWriter(
                self.paths, run_id, artifacts_reference=TEACHER_DIRECTORY
            ).start()

    def test_imported_rows_cannot_fake_automated_run_fields(self) -> None:
        cases = {
            "binary": {"binary_sha256": "b" * 64},
            "metrics": {"metrics": {"agreement": 1.0}},
            "spend": {"cost": {"estimated_usd": 1.0, "actual_usd": None}},
            "settled": {"cost": {"estimated_usd": 0.0, "actual_usd": 0.0}},
            "product": {"product": "rondo-local"},
            "run_artifacts": {"artifacts": "eval-data/runs/x"},
            "missing_teacher": {"config": {"teacher_model": "gpt-5.6-sol"}},
        }
        for index, (name, override) in enumerate(cases.items(), start=10):
            with self.subTest(case=name):
                run_id = f"20260815-1000000{index}-shadow-sol-static-r1"
                record = {**self._imported(run_id), **override}
                writer = ArtifactWriter(
                    self.paths, run_id, artifacts_reference=TEACHER_DIRECTORY
                ).start()
                with self.assertRaises(ArtifactError):
                    writer.finalize(record, secrets=())
                writer.abort()

    def test_side_and_source_must_agree_in_the_unified_validator(self) -> None:
        """The mapping is a contract, not a convention of one builder."""

        cases = {
            "imported_local": ("local-static", "imported"),
            "auto_teacher": ("sol-static", "auto"),
            "unmapped_side": ("luna-static", "imported"),
            "unmapped_side_auto": ("luna-static", "auto"),
        }
        for index, (name, (side, source)) in enumerate(cases.items(), start=30):
            with self.subTest(case=name):
                run_id = f"20260815-1000000{index}-shadow-{side}-r1"
                record = {
                    **self._imported(run_id),
                    "side": side,
                    "source": source,
                }
                if source == "auto":
                    record["binary_sha256"] = "b" * 64
                    record["metrics"] = {"agreement": 1.0}
                    record["artifacts"] = f"eval-data/runs/{run_id}"
                with self.assertRaises(ArtifactError):
                    artifacts._validate_record(record, run_id, self.root)

    def test_a_holdout_row_can_never_publish_per_task_results(self) -> None:
        holdout_task = [{"task_id": "hidden-sample", "outcome": "allow"}]
        for index, key in enumerate(("taskset", "partition"), start=40):
            with self.subTest(key=key):
                run_id = f"20260815-1000000{index}-shadow-sol-static-r1"
                record = self._imported(run_id)
                record["config"] = {**record["config"], key: "holdout"}
                record["tasks"] = holdout_task
                with self.assertRaisesRegex(ArtifactError, "holdout"):
                    artifacts._validate_record(record, run_id, self.root)
                record["tasks"] = None
                artifacts._validate_record(record, run_id, self.root)
        # A seed row keeps its body-free per-sample projection.
        run_id = "20260815-100000049-shadow-sol-static-r1"
        seed = self._imported(run_id)
        seed["config"] = {**seed["config"], "taskset": "seed", "partition": "seed"}
        seed["tasks"] = [{"task_id": "seed-sample", "outcome": "allow"}]
        artifacts._validate_record(seed, run_id, self.root)

    def test_shadow_rows_must_declare_their_source(self) -> None:
        run_id = "20260815-100000099-shadow-sol-static-r1"
        record = self._imported(run_id)
        record.pop("source")
        writer = ArtifactWriter(
            self.paths, run_id, artifacts_reference=TEACHER_DIRECTORY
        ).start()
        with self.assertRaises(ArtifactError):
            writer.finalize(record, secrets=())
        writer.abort()

    def test_non_shadow_tracks_cannot_carry_a_source(self) -> None:
        run_id = "20260815-100000098-tb-rondo-r1"
        record = {
            **self._imported("20260815-100000098-shadow-sol-static-r1"),
            "run_id": run_id,
            "track": "tb",
            "side": "rondo",
            "artifacts": f"eval-data/runs/{run_id}",
            "binary_sha256": "b" * 64,
        }
        writer = ArtifactWriter(self.paths, run_id).start()
        with self.assertRaises(ArtifactError):
            writer.finalize(record, secrets=())
        writer.abort()


if __name__ == "__main__":
    unittest.main()
