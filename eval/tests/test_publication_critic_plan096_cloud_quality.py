from __future__ import annotations

import copy
from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = REPO_ROOT / "eval"
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.cloud_quality.archive import (  # noqa: E402
    CloudQualityArchive,
)
from rondo_eval.publication_critic.cloud_quality.contract import (  # noqa: E402
    FORMAL_INCOMPLETE,
    FREEZE_SCHEMA,
    HEADROOM_RULE,
    PLAN066_BUNDLE_MANIFEST_SHA256,
    QUALITY_FLOORS,
    REQUESTED_MODEL,
    TERMINALS,
    VALIDATION_COUNTS,
    VALIDATION_RELEASE_SHA256,
    V8_MANIFEST_CONTENT_SHA256,
    V8_MANIFEST_FILE_SHA256,
    CloudQualityError,
    build_freeze,
    freeze_sha256,
    validate_freeze,
)
from rondo_eval.publication_critic.cloud_quality.cost import (  # noqa: E402
    attempts_cost_rmb,
    require_next_logical_call_budget,
    usage_cost_rmb,
)
from rondo_eval.publication_critic.cloud_quality.history import (  # noqa: E402
    project_historical_results,
)
from rondo_eval.publication_critic.cloud_quality.runner import (  # noqa: E402
    RustSubprocessEvaluator,
    _normalize_rust_observation,
    _stderr_attempts,
    _terminal,
    build_scores_document,
    recompute,
    run_commissioning,
    score_items,
    tracked_projection,
)
from rondo_eval.publication_critic.selection.contract import (  # noqa: E402
    SELECTION_METHOD,
)
from rondo_eval.publication_critic.selection.release import (  # noqa: E402
    SCHEMA as RELEASE_SCHEMA,
    validate_release,
)


def _freeze(*, mode: str = "formal", suffix: str = "unit") -> dict[str, object]:
    run_id = f"plan096-{mode}-20260827T120000Z-{suffix}"
    return validate_freeze(
        {
            "schema": FREEZE_SCHEMA,
            "source": {
                "git_commit": "1" * 40,
                "tracked_source_clean": True,
                "tracked_contract_sha256": "2" * 64,
                "environment_lock_sha256": "3" * 64,
                "scalar_executable_sha256": "4" * 64,
            },
            "provider": {
                "provider_identity": "deepseek-official",
                "api_shape": "chat-completions-json-object-v1",
                "endpoint_identity": "https://api.deepseek.com/chat/completions",
                "requested_model": REQUESTED_MODEL,
                "documented_model_version": "DeepSeek-V4-Flash-0731",
                "serving_revision": "provider-managed-unverifiable",
                "effective_model_policy": "exact-requested-and-served-model-v1",
                "response_model_policy": "required-exact-echo-reject-drift-v1",
                "thinking": "request-omitted-provider-default-documented-enabled",
                "reasoning_effort": "request-omitted-provider-default-documented-high",
            },
            "scorer": {
                "descriptor": "eval/locks/publication-critic-plan096-cloud-descriptor-v1.json",
                "descriptor_sha256": "5" * 64,
                "scorer_identity": "rondo-cloud-reference-deepseek-v4-flash@v1",
                "template_identity": "rondo-publication-cloud-template@v1",
                "projection_identity": "rondo-cloud-json-quality-scalar@v1",
                "domain": "finite-unit-interval-higher-is-better",
                "strict_parser": "single-json-quality-number-finish-stop-v1",
            },
            "request": {
                "temperature": 0.0,
                "top_p": None,
                "max_completion_tokens": 4096,
                "seed": None,
                "stream": False,
                "response_format": "json_object",
            },
            "retry": {
                "max_attempts": 2,
                "retryable_http_statuses": [408, 425, 429, 500, 502, 503],
                "retryable_failure_kinds": ["provider_transport"],
                "backoff_seconds": [1.0],
                "connect_timeout_seconds": 10.0,
                "request_timeout_seconds": 60.0,
            },
            "validation": {
                "dataset_revision": "v8",
                "manifest_content_sha256": V8_MANIFEST_CONTENT_SHA256,
                "manifest_file_sha256": V8_MANIFEST_FILE_SHA256,
                "bundle_manifest_sha256": PLAN066_BUNDLE_MANIFEST_SHA256,
                "release_sha256": VALIDATION_RELEASE_SHA256,
                **VALIDATION_COUNTS,
            },
            "metrics": {
                "threshold_search": SELECTION_METHOD["threshold_search"],
                "threshold_rule": SELECTION_METHOD["threshold_rule"],
                "quality_floors": QUALITY_FLOORS,
                "headroom_rule": HEADROOM_RULE,
            },
            "cost": {
                "currency": "CNY",
                "price_source_url": (
                    "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"
                ),
                "price_observed_at": "2026-08-27T12:00:00Z",
                "rates_per_million_tokens": {
                    "cache_hit_input": "0.05",
                    "cache_miss_input": "1.5",
                    "output": "4.5",
                },
                "price_tier": "off_peak",
                "price_tier_rule": (
                    "beijing_weekdays_09:00-12:00_and_14:00-18:00_peak_"
                    "otherwise_off_peak"
                ),
                "unknown_attempt_fallback_rmb": "1",
                "budget_cap_rmb": "30",
            },
            "commissioning": (
                None
                if mode == "commissioning"
                else {
                    "run_id": "plan096-commissioning-20260827T110000Z-unit",
                    "input_sha256": "6" * 64,
                    "scores_sha256": "7" * 64,
                    "result_sha256": "8" * 64,
                }
            ),
            "namespace": {
                "run_id": run_id,
                "mode": mode,
                "runs_root_identity": "eval-data/publication-critic/plan096",
                "formal_empty_required": mode == "formal",
                "write_once": "write-once-namespace-v1",
            },
        }
    )


def _release() -> dict[str, object]:
    identifiers = [f"pc096-{index:02d}" for index in range(55)]
    labels = ["PASS"] * 34 + ["REWRITE"] * 21
    pairs = []
    for index in range(19):
        pairs.append(
            {
                "pair_id": f"boundary-{index:02d}",
                "kind": "boundary",
                "preferred_candidate_id": identifiers[index],
                "dispreferred_candidate_id": identifiers[34 + index],
                "target_dimension": "quality",
            }
        )
    for index in range(7):
        pairs.append(
            {
                "pair_id": f"within-{index:02d}",
                "kind": "within_pass",
                "preferred_candidate_id": identifiers[index],
                "dispreferred_candidate_id": identifiers[7 + index],
                "target_dimension": "quality",
            }
        )
    pairs.sort(key=lambda row: row["pair_id"])
    return validate_release(
        {
            "schema": RELEASE_SCHEMA,
            "split": "validation",
            "dataset_revision": "v8",
            "dataset_manifest_sha256": V8_MANIFEST_FILE_SHA256,
            "authorization": {
                "kind": "frozen_protocol_split",
                "selection_lock_sha256": None,
            },
            "items": [
                {
                    "candidate_id": candidate_id,
                    "packet": {"publications": [{"body": candidate_id}]},
                    "dropped_oldest_publications": 0,
                }
                for candidate_id in identifiers
            ],
            "supervision": [
                {
                    "candidate_id": candidate_id,
                    "binary_label": label,
                    "publication_class": "test",
                    "completion_state": "complete",
                    "actor_role": "producer",
                    "hard_focus": "quality",
                    "length_bucket": "short",
                    "style": "plain",
                    "unicode": False,
                    "scenario_id": f"scenario-{index:02d}",
                    "scenario_group": f"group-{index:02d}",
                    "slices": ["synthetic"],
                }
                for index, (candidate_id, label) in enumerate(zip(identifiers, labels))
            ],
            "pairs": pairs,
        }
    )


def _attempt(*, usage: bool = True) -> dict[str, object]:
    return {
        "attempt": 1,
        "outcome": "success",
        "usage": (
            {
                "prompt_tokens": 100,
                "completion_tokens": 10,
                "cache_hit_tokens": 40,
                "cache_miss_tokens": 60,
            }
            if usage
            else None
        ),
        "failure_kind": None,
        "failure_code": None,
    }


class FakeEvaluator:
    def __init__(self, labels: dict[str, str]) -> None:
        self.labels = labels
        self.seen: list[tuple[str, dict[str, object]]] = []

    def evaluate(self, candidate_id: str, packet: dict[str, object]) -> dict[str, object]:
        self.seen.append((candidate_id, packet))
        return {
            "status": "success",
            "score": 0.9 if self.labels[candidate_id] == "PASS" else 0.1,
            "requested_model": REQUESTED_MODEL,
            "effective_model": REQUESTED_MODEL,
            "attempts": [_attempt()],
            "elapsed_ms": 1.0,
            "failure_kind": None,
            "failure_code": None,
            "failure_disposition": None,
        }


class ContractAndCostTest(unittest.TestCase):
    def test_builder_emits_the_exact_provider_request_and_retry_contract(self) -> None:
        built = build_freeze(
            source=_freeze()["source"],
            descriptor_sha256="5" * 64,
            price_observed_at="2026-08-27T12:00:00Z",
            commissioning=_freeze()["commissioning"],
            run_id=_freeze()["namespace"]["run_id"],
            mode="formal",
        )
        self.assertEqual(built, _freeze())

    def test_freeze_rejects_model_or_price_drift(self) -> None:
        freeze = _freeze()
        drifted = copy.deepcopy(freeze)
        drifted["provider"]["requested_model"] = "another-model"
        with self.assertRaises(CloudQualityError):
            validate_freeze(drifted)
        drifted = copy.deepcopy(freeze)
        drifted["cost"]["rates_per_million_tokens"]["output"] = 2.1
        with self.assertRaises(CloudQualityError):
            validate_freeze(drifted)

    def test_decimal_cost_uses_cache_classes_and_unknown_fallback(self) -> None:
        self.assertEqual(
            usage_cost_rmb(_attempt()["usage"]),
            Decimal("0.000137"),
        )
        self.assertEqual(attempts_cost_rmb([_attempt(usage=False)]), Decimal("1"))
        unknown_cache = dict(_attempt()["usage"])
        unknown_cache["cache_hit_tokens"] = None
        unknown_cache["cache_miss_tokens"] = None
        self.assertEqual(usage_cost_rmb(unknown_cache), Decimal("0.000195"))

    def test_budget_reserves_all_frozen_attempts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "plan096-commissioning-20260827T120000Z-budget"
            run.mkdir(parents=True)
            for index in range(29):
                (run / f"call-{index}.json").write_text(
                    json.dumps({"conservative_cost_rmb": "1"}), encoding="utf-8"
                )
            with self.assertRaisesRegex(
                CloudQualityError, "budget_insufficient_for_next_logical_call"
            ):
                require_next_logical_call_budget(root, max_attempts=2)

    def test_rust_success_normalizes_attempts_and_cache_usage(self) -> None:
        outcome = _normalize_rust_observation(
            {
                "requested_model": REQUESTED_MODEL,
                "served_model": REQUESTED_MODEL,
                "score": 0.75,
                "attempts": 2,
                "elapsed_ms": 250,
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 10,
                    "total_tokens": 110,
                    "prompt_cache_hit_tokens": 40,
                    "prompt_cache_miss_tokens": 60,
                },
                "outcome": {"type": "success"},
            }
        )
        self.assertEqual(outcome["status"], "success")
        self.assertEqual(len(outcome["attempts"]), 2)
        self.assertIsNone(outcome["attempts"][0]["usage"])
        self.assertEqual(
            outcome["attempts"][1]["usage"],
            {
                "prompt_tokens": 100,
                "completion_tokens": 10,
                "cache_hit_tokens": 40,
                "cache_miss_tokens": 60,
            },
        )
        self.assertEqual(
            attempts_cost_rmb(outcome["attempts"]), Decimal("1.000137")
        )

    def test_rust_failure_preserves_model_kind_and_attempt_count(self) -> None:
        outcome = _normalize_rust_observation(
            {
                "requested_model": REQUESTED_MODEL,
                "served_model": "unexpected-served-model",
                "score": 0.75,
                "attempts": 1,
                "elapsed_ms": 250,
                "usage": {
                    "prompt_tokens": 100,
                    "completion_tokens": 10,
                    "total_tokens": 110,
                    "prompt_cache_hit_tokens": None,
                    "prompt_cache_miss_tokens": None,
                },
                "outcome": {
                    "type": "failure",
                    "kind": "model_identity_mismatch",
                    "http_status": None,
                },
            }
        )
        self.assertEqual(outcome["status"], "failure")
        self.assertEqual(outcome["effective_model"], "unexpected-served-model")
        self.assertEqual(outcome["failure_code"], "model_identity_mismatch")
        self.assertEqual(outcome["failure_disposition"], "effective_model_failure")
        self.assertEqual(len(outcome["attempts"]), 1)

    def test_terminal_provider_status_is_not_mislabeled_retryable(self) -> None:
        outcome = _normalize_rust_observation(
            {
                "requested_model": REQUESTED_MODEL,
                "served_model": None,
                "score": None,
                "attempts": 1,
                "elapsed_ms": 25,
                "usage": None,
                "outcome": {
                    "type": "failure",
                    "kind": "provider_http_status",
                    "http_status": 401,
                },
            }
        )
        self.assertEqual(outcome["failure_disposition"], "permanent_failure")

    def test_timeout_uses_body_free_started_attempt_marker(self) -> None:
        self.assertEqual(
            _stderr_attempts(
                b"publication_critic_cloud_attempt attempt=1\n"
                b"publication_critic_cloud_attempt attempt=2\n"
            ),
            2,
        )
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "cloud-eval"
            executable.touch()
            evaluator = RustSubprocessEvaluator(
                executable=executable,
                arguments=(),
                credential_env={"DEEPSEEK_API_KEY": "unit-not-a-secret"},
                timeout_seconds=1.0,
            )
            expired = subprocess.TimeoutExpired(
                cmd=[str(executable)],
                timeout=1.0,
                stderr=(
                    b"publication_critic_cloud_attempt attempt=1\n"
                    b"publication_critic_cloud_attempt attempt=2\n"
                ),
            )
            with mock.patch(
                "rondo_eval.publication_critic.cloud_quality.runner.subprocess.run",
                side_effect=expired,
            ):
                outcome = evaluator.evaluate("candidate", {"publications": []})
        self.assertEqual(outcome["status"], "failure")
        self.assertEqual(len(outcome["attempts"]), 2)


class ArchiveAndRunnerTest(unittest.TestCase):
    def test_fake_55_blind_chain_recomputes_and_claims_authority(self) -> None:
        release = _release()
        labels = {
            row["candidate_id"]: row["binary_label"]
            for row in release["supervision"]
        }
        freeze = _freeze()
        items = [
            {"candidate_id": row["candidate_id"], "packet": row["packet"]}
            for row in release["items"]
        ]
        evaluator = FakeEvaluator(labels)
        with tempfile.TemporaryDirectory() as directory:
            archive = CloudQualityArchive(
                Path(directory), freeze["namespace"]["run_id"], "formal"
            ).create(freeze)
            rows, failures = score_items(
                freeze, items, archive=archive, evaluator=evaluator
            )
            self.assertEqual((len(rows), len(failures)), (55, 0))
            self.assertEqual(len(evaluator.seen), 55)
            self.assertTrue(all(set(packet) == {"publications"} for _, packet in evaluator.seen))
            scores = build_scores_document(freeze, rows, failures)
            with mock.patch(
                "rondo_eval.publication_critic.cloud_quality.runner.release_sha256",
                return_value=VALIDATION_RELEASE_SHA256,
            ):
                result = recompute(freeze, release, scores)
            self.assertEqual(result["terminal"], TERMINALS[0])
            self.assertEqual(len(result["metrics"]["rows"]), 55)
            self.assertIsNone(result["metrics"]["raw_logit_distribution"])
            summary = tracked_projection(freeze, result)
            self.assertEqual(len(summary["rows"]), 55)
            self.assertEqual(summary["freeze"], freeze)
            self.assertTrue(all(set(row) == {"candidate_id", "label", "score"} for row in summary["rows"]))
            archive.claim_formal_result(freeze, result)
            self.assertIsNotNone(archive.load_authority())

    def test_commissioning_exact_resume_and_formal_empty(self) -> None:
        release = _release()
        labels = {
            row["candidate_id"]: row["binary_label"]
            for row in release["supervision"]
        }
        items = [
            {"candidate_id": row["candidate_id"], "packet": row["packet"]}
            for row in release["items"][:2]
        ]
        freeze = _freeze(mode="commissioning", suffix="resume")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive = CloudQualityArchive(
                root, freeze["namespace"]["run_id"], "commissioning"
            ).create(freeze)
            rows, failures = score_items(
                freeze, items, archive=archive, evaluator=FakeEvaluator(labels)
            )
            self.assertEqual((len(rows), len(failures)), (2, 0))

            class UnexpectedEvaluator:
                def evaluate(self, candidate_id: str, packet: object) -> object:
                    raise AssertionError((candidate_id, packet))

            resumed = CloudQualityArchive(
                root, freeze["namespace"]["run_id"], "commissioning"
            ).create(freeze)
            rows, failures = score_items(
                freeze, items, archive=resumed, evaluator=UnexpectedEvaluator()
            )
            self.assertEqual((len(rows), len(failures)), (2, 0))
            drifted = copy.deepcopy(freeze)
            drifted["source"]["tracked_contract_sha256"] = "9" * 64
            with self.assertRaisesRegex(CloudQualityError, "archive_binding_drifted"):
                CloudQualityArchive(
                    root, freeze["namespace"]["run_id"], "commissioning"
                ).create(drifted)

        formal = _freeze(suffix="empty")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            CloudQualityArchive(
                root, formal["namespace"]["run_id"], "formal"
            ).create(formal)
            with self.assertRaisesRegex(CloudQualityError, "formal_namespace_not_empty"):
                CloudQualityArchive(
                    root, formal["namespace"]["run_id"], "formal"
                ).create(formal)

    def test_commissioning_binds_formal_freeze_input(self) -> None:
        release = _release()
        labels = {
            row["candidate_id"]: row["binary_label"]
            for row in release["supervision"]
        }
        items = [
            {"candidate_id": row["candidate_id"], "packet": row["packet"]}
            for row in release["items"]
        ]
        freeze = _freeze(mode="commissioning", suffix="binding")
        with tempfile.TemporaryDirectory() as directory:
            result, binding = run_commissioning(
                freeze,
                items,
                runs_root=Path(directory),
                evaluator=FakeEvaluator(labels),
            )
            bound = json.loads(
                (
                    Path(directory)
                    / freeze["namespace"]["run_id"]
                    / "commissioning-binding.json"
                ).read_text(encoding="utf-8")
            )
        self.assertTrue(result["complete"])
        self.assertEqual(bound, binding)

    def test_failure_stops_formal_and_incomplete_cannot_claim(self) -> None:
        freeze = _freeze(suffix="failure")
        items = [
            {"candidate_id": f"candidate-{index}", "packet": {"value": index}}
            for index in range(3)
        ]

        class FailedEvaluator:
            calls = 0

            def evaluate(self, candidate_id: str, packet: object) -> dict[str, object]:
                del candidate_id, packet
                self.calls += 1
                return {
                    "status": "failure",
                    "score": None,
                    "requested_model": REQUESTED_MODEL,
                    "effective_model": REQUESTED_MODEL,
                    "attempts": [
                        {
                            "attempt": 1,
                            "outcome": "failure",
                            "usage": None,
                            "failure_kind": "ModelFailure",
                            "failure_code": "malformed_scalar",
                        }
                    ],
                    "elapsed_ms": 1.0,
                    "failure_kind": "ModelFailure",
                    "failure_code": "malformed_scalar",
                    "failure_disposition": "effective_model_failure",
                }

        evaluator = FailedEvaluator()
        with tempfile.TemporaryDirectory() as directory:
            archive = CloudQualityArchive(
                Path(directory), freeze["namespace"]["run_id"], "formal"
            ).create(freeze)
            rows, failures = score_items(
                freeze, items, archive=archive, evaluator=evaluator
            )
            self.assertEqual((len(rows), len(failures), evaluator.calls), (0, 1, 1))
            result = {
                "complete": False,
                "terminal": FORMAL_INCOMPLETE,
                "scored_count": 0,
                "typed_failure_count": 1,
            }
            with self.assertRaises(CloudQualityError):
                archive.claim_formal_result(freeze, result)


class RecomputeAndHistoryTest(unittest.TestCase):
    def test_four_terminals_and_floor_equality(self) -> None:
        passing = {
            "roc_auc": QUALITY_FLOORS["min_roc_auc"],
            "boundary_pairs": {
                "strict_win_rate": QUALITY_FLOORS[
                    "min_boundary_pair_strict_win_rate"
                ]
            },
        }
        self.assertEqual(_terminal([], passing), TERMINALS[0])
        self.assertEqual(_terminal(["no_admissible_operating_point"], passing), TERMINALS[1])
        low = copy.deepcopy(passing)
        low["roc_auc"] -= 0.01
        low["boundary_pairs"]["strict_win_rate"] -= 0.01
        self.assertEqual(_terminal(["x"], low), TERMINALS[2])
        mixed = copy.deepcopy(passing)
        mixed["roc_auc"] -= 0.01
        self.assertEqual(_terminal(["x"], mixed), TERMINALS[3])

    def test_scores_reject_duplicate_drift_and_missing_is_incomplete(self) -> None:
        freeze = _freeze(suffix="integrity")
        release = _release()
        labels = {
            row["candidate_id"]: row["binary_label"]
            for row in release["supervision"]
        }
        evaluator = FakeEvaluator(labels)
        with tempfile.TemporaryDirectory() as directory:
            archive = CloudQualityArchive(
                Path(directory), freeze["namespace"]["run_id"], "formal"
            ).create(freeze)
            items = [
                {"candidate_id": row["candidate_id"], "packet": row["packet"]}
                for row in release["items"][:2]
            ]
            rows, failures = score_items(
                freeze, items, archive=archive, evaluator=evaluator
            )
            scores = build_scores_document(freeze, rows, failures)
            with mock.patch(
                "rondo_eval.publication_critic.cloud_quality.runner.release_sha256",
                return_value=VALIDATION_RELEASE_SHA256,
            ):
                result = recompute(freeze, release, scores)
            self.assertEqual(result["terminal"], FORMAL_INCOMPLETE)
            duplicate = copy.deepcopy(scores)
            duplicate["rows"].append(copy.deepcopy(duplicate["rows"][0]))
            drifted = copy.deepcopy(scores)
            drifted["rows"][0]["effective_model"] = "other-model"
            with mock.patch(
                "rondo_eval.publication_critic.cloud_quality.runner.release_sha256",
                return_value=VALIDATION_RELEASE_SHA256,
            ):
                with self.assertRaisesRegex(CloudQualityError, "duplicate"):
                    recompute(freeze, release, duplicate)
                with self.assertRaisesRegex(CloudQualityError, "model_mismatch"):
                    recompute(freeze, release, drifted)

    def test_tracked_history_projection_is_exact_and_excludes_calibration(self) -> None:
        one = json.loads(
            (REPO_ROOT / "eval/results/publication-critic/m3-c2-joint-selection-v1.json").read_text()
        )
        four = json.loads(
            (
                REPO_ROOT
                / "eval/results/publication-critic/skywork-reward-v2-qwen3-4b-base-quality-v1.json"
            ).read_text()
        )
        projected = project_historical_results(one, four)
        self.assertEqual(
            projected["exact_1_7b"]["release_sha256"], VALIDATION_RELEASE_SHA256
        )
        self.assertEqual(
            projected["exact_4b"]["release_sha256"], VALIDATION_RELEASE_SHA256
        )
        self.assertIn("raw_logit", projected["comparison_scope"]["not_compared"])
        self.assertNotIn(
            "raw_logit", projected["exact_1_7b"]["metrics"]
        )


if __name__ == "__main__":
    unittest.main()
