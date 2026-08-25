from __future__ import annotations

import copy
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = REPO_ROOT / "eval"
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.local_deployment.comparability import (  # noqa: E402
    FREEZE_SCHEMA,
    FORMAL_SAMPLE_IDS,
    FORMAL_THRESHOLD,
    OBSERVATIONS_SCHEMA,
    RESULT_SCHEMA,
    SERVICE_RESULT_SCHEMA,
    QualificationError,
    evaluate_run,
    freeze_sha256,
    validate_freeze,
)
from rondo_eval.publication_critic.local_deployment.qualification import (  # noqa: E402
    FREEZE_SCHEMA as PLAN068_FREEZE_SCHEMA,
    validate_freeze as validate_plan068_freeze,
)
from rondo_eval.publication_critic.local_deployment.comparability_observations import (  # noqa: E402
    MANIFEST_SCHEMA,
    build_observations,
)
from rondo_eval.publication_critic.local_deployment.service_runner import (  # noqa: E402
    RESULT_SCHEMA as PLAN068_SERVICE_RESULT_SCHEMA,
    _freeze_contract,
    main as service_main,
)
from rondo_eval.publication_critic.scoring import project_logit  # noqa: E402
from rondo_eval.publication_critic.identity import sha256_file  # noqa: E402
from rondo_eval.publication_critic.identity import (  # noqa: E402
    canonical_json_bytes,
    sha256_bytes,
)
from rondo_eval.publication_critic.local_deployment.worker_parity import (  # noqa: E402
    RESULT_SCHEMA as WORKER_PARITY_SCHEMA,
)
from eval.tests.test_publication_critic_plan068_service_runner import (  # noqa: E402
    Fixture as Plan068ServiceFixture,
)


SAMPLE_IDS = list(FORMAL_SAMPLE_IDS)
THRESHOLD_RAW = math.log(FORMAL_THRESHOLD / (1.0 - FORMAL_THRESHOLD))


def _raw(first_four: list[float]) -> list[float]:
    return [*first_four, *([1.0, -1.0] * 10)]


def _freeze(
    *,
    mode: str = "formal",
    run_id: str = "plan071-formal-20260824T120000Z-comparability",
) -> dict[str, object]:
    return {
        "schema": FREEZE_SCHEMA,
        "mode": mode,
        "run_id": run_id,
        "qualification_objects": ["base", "c1", "c3"],
        "cohort": {"sample_ids": SAMPLE_IDS, "future_unseen_test": False},
        "service_parity_input": {
            "sample_id": SAMPLE_IDS[0],
            "packet_sha256": "1" * 64,
        },
        "threshold": {
            "source": "plan054-calibration-threshold-v4",
            "projected_score": FORMAL_THRESHOLD,
        },
        "reference_method": "same-original-safetensors-cpu-float32-v1",
        "source": {
            "git_commit": "a" * 40,
            "tracked_source_clean": True,
            "environment_lock_path": "eval/environments/publication-critic-plan068/uv.lock",
            "environment_lock_sha256": "b" * 64,
        },
        "artifacts": {
            object_id: {
                "candidate_artifact_sha256": character * 64,
                "deployment_artifact_sha256": character * 64,
                "service_descriptor_sha256": character * 64,
            }
            for object_id, character in zip(("base", "c1", "c2", "c3"), "cdef")
        },
        "runtime": {
            "device": "cuda",
            "dtype": "bfloat16",
            "cpu_threads": 4,
            "deployment_format": "direct-transformers-safetensors-no-conversion-v1",
            "programs": {
                "service_sha256": "6" * 64,
                "probe_sha256": "7" * 64,
                "python_sha256": "8" * 64,
            },
            "service_limits": {
                "request_bytes": 131_072,
                "response_bytes": 16_384,
                "max_concurrency": 1,
                "queue_capacity": 8,
                "job_timeout_ms": 25_000,
                "io_timeout_ms": 2_000,
                "worker_startup_timeout_ms": 20_000,
                "worker_io_timeout_ms": 5_000,
                "worker_shutdown_timeout_ms": 5_000,
                "graceful_shutdown_ms": 3_000,
                "force_shutdown_ms": 2_000,
                "call_timeout_ms": 30_000,
                "startup_timeout_ms": 60_000,
                "process_timeout_ms": 60_000,
                "representative_cancel_after_ms": 1,
            },
        },
        "comparability_method": {
            "cross_runtime_raw": "absolute_raw_logit_cap_v1",
            "cross_runtime_projection": "stable_sigmoid_interval_from_raw_cap_v1",
            "temporary_verdict": "require_match_outside_reference_raw_guard_v1",
            "deployment_worker_parity": "same_runtime_absolute_drift_v1",
            "service_verdict": "exact_descriptor_threshold_v1",
            "lifecycle": "basic_shutdown_recheck_with_plan068_v3_matrix_unchanged_v1",
        },
        "gates": {
            "max_cross_runtime_raw_logit_absolute_drift": 0.25,
            "max_projection_envelope_excess": 1e-12,
            "min_ranking_concordance": 0.7,
            "reference_obvious_margin_floor": 0.1,
            "min_obvious_margin_direction_agreement": 0.8,
            "min_pair_direction_agreement": 0.5,
            "max_stable_verdict_mismatches": 0,
            "max_load_seconds": 30.0,
            "max_peak_rss_bytes": 8_000_000_000,
            "max_peak_vram_bytes": 7_500_000_000,
            "max_warm_p95_latency_ms": 1_000.0,
            "max_worker_score_absolute_drift": 0.005,
            "max_worker_raw_logit_absolute_drift": 0.25,
            "max_service_verdict_mismatches": 0,
            "min_stress_success_rate": 1.0,
            "max_stress_p95_latency_ms": 2_000.0,
        },
        "stress_call_counts": [1, 2, 4, 8],
        "representative_lifecycle_object": "c1",
    }


def _rows(raw_logits: list[float]) -> list[dict[str, object]]:
    return [
        {
            "sample_id": sample_id,
            "raw_logit": raw,
            "projected_score": project_logit(raw),
            "token_count": 100 + index,
            "dropped_oldest_publications": 0,
            "model_elapsed_ms": 20.0 + index,
        }
        for index, (sample_id, raw) in enumerate(zip(SAMPLE_IDS, raw_logits))
    ]


def _success(state: str, **values: object) -> dict[str, object]:
    return {"state": state, "reason": None, "failure_scope": "none", **values}


def _observation(
    freeze: dict[str, object],
    object_id: str,
    *,
    reference_raw: list[float] | None = None,
    deployed_raw: list[float] | None = None,
) -> dict[str, object]:
    reference_raw = reference_raw or _raw([THRESHOLD_RAW + 0.01, -2.0, 1.0, -1.0])
    deployed_raw = deployed_raw or reference_raw
    artifact = freeze["artifacts"][object_id]
    observation = {
        "schema": OBSERVATIONS_SCHEMA,
        "mode": freeze["mode"],
        "run_id": freeze["run_id"],
        "qualification_freeze_sha256": freeze_sha256(freeze),
        "object_id": object_id,
        "evidence": {
            "reference_offline_sha256": "2" * 64,
            "deployment_offline_sha256": "3" * 64,
            "service_run_sha256": "4" * 64,
            "service_parity_sha256": "5" * 64,
            "service_packet_sha256": "1" * 64,
        },
        "identity": _success(
            "passed", service_descriptor_sha256=artifact["service_descriptor_sha256"]
        ),
        "artifact": _success(
            "passed",
            candidate_artifact_sha256=artifact["candidate_artifact_sha256"],
            deployment_artifact_sha256=artifact["deployment_artifact_sha256"],
        ),
        "load": _success("observed", seconds=2.0),
        "scores": _success(
            "observed",
            reference=_rows(reference_raw),
            deployment=_rows(deployed_raw),
        ),
        "resources": _success(
            "observed", peak_rss_bytes=4_000_000_000, peak_vram_bytes=4_500_000_000
        ),
        "latency": _success("observed", warm_ms=[25.0, 26.0, 27.0, 28.0]),
        "service": _success(
            "observed",
            raw_logit_absolute_differences=[0.0],
            score_absolute_differences=[0.0],
            verdict_mismatch_count=0,
            bounded_call_count=1,
        ),
        "stress": _success(
            "observed",
            success_count=15,
            call_count=15,
            latencies_ms=[30.0] * 15,
            scenario_call_counts=[1, 2, 4, 8],
        ),
        "lifecycle": _success(
            "observed",
            matrix_role="basic_with_cancel_recheck" if object_id == "c1" else "basic",
            typed_failure_verified=False,
            cancel_verified=object_id == "c1",
            graceful_shutdown_verified=True,
            forced_cleanup_verified=False,
            orphan_worker_count=0,
            body_leak_count=0,
        ),
    }
    return observation


def _run_input(
    freeze: dict[str, object], observations: list[dict[str, object]]
) -> dict[str, object]:
    return {
        "schema": OBSERVATIONS_SCHEMA,
        "mode": freeze["mode"],
        "run_id": freeze["run_id"],
        "qualification_freeze_sha256": freeze_sha256(freeze),
        "evidence_manifest_sha256": "9" * 64,
        "objects": observations,
    }


def _upgrade_service_fixture_to_plan071(fixture: Plan068ServiceFixture) -> None:
    old = json.loads(fixture.freeze.read_text(encoding="utf-8"))
    freeze = _freeze(
        mode="commissioning",
        run_id="plan071-commissioning-20260824T120001Z-service-fixture",
    )
    for name in (
        "cohort",
        "service_parity_input",
        "threshold",
        "source",
        "artifacts",
        "runtime",
        "stress_call_counts",
        "representative_lifecycle_object",
    ):
        freeze[name] = old[name]
    fixture.freeze.write_text(json.dumps(freeze), encoding="utf-8")
    descriptor = json.loads(fixture.descriptor.read_text(encoding="utf-8"))
    descriptor["qualification_freeze_sha256"] = freeze_sha256(freeze)
    fixture.descriptor.write_text(json.dumps(descriptor), encoding="utf-8")


def _write_builder_evidence(root: Path, freeze: dict[str, object]) -> dict[str, object]:
    paths: dict[str, dict[str, str]] = {}
    digest = freeze_sha256(freeze)
    expected_verdict = "pass"
    for object_id in ("base", "c1", "c3"):
        object_paths = {
            name: root / f"{object_id}-{name}.json"
            for name in (
                "reference_offline",
                "deployment_offline",
                "worker_parity",
                "service_run",
            )
        }
        rows = _rows(_raw([THRESHOLD_RAW + 0.01, -2.0, 1.0, -1.0]))
        common_offline = {
            "mode": freeze["mode"],
            "run_id": freeze["run_id"],
            "qualification_freeze_sha256": digest,
            "object_id": object_id,
            "deployment_artifact_sha256": freeze["artifacts"][object_id][
                "deployment_artifact_sha256"
            ],
            "snapshot_model_sha256": freeze["artifacts"][object_id][
                "deployment_artifact_sha256"
            ],
            "cohort_sample_ids_sha256": sha256_bytes(
                canonical_json_bytes(list(freeze["cohort"]["sample_ids"]))
            ),
            "load_seconds": 2.0,
            "rows": rows,
            "resources": {
                "process_peak_rss_bytes": 4_000_000_000,
                "cuda": {"max_reserved_bytes": 3_500_000_000},
            },
        }
        reference = {
            **common_offline,
            "schema": "rondo-publication-critic-plan071-offline-scores-v1",
            "execution_role": "reference",
            "runtime": {"device": "cpu", "dtype": "float32", "cpu_threads": 4},
        }
        deployment = {
            **common_offline,
            "schema": "rondo-publication-critic-plan071-offline-scores-v1",
            "execution_role": "deployment",
            "runtime": {"device": "cuda", "dtype": "bfloat16", "cpu_threads": 4},
        }
        object_paths["reference_offline"].write_text(json.dumps(reference), encoding="utf-8")
        object_paths["deployment_offline"].write_text(json.dumps(deployment), encoding="utf-8")
        parity = {
            "schema": WORKER_PARITY_SCHEMA,
            "mode": freeze["mode"],
            "run_id": freeze["run_id"],
            "qualification_freeze_sha256": digest,
            "object_id": object_id,
            "deployment_artifact_sha256": freeze["artifacts"][object_id][
                "deployment_artifact_sha256"
            ],
            "deployment_offline_sha256": sha256_file(object_paths["deployment_offline"]),
            "packet_sha256": freeze["service_parity_input"]["packet_sha256"],
            "sample_id": SAMPLE_IDS[0],
            "raw_logit_absolute_difference": 0.0,
            "projected_score_absolute_difference": 0.0,
            "verdict_mismatch": False,
            "token_count_matches": True,
            "dropped_oldest_publications_matches": True,
            "within_response_projection_absolute_difference": 0.0,
            "worker_load_seconds": 2.0,
            "worker_resources": {
                "process_peak_rss_bytes": 4_100_000_000,
                "cuda": {"max_reserved_bytes": 3_600_000_000},
            },
            "worker_exit_code": 0,
            "worker_reaped": True,
            "stderr_bytes": 0,
        }
        object_paths["worker_parity"].write_text(json.dumps(parity), encoding="utf-8")
        service = {
            "schema": SERVICE_RESULT_SCHEMA,
            "mode": freeze["mode"],
            "run_id": freeze["run_id"],
            "qualification_freeze_sha256": digest,
            "object_id": object_id,
            "snapshot_model_sha256": freeze["artifacts"][object_id][
                "deployment_artifact_sha256"
            ],
            "service_descriptor_sha256": freeze["artifacts"][object_id][
                "service_descriptor_sha256"
            ],
            "packet_sha256": freeze["service_parity_input"]["packet_sha256"],
            "service_sample_id": freeze["service_parity_input"]["sample_id"],
            "status": "COMPLETE",
            "failure_code": None,
            "warm_reviews": [
                {"outcome": "success", "result": expected_verdict, "latency_ms": 30.0}
                for _ in range(3)
            ],
            "stress": [
                {
                    "concurrency": count,
                    "calls": [
                        {
                            "outcome": "success",
                            "result": expected_verdict,
                            "latency_ms": 30.0,
                        }
                        for _ in range(count)
                    ],
                }
                for count in (1, 2, 4, 8)
            ],
            "shutdown": {"outcome": "success", "result": "accepted"},
            "service_exit": {"exit_code": 0, "reaped": True},
        }
        if object_id == "c1":
            service.update(
                {
                    "cancel": {"result": "cancelled"},
                    "post_cancel_ready": {"result": "ready"},
                    "post_cancel_review": {"outcome": "success"},
                }
            )
        object_paths["service_run"].write_text(json.dumps(service), encoding="utf-8")
        paths[object_id] = {name: str(path) for name, path in object_paths.items()}
    return {
        "schema": MANIFEST_SCHEMA,
        "run_id": freeze["run_id"],
        "qualification_freeze_sha256": digest,
        "objects": paths,
    }


class Plan071ComparabilityTests(unittest.TestCase):
    def test_plan071_schema_is_strict_and_does_not_widen_plan068(self) -> None:
        freeze = validate_freeze(_freeze())
        self.assertEqual(freeze["schema"], FREEZE_SCHEMA)
        with self.assertRaises(QualificationError):
            validate_plan068_freeze(freeze)

        wrong = copy.deepcopy(freeze)
        wrong["schema"] = PLAN068_FREEZE_SCHEMA
        with self.assertRaises(QualificationError):
            validate_freeze(wrong)

    def test_freeze_rejects_c2_or_unseen_in_the_qualification_set(self) -> None:
        c2 = _freeze()
        c2["qualification_objects"] = ["base", "c1", "c2", "c3"]
        with self.assertRaisesRegex(QualificationError, "identity"):
            validate_freeze(c2)

        unseen = _freeze()
        unseen["cohort"]["future_unseen_test"] = True
        with self.assertRaisesRegex(QualificationError, "cohort"):
            validate_freeze(unseen)

        subset = _freeze()
        subset["cohort"]["sample_ids"] = SAMPLE_IDS[:4]
        with self.assertRaisesRegex(QualificationError, "24-sample"):
            validate_freeze(subset)

        commissioning = _freeze(
            mode="commissioning",
            run_id="plan071-commissioning-20260824T120002Z-subset",
        )
        commissioning["cohort"]["sample_ids"] = SAMPLE_IDS[:4]
        self.assertEqual(len(validate_freeze(commissioning)["cohort"]["sample_ids"]), 4)

        threshold_drift = _freeze()
        threshold_drift["threshold"]["projected_score"] = 0.5
        with self.assertRaisesRegex(QualificationError, "threshold identity"):
            validate_freeze(threshold_drift)

        reference_drift = _freeze()
        reference_drift["reference_method"] = "other-cpu-reference"
        with self.assertRaisesRegex(QualificationError, "reference method"):
            validate_freeze(reference_drift)

    def test_raw_induced_sigmoid_envelope_allows_large_projected_drift(self) -> None:
        freeze = validate_freeze(_freeze())
        observations = [
            _observation(
                freeze,
                "base",
                reference_raw=_raw([THRESHOLD_RAW + 0.01, -2.0, 1.0, -1.0]),
                deployed_raw=_raw([THRESHOLD_RAW - 0.09, -2.0, 1.0, -1.0]),
            ),
            _observation(freeze, "c1"),
            _observation(freeze, "c3"),
        ]
        result = evaluate_run(
            _run_input(freeze, observations),
            freeze,
            mode="formal",
            run_id=freeze["run_id"],
        )

        base = result["objects"][0]
        self.assertEqual(base["conclusion"], "QUALIFIED")
        cross = base["metrics"]["cross_runtime"]["value"]
        self.assertGreater(cross["max_projected_absolute_drift"], 0.005)
        self.assertEqual(cross["max_projection_envelope_excess"], 0.0)
        self.assertEqual(cross["temporary_verdict_mismatches"], 1)
        self.assertEqual(len(cross["near_threshold_verdict_mismatch_sample_ids"]), 1)
        self.assertEqual(cross["stable_verdict_mismatch_sample_ids"], [])
        self.assertEqual(result["task_terminal"], "BASE_COMPARABILITY_GO")
        self.assertTrue(result["m3_c2_prerequisite_satisfied"])
        self.assertEqual(result["schema"], RESULT_SCHEMA)

    def test_cross_runtime_failure_keeps_reached_service_and_resource_metrics(self) -> None:
        freeze = validate_freeze(_freeze())
        observations = [
            _observation(
                freeze,
                "base",
                deployed_raw=_raw([THRESHOLD_RAW + 0.40, -2.0, 1.0, -1.0]),
            ),
            _observation(freeze, "c1"),
            _observation(freeze, "c3"),
        ]
        result = evaluate_run(
            _run_input(freeze, observations),
            freeze,
            mode="formal",
            run_id=freeze["run_id"],
        )

        base = result["objects"][0]
        self.assertEqual(base["conclusion"], "NOT_QUALIFIED")
        self.assertIn("cross_runtime_raw_logit_drift_gate_failed", base["reasons"])
        self.assertEqual(base["metrics"]["resources"]["status"], "OBSERVED")
        self.assertEqual(
            base["metrics"]["deployment_worker_parity"]["status"], "OBSERVED"
        )
        self.assertEqual(base["metrics"]["service_verdict_parity"]["status"], "OBSERVED")
        self.assertEqual(result["task_terminal"], "BASE_NOT_COMPARABLE")

    def test_stable_threshold_flip_is_not_hidden_by_the_guard(self) -> None:
        freeze = validate_freeze(_freeze())
        observations = [
            _observation(
                freeze,
                "base",
                reference_raw=_raw([THRESHOLD_RAW + 0.30, -2.0, 1.0, -1.0]),
                deployed_raw=_raw([THRESHOLD_RAW - 0.30, -2.0, 1.0, -1.0]),
            ),
            _observation(freeze, "c1"),
            _observation(freeze, "c3"),
        ]
        result = evaluate_run(
            _run_input(freeze, observations),
            freeze,
            mode="formal",
            run_id=freeze["run_id"],
        )

        base = result["objects"][0]
        self.assertIn("stable_temporary_verdict_parity_gate_failed", base["reasons"])
        self.assertEqual(
            base["metrics"]["cross_runtime"]["value"][
                "stable_verdict_mismatch_sample_ids"
            ],
            [SAMPLE_IDS[0]],
        )

    def test_infrastructure_failure_is_inconclusive(self) -> None:
        freeze = validate_freeze(_freeze())
        observations = [
            _observation(freeze, object_id) for object_id in ("base", "c1", "c3")
        ]
        observations[0]["resources"] = {
            "state": "not_reached",
            "reason": "gpu_counters_unavailable",
            "failure_scope": "infrastructure",
            "peak_rss_bytes": None,
            "peak_vram_bytes": None,
        }
        result = evaluate_run(
            _run_input(freeze, observations),
            freeze,
            mode="formal",
            run_id=freeze["run_id"],
        )

        self.assertEqual(result["objects"][0]["conclusion"], "INCONCLUSIVE")
        self.assertEqual(result["task_terminal"], "INCONCLUSIVE")
        self.assertFalse(result["m3_c2_prerequisite_satisfied"])

    def test_c1_cancel_recheck_failure_cannot_qualify(self) -> None:
        freeze = validate_freeze(_freeze())
        observations = [
            _observation(freeze, object_id) for object_id in ("base", "c1", "c3")
        ]
        observations[1]["lifecycle"]["cancel_verified"] = False
        result = evaluate_run(
            _run_input(freeze, observations),
            freeze,
            mode="formal",
            run_id=freeze["run_id"],
        )

        self.assertEqual(result["objects"][1]["conclusion"], "NOT_QUALIFIED")
        self.assertIn(
            "affected_lifecycle_gate_failed", result["objects"][1]["reasons"]
        )

    def test_formal_requires_exact_base_c1_c3_order(self) -> None:
        freeze = validate_freeze(_freeze())
        partial = [_observation(freeze, "base"), _observation(freeze, "c1")]
        with self.assertRaisesRegex(QualificationError, "object order"):
            evaluate_run(
                _run_input(freeze, partial),
                freeze,
                mode="formal",
                run_id=freeze["run_id"],
            )

    def test_service_runner_contract_selection_is_explicit(self) -> None:
        _validator, schema, result_schema = _freeze_contract("plan068")
        self.assertEqual(schema, PLAN068_FREEZE_SCHEMA)
        self.assertEqual(result_schema, PLAN068_SERVICE_RESULT_SCHEMA)

        validator, schema, result_schema = _freeze_contract("plan071")
        self.assertEqual(schema, FREEZE_SCHEMA)
        self.assertEqual(result_schema, SERVICE_RESULT_SCHEMA)
        self.assertEqual(validator(_freeze())["schema"], FREEZE_SCHEMA)

    def test_observation_builder_binds_raw_files_and_preserves_cancel_recheck(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            freeze = validate_freeze(_freeze())
            manifest = _write_builder_evidence(Path(temporary), freeze)
            observations = build_observations(
                freeze,
                manifest,
                manifest_sha256="b" * 64,
            )
            result = evaluate_run(
                observations,
                freeze,
                mode="formal",
                run_id=freeze["run_id"],
            )

            self.assertEqual(result["task_terminal"], "BASE_COMPARABILITY_GO")
            self.assertEqual(result["evidence_manifest_sha256"], "b" * 64)
            self.assertTrue(
                result["objects"][1]["metrics"]["lifecycle"]["value"][
                    "cancel_verified"
                ]
            )

    def test_observation_builder_rejects_offline_identity_field_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            freeze = validate_freeze(_freeze())
            manifest = _write_builder_evidence(root, freeze)
            deployment_path = Path(
                manifest["objects"]["base"]["deployment_offline"]
            )
            deployment = json.loads(deployment_path.read_text(encoding="utf-8"))
            deployment["cohort_sample_ids_sha256"] = "0" * 64
            deployment_path.write_text(json.dumps(deployment), encoding="utf-8")

            with self.assertRaisesRegex(QualificationError, "offline evidence identity"):
                build_observations(freeze, manifest, manifest_sha256="b" * 64)

    def test_service_runner_executes_plan071_with_plan071_result_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Plan068ServiceFixture(Path(temporary))
            _upgrade_service_fixture_to_plan071(fixture)
            arguments = [
                "--mode",
                "commissioning",
                "--qualification-contract",
                "plan071",
                *fixture.arguments()[2:],
            ]

            self.assertEqual(service_main(arguments), 0)

            result = json.loads(fixture.output.read_text(encoding="utf-8"))
            self.assertEqual(result["schema"], SERVICE_RESULT_SCHEMA)
            self.assertEqual(
                result["run_id"],
                "plan071-commissioning-20260824T120001Z-service-fixture",
            )
            self.assertEqual(result["status"], "COMPLETE")

    def test_service_runner_rejects_contract_schema_mismatch_before_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Plan068ServiceFixture(Path(temporary))
            _upgrade_service_fixture_to_plan071(fixture)

            self.assertEqual(service_main(fixture.arguments()), 1)

            result = json.loads(fixture.output.read_text(encoding="utf-8"))
            self.assertEqual(result["failure_code"], "freeze_identity_invalid")
            self.assertFalse((fixture.root / "service-pid").exists())

    def test_service_runner_rejects_c2_before_start(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            fixture = Plan068ServiceFixture(Path(temporary))
            _upgrade_service_fixture_to_plan071(fixture)
            freeze = json.loads(fixture.freeze.read_text(encoding="utf-8"))
            freeze["artifacts"]["c2"] = copy.deepcopy(freeze["artifacts"]["c1"])
            fixture.freeze.write_text(json.dumps(freeze), encoding="utf-8")
            descriptor = json.loads(fixture.descriptor.read_text(encoding="utf-8"))
            descriptor["object_id"] = "c2"
            descriptor["qualification_freeze_sha256"] = freeze_sha256(freeze)
            fixture.descriptor.write_text(json.dumps(descriptor), encoding="utf-8")

            arguments = [
                "--mode",
                "commissioning",
                "--qualification-contract",
                "plan071",
                *fixture.arguments()[2:],
            ]
            self.assertEqual(service_main(arguments), 1)

            result = json.loads(fixture.output.read_text(encoding="utf-8"))
            self.assertEqual(result["failure_code"], "freeze_descriptor_mismatch")
            self.assertFalse((fixture.root / "service-pid").exists())


if __name__ == "__main__":
    unittest.main()
