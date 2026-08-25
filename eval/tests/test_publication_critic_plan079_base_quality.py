from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = REPO_ROOT / "eval"
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.full_model_training.contract import (  # noqa: E402
    canonical_json_bytes,
    sha256_bytes,
    sha256_file,
)
from rondo_eval.publication_critic.selection.release import (  # noqa: E402
    SCHEMA as RELEASE_SCHEMA,
    release_sha256,
    validate_release,
)
from rondo_eval.publication_critic.base_quality.archive import (  # noqa: E402
    BaseQualityArchive,
)
from rondo_eval.publication_critic.base_quality.backend import (  # noqa: E402
    Plan079CloudBackend,
)
from rondo_eval.publication_critic.base_quality.contract import (  # noqa: E402
    BaseQualityError,
    MODEL_REPOSITORY,
    MODEL_REVISION,
    QUALITY_FLOORS,
    RUN_SPEC_SCHEMA,
    RUNTIME_CONTRACT,
)
from rondo_eval.publication_critic.base_quality.runner import (  # noqa: E402
    build_scores_document,
    prepare_validation_release,
    recompute_result,
    run_evaluation,
    validate_result,
)
from rondo_eval.publication_critic.base_quality.snapshot import (  # noqa: E402
    MODEL_LOCK_SCHEMA,
    verify_snapshot,
)


BUNDLE_ROOT = (
    Path("/home/sjc/desktop/RONDO/eval-data/publication-critic/plan068/handoff")
    / "bundle-plan066-final-01"
)
FILES = (
    ".gitattributes",
    "README.md",
    "added_tokens.json",
    "assets/skywork_logo.png",
    "chat_template.jinja",
    "config.json",
    "merges.txt",
    "model-00001-of-00002.safetensors",
    "model-00002-of-00002.safetensors",
    "model.safetensors.index.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
)


def _packet(name: str) -> dict[str, object]:
    return {
        "qualification": {"packet_schema": "v1", "rubric": "v1"},
        "actor_role": "member",
        "target_kind": "new_event",
        "local_scope": {"title": name},
        "continuity": {"state": "not_applicable"},
        "evidence_v1": {"state": "not_applicable"},
        "candidate": {"summary": f"summary {name}", "handoff": f"handoff {name}"},
    }


def _release() -> dict[str, object]:
    identifiers = [f"v079-{index:02d}" for index in range(55)]
    labels = ["PASS"] * 34 + ["REWRITE"] * 21
    pairs = [
        (
            f"boundary-{index:02d}",
            "boundary",
            identifiers[index],
            identifiers[34 + index],
        )
        for index in range(19)
    ] + [
        (
            f"within-{index:02d}",
            "within_pass",
            identifiers[index],
            identifiers[7 + index],
        )
        for index in range(7)
    ]
    pairs.sort(key=lambda row: row[0])
    return validate_release(
        {
            "schema": RELEASE_SCHEMA,
            "split": "validation",
            "dataset_revision": "v8",
            "dataset_manifest_sha256": "7" * 64,
            "authorization": {
                "kind": "frozen_protocol_split",
                "selection_lock_sha256": None,
            },
            "items": [
                {
                    "candidate_id": candidate_id,
                    "packet": _packet(candidate_id),
                    "dropped_oldest_publications": 0,
                }
                for candidate_id in identifiers
            ],
            "supervision": [
                {
                    "candidate_id": candidate_id,
                    "binary_label": label,
                    "publication_class": "event",
                    "completion_state": "complete",
                    "actor_role": "member",
                    "hard_focus": "none",
                    "length_bucket": "short",
                    "style": "plain",
                    "unicode": False,
                    "scenario_id": f"scenario-{index:02d}",
                    "scenario_group": "synthetic",
                    "slices": ["synthetic"],
                }
                for index, (candidate_id, label) in enumerate(zip(identifiers, labels))
            ],
            "pairs": [
                {
                    "pair_id": pair_id,
                    "kind": kind,
                    "preferred_candidate_id": preferred,
                    "dispreferred_candidate_id": dispreferred,
                    "target_dimension": "quality",
                }
                for pair_id, kind, preferred, dispreferred in pairs
            ],
        }
    )


def _snapshot(root: Path) -> tuple[Path, Path, dict[str, object]]:
    root.mkdir(parents=True, exist_ok=True)
    snapshot = root / "snapshot"
    snapshot.mkdir()
    config = {
        "architectures": ["Qwen3ForSequenceClassification"],
        "model_type": "qwen3",
        "pad_token_id": 151654,
        "eos_token_id": 151645,
        "max_position_embeddings": 40960,
        "torch_dtype": "bfloat16",
        "id2label": {"0": "LABEL_0"},
    }
    weight_map = {
        f"tensor.{index:03d}": (
            "model-00001-of-00002.safetensors"
            if index < 200
            else "model-00002-of-00002.safetensors"
        )
        for index in range(399)
    }
    bodies: dict[str, bytes] = {name: f"fixture:{name}\n".encode() for name in FILES}
    bodies["config.json"] = json.dumps(config, sort_keys=True).encode()
    bodies["model.safetensors.index.json"] = json.dumps(
        {"metadata": {"total_size": 8_044_941_312}, "weight_map": weight_map},
        sort_keys=True,
    ).encode()
    for name, body in bodies.items():
        path = snapshot / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    files = {
        name: {"bytes": len(body), "sha256": sha256_bytes(body)}
        for name, body in bodies.items()
    }
    lock = {
        "schema": MODEL_LOCK_SCHEMA,
        "repository": MODEL_REPOSITORY,
        "revision": MODEL_REVISION,
        "license": "apache-2.0",
        "library_name": "transformers",
        "pipeline_tag": "text-classification",
        "parameters": {"count": 4_022_470_656, "dtype": "BF16"},
        "expected_config": {
            "architecture": "Qwen3ForSequenceClassification",
            "model_type": "qwen3",
            "num_labels": 1,
            "pad_token_id": 151654,
            "eos_token_id": 151645,
            "max_position_embeddings": 40960,
            "torch_dtype": "bfloat16",
        },
        "weight_index": {
            "filename": "model.safetensors.index.json",
            "total_size": 8_044_941_312,
            "tensor_count": 399,
            "shards": [
                "model-00001-of-00002.safetensors",
                "model-00002-of-00002.safetensors",
            ],
        },
        "files": files,
    }
    lock_path = root / "model-lock.json"
    lock_path.write_text(json.dumps(lock), encoding="utf-8")
    return snapshot, lock_path, verify_snapshot(snapshot, lock_path)


def _spec(
    release: dict[str, object],
    receipt: dict[str, object],
    lock_path: Path,
    *,
    mode: str = "formal",
    suffix: str = "unit",
) -> dict[str, object]:
    return {
        "schema": RUN_SPEC_SCHEMA,
        "mode": mode,
        "run_id": f"plan079-{mode}-20260825T120000Z-{suffix}",
        "source": {
            "git_commit": "1" * 40,
            "tracked_source_clean": mode == "formal",
            "source_archive_sha256": "2" * 64,
            "environment_lock_path": "eval/environments/publication-critic-plan068/uv.lock",
            "environment_lock_sha256": "3" * 64,
        },
        "model": {
            "repository": MODEL_REPOSITORY,
            "revision": MODEL_REVISION,
            "model_lock_sha256": sha256_file(lock_path),
            "snapshot_receipt_sha256": sha256_bytes(canonical_json_bytes(receipt)),
            "snapshot_content_sha256": receipt["snapshot_content_sha256"],
        },
        "input": {
            "dataset_revision": "v8",
            "bundle_manifest_sha256": "4" * 64,
            "release_sha256": release_sha256(release),
            "candidate_count": 55,
            "boundary_pair_count": 19,
            "within_pass_pair_count": 7,
            "unseen_test_rows_available": 0,
        },
        "runtime": {**RUNTIME_CONTRACT, "cpu_threads": 4},
        "cloud": {
            "pod_id": "pod-unit",
            "network_volume_id": "volume-unit",
            "data_center_id": "US-IL-1",
            "gpu_model": "NVIDIA GeForce RTX 4090",
            "container_image": "runpod/pytorch:test",
            "cuda_host_version": "13.0",
        },
        "quality_floors": dict(QUALITY_FLOORS),
    }


def _rows(release: dict[str, object], *, good: bool) -> list[dict[str, object]]:
    labels = {
        row["candidate_id"]: row["binary_label"] for row in release["supervision"]
    }
    return [
        {
            "candidate_id": item["candidate_id"],
            "raw_logit": 2.0
            if good and labels[item["candidate_id"]] == "PASS"
            else -2.0
            if good
            else 0.0,
            "score": 0.9
            if good and labels[item["candidate_id"]] == "PASS"
            else 0.1
            if good
            else 0.5,
            "token_count": 100,
            "dropped_oldest_publications": 0,
            "model_elapsed_ms": 10.0,
        }
        for item in release["items"]
    ]


def _runtime() -> dict[str, object]:
    return {
        "load_seconds": 1.0,
        "warm_p95_latency_ms": 10.0,
        "wall_seconds": 2.0,
        "peak_rss_bytes": 100,
        "peak_vram_allocated_bytes": 200,
        "peak_vram_reserved_bytes": 300,
        "scored_count": 55,
        "typed_failure_count": 0,
        "torch_version": "2.8.0",
        "transformers_version": "4.52.3",
        "cuda_runtime_version": "12.8",
        "gpu_name": "NVIDIA GeForce RTX 4090",
        "gpu_capability": "8.9",
    }


class SnapshotContractTest(unittest.TestCase):
    def test_two_shard_snapshot_and_index_are_bound(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot, lock, receipt = _snapshot(Path(directory))
            self.assertEqual(receipt["weight_index"]["tensor_count"], 399)
            (snapshot / "model-00002-of-00002.safetensors").unlink()
            with self.assertRaises(BaseQualityError):
                verify_snapshot(snapshot, lock)

    def test_cloud_backend_requires_explicit_plan079_process_marker(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            snapshot, lock, _ = _snapshot(Path(directory))
            backend = Plan079CloudBackend(
                snapshot,
                model_lock_path=lock,
                device="cuda",
                dtype="bfloat16",
            )
            with mock.patch.dict("os.environ", {}, clear=True):
                with self.assertRaisesRegex(RuntimeError, "cloud run marker"):
                    backend.load()

    def test_hash_drift_and_third_shard_reference_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            snapshot, lock, _ = _snapshot(root)
            (snapshot / "config.json").write_bytes(b"drift")
            with self.assertRaises(BaseQualityError):
                verify_snapshot(snapshot, lock)
            snapshot, lock, _ = _snapshot(root / "second")
            index = json.loads((snapshot / "model.safetensors.index.json").read_text())
            index["weight_map"]["tensor.000"] = "third.safetensors"
            body = json.dumps(index, sort_keys=True).encode()
            (snapshot / "model.safetensors.index.json").write_bytes(body)
            lock_data = json.loads(lock.read_text())
            lock_data["files"]["model.safetensors.index.json"] = {
                "bytes": len(body),
                "sha256": sha256_bytes(body),
            }
            lock.write_text(json.dumps(lock_data), encoding="utf-8")
            with self.assertRaises(BaseQualityError):
                verify_snapshot(snapshot, lock)


class ResultContractTest(unittest.TestCase):
    def test_complete_good_and_bad_quality_get_distinct_terminals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, lock, receipt = _snapshot(Path(directory))
            release = _release()
            spec = _spec(release, receipt, lock)
            good_scores = build_scores_document(
                spec, release, _rows(release, good=True), []
            )
            good = recompute_result(spec, release, good_scores, _runtime())
            self.assertEqual(good["terminal"], "4B_BASE_QUALITY_GO")
            self.assertTrue(good["threshold_search"]["feasible"])
            bad_scores = build_scores_document(
                spec, release, _rows(release, good=False), []
            )
            bad = recompute_result(spec, release, bad_scores, _runtime())
            self.assertEqual(bad["terminal"], "4B_BASE_QUALITY_NO_GO")
            self.assertIn("roc_auc_floor_failed", bad["gate_failures"])

    def test_incomplete_or_tampered_evidence_is_inconclusive_or_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, lock, receipt = _snapshot(Path(directory))
            release = _release()
            spec = _spec(release, receipt, lock)
            scores = build_scores_document(
                spec,
                release,
                _rows(release, good=True)[:-1],
                [
                    {
                        "candidate_id": "v079-54",
                        "failure_kind": "BackendError",
                        "failure_code": "runtime",
                    }
                ],
            )
            runtime = _runtime()
            runtime["scored_count"] = 54
            runtime["typed_failure_count"] = 1
            result = recompute_result(spec, release, scores, runtime)
            self.assertEqual(result["terminal"], "INCONCLUSIVE")
            tampered = copy.deepcopy(result)
            tampered["terminal"] = "4B_BASE_QUALITY_GO"
            with self.assertRaises(BaseQualityError):
                validate_result(tampered, spec, release, scores, runtime)


class ArchiveAndRunTest(unittest.TestCase):
    def test_formal_namespace_is_empty_and_commissioning_can_resume(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = _release()
            snapshot, lock, receipt = _snapshot(root)
            formal = _spec(release, receipt, lock, suffix="formal")
            runs = root / "runs"
            BaseQualityArchive(runs, formal["run_id"], "formal").create()
            with self.assertRaises(BaseQualityError):
                BaseQualityArchive(runs, formal["run_id"], "formal").create()

            commissioning = _spec(
                release, receipt, lock, mode="commissioning", suffix="resume"
            )
            source_archive = root / "source.tar"
            environment_lock = root / "uv.lock"
            source_archive.write_bytes(b"source")
            environment_lock.write_bytes(b"environment")
            commissioning["source"]["source_archive_sha256"] = sha256_file(
                source_archive
            )
            commissioning["source"]["environment_lock_sha256"] = sha256_file(
                environment_lock
            )
            calls = {"count": 0}
            fail_after = {"value": 10}

            class FakeInference:
                def __init__(self, *args: object, **kwargs: object) -> None:
                    del args, kwargs
                    self.load_seconds = 0.1
                    self.backend = SimpleNamespace(
                        cloud_runtime_snapshot=lambda: {
                            "torch_version": "2.8.0",
                            "transformers_version": "4.52.3",
                            "cuda_runtime_version": "12.8",
                            "gpu_name": "NVIDIA GeForce RTX 4090",
                            "gpu_capability": "8.9",
                        }
                    )

                def load(self) -> None:
                    return None

                def score_packet(self, packet: object, *, sample_id: str) -> object:
                    del packet
                    calls["count"] += 1
                    if (
                        fail_after["value"] is not None
                        and calls["count"] > fail_after["value"]
                    ):
                        raise RuntimeError("fixture interruption")
                    return SimpleNamespace(
                        raw_logit=2.0,
                        projected_score=0.9,
                        token_count=100,
                        dropped_oldest_publications=0,
                        model_elapsed_ms=1.0,
                        sample_id=sample_id,
                    )

                def resource_snapshot(self) -> dict[str, object]:
                    return {
                        "process_peak_rss_bytes": 100,
                        "cuda": {"max_allocated_bytes": 200, "max_reserved_bytes": 300},
                    }

            bundle_receipt = {
                "bundle_manifest_sha256": commissioning["input"][
                    "bundle_manifest_sha256"
                ]
            }
            with mock.patch(
                "rondo_eval.publication_critic.base_quality.runner.verify_plan066_bundle",
                return_value=bundle_receipt,
            ):
                with self.assertRaisesRegex(
                    BaseQualityError, "commissioning_incomplete"
                ):
                    run_evaluation(
                        spec_value=commissioning,
                        release_value=release,
                        snapshot=snapshot,
                        model_lock_path=lock,
                        source_archive=source_archive,
                        environment_lock=environment_lock,
                        bundle_root=root,
                        runs_root=runs,
                        repo_root=REPO_ROOT,
                        attempt_id="resume-one",
                        inference_factory=FakeInference,
                    )
                fail_after["value"] = None
                _, runtime, _ = run_evaluation(
                    spec_value=commissioning,
                    release_value=release,
                    snapshot=snapshot,
                    model_lock_path=lock,
                    source_archive=source_archive,
                    environment_lock=environment_lock,
                    bundle_root=root,
                    runs_root=runs,
                    repo_root=REPO_ROOT,
                    attempt_id="resume-two",
                    inference_factory=FakeInference,
                )
            self.assertEqual(runtime["scored_count"], 55)
            self.assertEqual(calls["count"], 56)


@unittest.skipUnless(
    BUNDLE_ROOT.is_dir(), "local physically unseen-free Plan 066 bundle absent"
)
class RealBundleIntegrationTest(unittest.TestCase):
    def test_plan079_reuses_exact_validation_release(self) -> None:
        release, bundle = prepare_validation_release(BUNDLE_ROOT, REPO_ROOT)
        self.assertEqual(len(release["items"]), 55)
        self.assertEqual(sum(row["kind"] == "boundary" for row in release["pairs"]), 19)
        self.assertEqual(
            sum(row["kind"] == "within_pass" for row in release["pairs"]), 7
        )
        self.assertEqual(bundle["unseen_test_rows"], 0)


if __name__ == "__main__":
    unittest.main()
