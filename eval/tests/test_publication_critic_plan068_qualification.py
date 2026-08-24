from __future__ import annotations

from dataclasses import dataclass
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = REPO_ROOT / "eval"
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.local_deployment.archive import (  # noqa: E402
    QualificationArchive,
    QualificationArchiveError,
)
from rondo_eval.publication_critic.local_deployment.inference import (  # noqa: E402
    InferenceResult,
)
from rondo_eval.publication_critic.local_deployment.qualification import (  # noqa: E402
    FREEZE_SCHEMA,
    OFFLINE_SCHEMA,
    OBSERVATIONS_SCHEMA,
    QualificationError,
    _offline,
    _verify_formal_source,
    evaluate_run,
    freeze_sha256,
    validate_freeze,
)
from rondo_eval.publication_critic.local_deployment.worker import (  # noqa: E402
    WorkerSession,
    read_frame,
    serve,
)
from rondo_eval.publication_critic.scoring import project_logit  # noqa: E402
from rondo_eval.publication_critic.identity import sha256_file  # noqa: E402


SAMPLE_IDS = [
    "pc-v1-cal-nc-pass",
    "pc-v1-cal-nc-rewrite",
    "pc-v1-cal-ni-pass",
    "pc-v1-cal-ni-rewrite",
]


def _freeze(
    *,
    mode: str = "formal",
    run_id: str = "plan068-formal-20260824T120000Z-four-objects",
) -> dict[str, object]:
    return {
        "schema": FREEZE_SCHEMA,
        "mode": mode,
        "run_id": run_id,
        "qualification_objects": ["base", "c1", "c2", "c3"],
        "cohort": {"sample_ids": SAMPLE_IDS, "future_unseen_test": False},
        "service_parity_input": {
            "sample_id": SAMPLE_IDS[0],
            "packet_sha256": "1" * 64,
        },
        "threshold": {
            "source": "plan054-calibration-threshold-v4",
            "projected_score": 0.5,
        },
        "reference_method": "same-original-artifact-float32",
        "source": {
            "git_commit": "a" * 40,
            "tracked_source_clean": True,
            "environment_lock_path": "eval/environments/publication-critic-plan054/uv.lock",
            "environment_lock_sha256": "b" * 64,
        },
        "artifacts": {
            object_id: {
                "candidate_artifact_sha256": character * 64,
                "deployment_artifact_sha256": character * 64,
                "service_descriptor_sha256": character.upper().lower() * 64,
            }
            for object_id, character in zip(("base", "c1", "c2", "c3"), "cdef")
        },
        "runtime": {
            "device": "cuda",
            "dtype": "bfloat16",
            "cpu_threads": 4,
            "deployment_format": "transformers-safetensors",
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
        "gates": {
            "max_raw_logit_absolute_drift": 0.25,
            "max_projected_absolute_drift": 0.02,
            "min_ranking_concordance": 1.0,
            "reference_obvious_margin_floor": 0.1,
            "min_obvious_margin_direction_agreement": 1.0,
            "min_pair_direction_agreement": 1.0,
            "max_verdict_mismatches": 0,
            "max_load_seconds": 30.0,
            "max_peak_rss_bytes": 8_000_000_000,
            "max_peak_vram_bytes": 7_500_000_000,
            "max_warm_p95_latency_ms": 1000.0,
            "max_service_score_absolute_drift": 0.001,
            "max_service_raw_logit_absolute_drift": 0.25,
            "max_service_verdict_mismatches": 0,
            "min_stress_success_rate": 1.0,
            "max_stress_p95_latency_ms": 2000.0,
        },
        "stress_call_counts": [1, 2, 4, 8],
        "representative_lifecycle_object": "c1",
    }


def _score_rows(raw_logits: list[float]) -> list[dict[str, object]]:
    return [
        {
            "sample_id": sample_id,
            "raw_logit": raw_logit,
            "projected_score": project_logit(raw_logit),
            "token_count": 300 + index,
            "dropped_oldest_publications": 0,
            "model_elapsed_ms": 20.0 + index,
        }
        for index, (sample_id, raw_logit) in enumerate(zip(SAMPLE_IDS, raw_logits))
    ]


def _success(state: str, **values: object) -> dict[str, object]:
    return {"state": state, "reason": None, "failure_scope": "none", **values}


def _unavailable(**values: object) -> dict[str, object]:
    return {
        "state": "not_reached",
        "reason": "gpu_counters_unavailable",
        "failure_scope": "infrastructure",
        **values,
    }


def _fake_backend_observation(
    object_id: str,
    digest: str,
    *,
    mode: str = "formal",
    deployed_raw: list[float] | None = None,
) -> dict[str, object]:
    reference_raw = [2.0, -2.0, 1.0, -1.0]
    artifact = _freeze()["artifacts"][object_id]
    is_representative = object_id == "c1"
    return {
        "schema": OBSERVATIONS_SCHEMA,
        "mode": mode,
        "run_id": (
            "plan068-formal-20260824T120000Z-four-objects"
            if mode == "formal"
            else "plan068-commissioning-20260824T120005Z-pair-preservation"
        ),
        "qualification_freeze_sha256": digest,
        "object_id": object_id,
        "evidence": {
            "reference_offline_sha256": "2" * 64,
            "deployment_offline_sha256": "3" * 64,
            "service_run_sha256": "4" * 64,
            "service_parity_sha256": "5" * 64,
            "service_packet_sha256": "1" * 64,
        },
        "identity": _success(
            "passed",
            service_descriptor_sha256=artifact["service_descriptor_sha256"],
        ),
        "artifact": _success(
            "passed",
            candidate_artifact_sha256=artifact["candidate_artifact_sha256"],
            deployment_artifact_sha256=artifact["deployment_artifact_sha256"],
        ),
        "load": _success("observed", seconds=2.0),
        "scores": _success(
            "observed",
            reference=_score_rows(reference_raw),
            deployment=_score_rows(deployed_raw or reference_raw),
        ),
        "resources": _success(
            "observed",
            peak_rss_bytes=4_000_000_000,
            peak_vram_bytes=4_500_000_000,
        ),
        "latency": _success("observed", warm_ms=[25.0, 26.0, 27.0, 28.0]),
        "service": _success(
            "observed",
            raw_logit_absolute_differences=[0.0, 0.0],
            score_absolute_differences=[0.0, 0.0],
            verdict_mismatch_count=0,
            bounded_call_count=2,
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
            matrix_role="representative" if is_representative else "basic",
            typed_failure_verified=is_representative,
            cancel_verified=is_representative,
            graceful_shutdown_verified=True,
            forced_cleanup_verified=is_representative,
            orphan_worker_count=0,
            body_leak_count=0,
        ),
    }


def _run_input(
    freeze: dict[str, object],
    objects: list[dict[str, object]],
    *,
    mode: str = "formal",
) -> dict[str, object]:
    return {
        "schema": OBSERVATIONS_SCHEMA,
        "mode": mode,
        "run_id": freeze["run_id"],
        "qualification_freeze_sha256": freeze_sha256(freeze),
        "objects": [{**item, "run_id": freeze["run_id"]} for item in objects],
    }


class QualificationDecisionTests(unittest.TestCase):
    def test_offline_output_binds_freeze_run_artifact_cohort_and_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            snapshot = root / "snapshot"
            snapshot.mkdir()
            (snapshot / "model.safetensors").write_bytes(b"offline-fixture")
            freeze = _freeze()
            freeze["artifacts"]["base"]["deployment_artifact_sha256"] = sha256_file(
                snapshot / "model.safetensors"
            )
            freeze_path = root / "freeze.json"
            freeze_path.write_text(json.dumps(freeze), encoding="utf-8")
            output = root / "offline.json"
            inference = mock.Mock(
                load_seconds=1.25,
                score_frozen_cohort=mock.Mock(
                    return_value=_score_rows([2.0, -2.0, 1.0, -1.0])
                ),
                resource_snapshot=mock.Mock(return_value={"peak": 123}),
            )
            with mock.patch(
                "rondo_eval.publication_critic.local_deployment.qualification.PublicationCriticInference",
                return_value=inference,
            ):
                self.assertEqual(
                    _offline(
                        SimpleNamespace(
                            freeze=freeze_path,
                            snapshot=snapshot,
                            object_id="base",
                            execution_role="reference",
                            sample_id=SAMPLE_IDS,
                            repo_root=REPO_ROOT,
                            device="cpu",
                            dtype="float32",
                            cpu_threads=4,
                            output=output,
                        )
                    ),
                    0,
                )

            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["schema"], OFFLINE_SCHEMA)
            self.assertEqual(result["run_id"], freeze["run_id"])
            self.assertEqual(
                result["qualification_freeze_sha256"], freeze_sha256(freeze)
            )
            self.assertEqual(result["execution_role"], "reference")
            self.assertEqual(
                result["snapshot_model_sha256"],
                sha256_file(snapshot / "model.safetensors"),
            )
            self.assertEqual(
                result["runtime"],
                {"device": "cpu", "dtype": "float32", "cpu_threads": 4},
            )

    def test_fake_backend_four_object_formal_run_qualifies_without_ranking(self) -> None:
        freeze = validate_freeze(_freeze())
        digest = freeze_sha256(freeze)
        observations = [
            _fake_backend_observation(object_id, digest)
            for object_id in ("base", "c1", "c2", "c3")
        ]

        result = evaluate_run(
            _run_input(freeze, observations),
            freeze,
            mode="formal",
            run_id="plan068-formal-20260824T120000Z-four-objects",
        )

        self.assertEqual(
            [item["conclusion"] for item in result["objects"]],
            ["QUALIFIED", "QUALIFIED", "QUALIFIED", "QUALIFIED"],
        )
        self.assertTrue(result["m3_c2_prerequisite_satisfied"])
        self.assertRegex(result["observations_sha256"], r"[0-9a-f]{64}")
        self.assertEqual(
            result["scope_note"],
            "qualification_only_no_candidate_ranking_or_final_threshold",
        )

    def test_valid_candidate_score_drift_is_not_qualified(self) -> None:
        run_id = "plan068-formal-20260824T120001Z-score-drift"
        freeze = validate_freeze(_freeze(run_id=run_id))
        digest = freeze_sha256(freeze)
        observations = [
            _fake_backend_observation("base", digest),
            _fake_backend_observation("c1", digest),
            _fake_backend_observation(
                "c2",
                digest,
                deployed_raw=[-2.0, 2.0, -1.0, 1.0],
            ),
            _fake_backend_observation("c3", digest),
        ]

        result = evaluate_run(
            _run_input(freeze, observations),
            freeze,
            mode="formal",
            run_id=run_id,
        )

        c2 = result["objects"][2]
        self.assertEqual(c2["conclusion"], "NOT_QUALIFIED")
        self.assertIn("projected_drift_gate_failed", c2["reasons"])
        self.assertEqual(c2["metrics"]["remaining"]["status"], "N/A")
        self.assertTrue(result["m3_c2_prerequisite_satisfied"])

    def test_pair_gate_measures_deployment_preservation_not_label_quality(self) -> None:
        run_id = "plan068-commissioning-20260824T120005Z-pair-preservation"
        freeze = validate_freeze(_freeze(mode="commissioning", run_id=run_id))
        digest = freeze_sha256(freeze)
        observation = _fake_backend_observation("c1", digest, mode="commissioning")
        reversed_but_preserved = [-2.0, 2.0, -1.0, 1.0]
        observation["scores"] = _success(
            "observed",
            reference=_score_rows(reversed_but_preserved),
            deployment=_score_rows(reversed_but_preserved),
        )

        result = evaluate_run(
            _run_input(freeze, [observation], mode="commissioning"),
            freeze,
            mode="commissioning",
            run_id=run_id,
        )

        decision = result["objects"][0]
        self.assertEqual(decision["conclusion"], "QUALIFIED")
        score_metrics = decision["metrics"]["scores"]["value"]
        self.assertEqual(score_metrics["reference_pair_direction_agreement"], 0.0)
        self.assertEqual(score_metrics["deployment_pair_direction_agreement"], 0.0)
        self.assertEqual(score_metrics["pair_direction_preservation"], 1.0)

    def test_service_raw_logit_drift_is_an_independent_gate(self) -> None:
        run_id = "plan068-commissioning-20260824T120006Z-service-raw-drift"
        freeze = validate_freeze(_freeze(mode="commissioning", run_id=run_id))
        digest = freeze_sha256(freeze)
        observation = _fake_backend_observation("c1", digest, mode="commissioning")
        observation["service"]["raw_logit_absolute_differences"] = [0.3]

        result = evaluate_run(
            _run_input(freeze, [observation], mode="commissioning"),
            freeze,
            mode="commissioning",
            run_id=run_id,
        )

        decision = result["objects"][0]
        self.assertEqual(decision["conclusion"], "NOT_QUALIFIED")
        self.assertEqual(decision["reasons"], ["service_parity_gate_failed"])
        self.assertEqual(
            decision["metrics"]["service"]["value"][
                "max_raw_logit_absolute_drift"
            ],
            0.3,
        )

    def test_infrastructure_gap_is_inconclusive_with_na_reason(self) -> None:
        run_id = "plan068-commissioning-20260824T120002Z-missing-counter"
        freeze = validate_freeze(_freeze(mode="commissioning", run_id=run_id))
        digest = freeze_sha256(freeze)
        observation = _fake_backend_observation("c1", digest, mode="commissioning")
        observation["resources"] = _unavailable(
            peak_rss_bytes=None,
            peak_vram_bytes=None,
        )

        result = evaluate_run(
            _run_input(freeze, [observation], mode="commissioning"),
            freeze,
            mode="commissioning",
            run_id=run_id,
        )

        decision = result["objects"][0]
        self.assertEqual(decision["conclusion"], "INCONCLUSIVE")
        self.assertEqual(
            decision["metrics"]["resources"],
            {"status": "N/A", "value": None, "reason": "gpu_counters_unavailable"},
        )
        self.assertFalse(result["m3_c2_prerequisite_satisfied"])

    def test_formal_run_rejects_debug_mix_or_partial_object_set(self) -> None:
        mixed_run_id = "plan068-formal-20260824T120003Z-mixed-mode"
        freeze = validate_freeze(_freeze(run_id=mixed_run_id))
        digest = freeze_sha256(freeze)
        commissioning = _fake_backend_observation("base", digest, mode="commissioning")
        with self.assertRaisesRegex(QualificationError, "mode drifted"):
            evaluate_run(
                _run_input(freeze, [commissioning]),
                freeze,
                mode="formal",
                run_id=mixed_run_id,
            )

        partial_run_id = "plan068-formal-20260824T120004Z-partial"
        freeze = validate_freeze(_freeze(run_id=partial_run_id))
        digest = freeze_sha256(freeze)
        base = _fake_backend_observation("base", digest)
        with self.assertRaisesRegex(QualificationError, "four-object order"):
            evaluate_run(
                _run_input(freeze, [base]),
                freeze,
                mode="formal",
                run_id=partial_run_id,
            )

    def test_freeze_requires_explicit_numeric_gate_and_excludes_unseen(self) -> None:
        missing_gate = _freeze()
        del missing_gate["gates"]["max_peak_vram_bytes"]
        with self.assertRaisesRegex(QualificationError, "gates fields"):
            validate_freeze(missing_gate)

        unseen = _freeze()
        unseen["cohort"]["future_unseen_test"] = True
        with self.assertRaisesRegex(QualificationError, "cohort is invalid"):
            validate_freeze(unseen)

    def test_observations_require_the_frozen_packet_and_raw_evidence_hashes(self) -> None:
        freeze = validate_freeze(_freeze())
        digest = freeze_sha256(freeze)
        observation = _fake_backend_observation("base", digest)
        observation["evidence"]["service_packet_sha256"] = "9" * 64
        with self.assertRaisesRegex(QualificationError, "evidence identity"):
            evaluate_run(
                _run_input(freeze, [observation]),
                freeze,
                mode="formal",
                run_id=freeze["run_id"],
            )

    def test_formal_source_requires_clean_exact_commit_and_environment_lock(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            lock_path = root / "eval/environments/publication-critic-plan054/uv.lock"
            lock_path.parent.mkdir(parents=True)
            lock_path.write_text("locked\n", encoding="utf-8")
            freeze = _freeze()
            freeze["source"] = {
                "git_commit": "a" * 40,
                "tracked_source_clean": True,
                "environment_lock_path": str(lock_path.relative_to(root)),
                "environment_lock_sha256": sha256_file(lock_path),
            }
            completed = [
                mock.Mock(stdout="a" * 40 + "\n"),
                mock.Mock(stdout=""),
            ]
            with mock.patch("subprocess.run", side_effect=completed):
                _verify_formal_source(root, freeze)

            dirty = [
                mock.Mock(stdout="a" * 40 + "\n"),
                mock.Mock(stdout="?? debug-output.json\n"),
            ]
            with mock.patch("subprocess.run", side_effect=dirty), self.assertRaisesRegex(
                QualificationError, "not the frozen clean commit"
            ):
                _verify_formal_source(root, freeze)


@dataclass
class _FakeInference:
    load_seconds: float = 1.25

    def score_packet(self, packet: object) -> InferenceResult:
        del packet
        return InferenceResult(
            sample_id=None,
            raw_logit=2.0,
            projected_score=project_logit(2.0),
            token_count=321,
            dropped_oldest_publications=1,
            model_elapsed_ms=12.5,
        )

    def resource_snapshot(self) -> dict[str, object]:
        return {
            "process_rss_bytes": 10,
            "process_peak_rss_bytes": 20,
            "cuda": None,
        }


class _ShortReadStream(io.BytesIO):
    def read(self, size: int = -1) -> bytes:
        return super().read(1 if size < 0 else min(size, 1))


class WorkerAndArchiveTests(unittest.TestCase):
    def test_worker_frame_reader_handles_pipe_short_reads(self) -> None:
        encoded = b'{"op":"status"}'
        stream = _ShortReadStream(struct.pack(">I", len(encoded)) + encoded)
        self.assertEqual(read_frame(stream, 1024 * 1024), {"op": "status"})

    def test_worker_framing_score_status_and_shutdown(self) -> None:
        descriptor = {
            "worker_protocol": "rondo-publication-critic-worker-v1",
            "object_id": "c1",
            "deployment_artifact_sha256": "a" * 64,
            "qualification_freeze_sha256": "b" * 64,
            "service_descriptor": {},
        }
        requests = [
            {"op": "descriptor"},
            {"op": "status"},
            {"op": "score", "request_id": "req-1", "packet": {}},
            {"op": "shutdown"},
        ]
        body = b"".join(
            struct.pack(">I", len(encoded)) + encoded
            for encoded in (
                json.dumps(request, separators=(",", ":")).encode("utf-8")
                for request in requests
            )
        )
        output = io.BytesIO()
        serve(
            WorkerSession(_FakeInference(), descriptor=descriptor),
            io.BytesIO(body),
            output,
        )
        output.seek(0)
        responses = [read_frame(output, 1024 * 1024) for _ in requests]
        self.assertEqual(responses[0], {"ok": True, "descriptor": descriptor})
        self.assertEqual(responses[1]["state"], "ready")
        self.assertEqual(
            responses[2],
            {
                "ok": True,
                "request_id": "req-1",
                "raw_logit": 2.0,
                "projected_score": project_logit(2.0),
                "token_count": 321,
                "dropped_oldest_publications": 1,
                "model_elapsed_ms": 12.5,
            },
        )
        self.assertEqual(responses[3], {"ok": True, "state": "stopped"})

    def test_worker_error_is_body_free_and_session_remains_usable(self) -> None:
        sentinel = "SECRET_PACKET_BODY_SENTINEL"
        bad = json.dumps(
            {"op": "score", "request_id": "req-1", "packet": {}, "extra": sentinel},
            separators=(",", ":"),
        ).encode("utf-8")
        shutdown = json.dumps({"op": "shutdown"}, separators=(",", ":")).encode("utf-8")
        output = io.BytesIO()
        serve(
            WorkerSession(_FakeInference(), descriptor={}),
            io.BytesIO(
                struct.pack(">I", len(bad))
                + bad
                + struct.pack(">I", len(shutdown))
                + shutdown
            ),
            output,
        )
        self.assertNotIn(sentinel.encode(), output.getvalue())
        output.seek(0)
        self.assertEqual(
            read_frame(output, 1024 * 1024),
            {
                "ok": False,
                "failure": {
                    "failure_kind": "WorkerError",
                    "message": "worker request fields are invalid",
                },
            },
        )
        self.assertEqual(
            read_frame(output, 1024 * 1024),
            {"ok": True, "state": "stopped"},
        )

    def test_archive_is_mode_bound_private_and_write_once(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "runs"
            archive = QualificationArchive(
                root,
                "plan068-formal-20260824T120005Z-archive",
                "formal",
            ).create()
            output = archive.write_json("qualification-result.json", {"ok": True})
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            self.assertEqual(archive.path.stat().st_mode & 0o777, 0o700)
            with self.assertRaisesRegex(QualificationArchiveError, "without overwrite"):
                archive.write_json("qualification-result.json", {"ok": False})
            with self.assertRaisesRegex(QualificationArchiveError, "identity is invalid"):
                QualificationArchive(
                    root,
                    "plan068-commissioning-20260824T120006Z-wrong-mode",
                    "formal",
                )


if __name__ == "__main__":
    unittest.main()
