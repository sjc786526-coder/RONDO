from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from types import SimpleNamespace
import sys
import tarfile
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
    build_commissioning_binding,
    build_scores_document,
    prepare_validation_release,
    recompute_result,
    run_evaluation,
    validate_formal_commissioning,
    validate_result,
)
from rondo_eval.publication_critic.base_quality.__main__ import (  # noqa: E402
    command_freeze,
)
from rondo_eval.publication_critic.base_quality.snapshot import (  # noqa: E402
    MODEL_LOCK_SCHEMA,
    verify_snapshot,
)
from rondo_eval.publication_critic.base_quality.source import (  # noqa: E402
    verify_source_archive_tree,
)
from rondo_eval.publication_critic.base_quality.runtime import (  # noqa: E402
    PACKAGE_VERSIONS,
    RUNTIME_RECEIPT_SCHEMA,
    runtime_receipt_sha256,
    validate_runtime_receipt,
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


def _source_archive(root: Path) -> tuple[Path, Path]:
    source_root = root / "source-root"
    source_file = source_root / "eval" / "source-marker.txt"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("plan079 source\n", encoding="utf-8")
    archive = root / "source.tar"
    with tarfile.open(archive, mode="w") as handle:
        handle.add(source_file, arcname="eval/source-marker.txt")
    return archive, source_root


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
            "tracked_source_clean": True,
            "source_archive_sha256": "2" * 64,
            "environment_lock_path": "eval/environments/publication-critic-plan068/uv.lock",
            "environment_lock_sha256": "3" * 64,
            "runtime_receipt_sha256": "5" * 64,
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
        "commissioning": (
            None
            if mode == "commissioning"
            else {
                "run_id": "plan079-commissioning-20260825T110000Z-unit",
                "run_spec_sha256": "a" * 64,
                "scores_sha256": "b" * 64,
                "runtime_sha256": "c" * 64,
                "result_sha256": "d" * 64,
            }
        ),
        "quality_floors": dict(QUALITY_FLOORS),
    }


def _rows(release: dict[str, object], *, good: bool) -> list[dict[str, object]]:
    labels = {
        row["candidate_id"]: row["binary_label"] for row in release["supervision"]
    }
    return [
        {
            "candidate_id": item["candidate_id"],
            "raw_logit": math.log(9.0)
            if good and labels[item["candidate_id"]] == "PASS"
            else -math.log(9.0)
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


def _runtime_receipt(root: Path) -> tuple[Path, Path, dict[str, object]]:
    dependency_freeze = root / "dependency-freeze.txt"
    dependency_freeze.write_text("fixture==1\n", encoding="utf-8")
    receipt: dict[str, object] = {
        "schema": RUNTIME_RECEIPT_SCHEMA,
        "image_id": "runpod/pytorch:test",
        "dependency_freeze_sha256": sha256_file(dependency_freeze),
        "environment_lock_sha256": "3" * 64,
        "python_version": "3.12.0",
        "packages": dict(PACKAGE_VERSIONS),
        "torch_cuda_runtime_version": "12.8",
        "cuda_host_version": "13.0",
        "gpu_name": "NVIDIA GeForce RTX 4090",
        "gpu_capability": "8.9",
        "driver_version": "580.0",
    }
    path = root / "runtime-receipt.json"
    path.write_text(json.dumps(receipt), encoding="utf-8")
    return path, dependency_freeze, receipt


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


class RuntimeReceiptContractTest(unittest.TestCase):
    def test_runtime_receipt_binds_image_lock_freeze_and_packages(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, _, receipt = _runtime_receipt(Path(directory))
            self.assertEqual(validate_runtime_receipt(receipt), receipt)
            drifted = copy.deepcopy(receipt)
            drifted["packages"]["transformers"] = "4.53.0"
            with self.assertRaisesRegex(BaseQualityError, "packages_invalid"):
                validate_runtime_receipt(drifted)

    def test_bootstrap_disables_unavailable_image_hf_transfer_toggle(self) -> None:
        script = (
            REPO_ROOT / "training/publication-critic-plan079/runpod-bootstrap.sh"
        ).read_text(encoding="utf-8")
        disable = script.index("export HF_HUB_ENABLE_HF_TRANSFER=0")
        download = script.index('"$venv/bin/hf" download')
        self.assertLess(disable, download)


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

    def test_commissioning_never_emits_a_formal_quality_terminal(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, lock, receipt = _snapshot(Path(directory))
            release = _release()
            spec = _spec(release, receipt, lock, mode="commissioning")
            scores = build_scores_document(spec, release, _rows(release, good=True), [])
            result = recompute_result(spec, release, scores, _runtime())
            self.assertEqual(result["terminal"], "COMMISSIONING_COMPLETE")
            self.assertNotIn(
                result["terminal"],
                {"4B_BASE_QUALITY_GO", "4B_BASE_QUALITY_NO_GO"},
            )

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

    def test_score_projection_is_recomputed_from_raw_logit(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, lock, receipt = _snapshot(Path(directory))
            release = _release()
            spec = _spec(release, receipt, lock)
            rows = _rows(release, good=True)
            rows[0]["score"] = 0.8
            with self.assertRaisesRegex(BaseQualityError, "projection_mismatch"):
                build_scores_document(spec, release, rows, [])


class ArchiveAndRunTest(unittest.TestCase):
    def test_formal_requires_matching_completed_commissioning(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            _, lock, receipt = _snapshot(Path(directory))
            release = _release()
            commissioning = _spec(
                release, receipt, lock, mode="commissioning", suffix="qualified"
            )
            scores = build_scores_document(
                commissioning, release, _rows(release, good=True), []
            )
            runtime = _runtime()
            result = recompute_result(commissioning, release, scores, runtime)
            binding = build_commissioning_binding(
                commissioning, release, scores, runtime, result
            )
            formal = _spec(release, receipt, lock, mode="formal", suffix="qualified")
            formal["commissioning"] = binding
            self.assertEqual(
                validate_formal_commissioning(
                    formal,
                    release,
                    commissioning,
                    release,
                    scores,
                    runtime,
                    result,
                ),
                binding,
            )
            drifted = copy.deepcopy(formal)
            drifted["source"]["source_archive_sha256"] = "e" * 64
            with self.assertRaisesRegex(BaseQualityError, "source_mismatch"):
                validate_formal_commissioning(
                    drifted,
                    release,
                    commissioning,
                    release,
                    scores,
                    runtime,
                    result,
                )

    def test_source_archive_must_match_the_executing_tree(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            archive, source_root = _source_archive(root)
            receipt = verify_source_archive_tree(archive, source_root, exact_tree=True)
            self.assertEqual(receipt["file_count"], 1)
            (source_root / "eval" / "source-marker.txt").write_text(
                "old source\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(BaseQualityError, "source_tree_identity"):
                verify_source_archive_tree(archive, source_root, exact_tree=True)

    def test_freeze_and_run_rebuild_release_from_the_frozen_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = _release()
            tampered = copy.deepcopy(release)
            tampered["supervision"][0]["binary_label"] = "REWRITE"
            tampered = validate_release(tampered)
            release_path = root / "release.json"
            release_path.write_text(json.dumps(tampered), encoding="utf-8")
            args = SimpleNamespace(
                release=release_path,
                bundle=root / "bundle",
                repo_root=REPO_ROOT,
            )
            with mock.patch(
                "rondo_eval.publication_critic.base_quality.__main__.prepare_validation_release",
                return_value=(release, {"bundle_manifest_sha256": "4" * 64}),
            ):
                with self.assertRaisesRegex(
                    BaseQualityError, "validation_release_bundle_mismatch"
                ):
                    command_freeze(args)

            snapshot, lock, receipt = _snapshot(root / "model")
            archive, source_root = _source_archive(root)
            environment_lock = root / "uv.lock"
            environment_lock.write_bytes(b"environment")
            runtime_receipt_path = root / "missing-runtime-receipt.json"
            dependency_freeze = root / "missing-dependency-freeze.txt"
            spec = _spec(tampered, receipt, lock, mode="formal", suffix="release")
            spec["source"]["source_archive_sha256"] = sha256_file(archive)
            spec["source"]["environment_lock_sha256"] = sha256_file(environment_lock)
            with mock.patch(
                "rondo_eval.publication_critic.base_quality.runner.prepare_validation_release",
                return_value=(release, {"bundle_manifest_sha256": "4" * 64}),
            ):
                with self.assertRaisesRegex(
                    BaseQualityError, "validation_release_bundle_mismatch"
                ):
                    run_evaluation(
                        spec_value=spec,
                        release_value=tampered,
                        snapshot=snapshot,
                        model_lock_path=lock,
                        source_archive=archive,
                        environment_lock=environment_lock,
                        runtime_receipt_path=runtime_receipt_path,
                        dependency_freeze=dependency_freeze,
                        image_id="runpod/pytorch:test",
                        bundle_root=root / "bundle",
                        runs_root=root / "runs",
                        repo_root=source_root,
                        attempt_id="release-mismatch",
                    )

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
            source_archive, source_root = _source_archive(root)
            environment_lock = root / "uv.lock"
            environment_lock.write_bytes(b"environment")
            runtime_receipt_path, dependency_freeze, runtime_receipt = _runtime_receipt(
                root
            )
            commissioning["source"]["source_archive_sha256"] = sha256_file(
                source_archive
            )
            commissioning["source"]["environment_lock_sha256"] = sha256_file(
                environment_lock
            )
            runtime_receipt["environment_lock_sha256"] = sha256_file(environment_lock)
            runtime_receipt_path.write_text(
                json.dumps(runtime_receipt), encoding="utf-8"
            )
            commissioning["source"]["runtime_receipt_sha256"] = runtime_receipt_sha256(
                runtime_receipt
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
                        raw_logit=math.log(9.0),
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
            with (
                mock.patch(
                    "rondo_eval.publication_critic.base_quality.runner.prepare_validation_release",
                    return_value=(release, bundle_receipt),
                ),
                mock.patch(
                    "rondo_eval.publication_critic.base_quality.runner.verify_runtime_environment",
                    return_value=runtime_receipt,
                ),
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
                        runtime_receipt_path=runtime_receipt_path,
                        dependency_freeze=dependency_freeze,
                        image_id="runpod/pytorch:test",
                        bundle_root=root,
                        runs_root=runs,
                        repo_root=source_root,
                        attempt_id="resume-one",
                        inference_factory=FakeInference,
                    )
                fail_after["value"] = None
                scores, runtime, result = run_evaluation(
                    spec_value=commissioning,
                    release_value=release,
                    snapshot=snapshot,
                    model_lock_path=lock,
                    source_archive=source_archive,
                    environment_lock=environment_lock,
                    runtime_receipt_path=runtime_receipt_path,
                    dependency_freeze=dependency_freeze,
                    image_id="runpod/pytorch:test",
                    bundle_root=root,
                    runs_root=runs,
                    repo_root=source_root,
                    attempt_id="resume-two",
                    inference_factory=FakeInference,
                )
            self.assertEqual(runtime["scored_count"], 55)
            self.assertEqual(calls["count"], 56)
            run_root = runs / commissioning["run_id"]
            expected_runtime = (run_root / "runtime.json").read_bytes()
            (run_root / "runtime.json").unlink()

            class UnexpectedInference:
                def __init__(self, *args: object, **kwargs: object) -> None:
                    del args, kwargs
                    raise AssertionError("completed commissioning must recover")

            with (
                mock.patch(
                    "rondo_eval.publication_critic.base_quality.runner.prepare_validation_release",
                    return_value=(release, bundle_receipt),
                ),
                mock.patch(
                    "rondo_eval.publication_critic.base_quality.runner.verify_runtime_environment",
                    return_value=runtime_receipt,
                ),
            ):
                recovered = run_evaluation(
                    spec_value=commissioning,
                    release_value=release,
                    snapshot=snapshot,
                    model_lock_path=lock,
                    source_archive=source_archive,
                    environment_lock=environment_lock,
                    runtime_receipt_path=runtime_receipt_path,
                    dependency_freeze=dependency_freeze,
                    image_id="runpod/pytorch:test",
                    bundle_root=root,
                    runs_root=runs,
                    repo_root=source_root,
                    attempt_id="resume-three",
                    inference_factory=UnexpectedInference,
                )
            self.assertEqual(recovered, (scores, runtime, result))
            self.assertEqual((run_root / "runtime.json").read_bytes(), expected_runtime)

    def test_first_complete_formal_result_blocks_a_second_formal_run(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            runs = Path(directory) / "formal-runs"
            first = BaseQualityArchive(
                runs,
                "plan079-formal-20260825T120000Z-first",
                "formal",
            )
            first.require_formal_unclaimed()
            first.create()
            result = {
                "terminal": "4B_BASE_QUALITY_NO_GO",
                "valid_full_quality_run": True,
            }
            marker = first.claim_formal_result(result)
            self.assertEqual(first.claim_formal_result(result), marker)
            second = BaseQualityArchive(
                runs,
                "plan079-formal-20260825T130000Z-second",
                "formal",
            )
            with self.assertRaisesRegex(
                BaseQualityError, "formal_result_already_authoritative"
            ):
                second.require_formal_unclaimed()
            first.path.rmdir()
            with self.assertRaisesRegex(
                BaseQualityError, "formal_result_reconciliation_required"
            ):
                first.require_formal_unclaimed()

    def test_completed_formal_recovery_claims_authority(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            release = _release()
            snapshot, lock, receipt = _snapshot(root / "model")
            source_archive, source_root = _source_archive(root)
            environment_lock = root / "uv.lock"
            environment_lock.write_bytes(b"environment")
            runtime_receipt_path, dependency_freeze, runtime_receipt = _runtime_receipt(
                root
            )
            runtime_receipt["environment_lock_sha256"] = sha256_file(environment_lock)
            runtime_receipt_path.write_text(
                json.dumps(runtime_receipt), encoding="utf-8"
            )

            commissioning = _spec(
                release, receipt, lock, mode="commissioning", suffix="authority"
            )
            commissioning["source"]["source_archive_sha256"] = sha256_file(
                source_archive
            )
            commissioning["source"]["environment_lock_sha256"] = sha256_file(
                environment_lock
            )
            commissioning["source"]["runtime_receipt_sha256"] = runtime_receipt_sha256(
                runtime_receipt
            )
            commissioning_scores = build_scores_document(
                commissioning, release, _rows(release, good=True), []
            )
            commissioning_runtime = _runtime()
            commissioning_result = recompute_result(
                commissioning,
                release,
                commissioning_scores,
                commissioning_runtime,
            )
            binding = build_commissioning_binding(
                commissioning,
                release,
                commissioning_scores,
                commissioning_runtime,
                commissioning_result,
            )

            formal = _spec(release, receipt, lock, suffix="authority")
            formal["source"] = copy.deepcopy(commissioning["source"])
            formal["commissioning"] = binding
            scores = build_scores_document(
                formal, release, _rows(release, good=True), []
            )
            runtime = _runtime()
            result = recompute_result(formal, release, scores, runtime)
            runs = root / "runs"
            archive = BaseQualityArchive(runs, formal["run_id"], "formal").create()
            archive.bind_json("run-spec.json", formal)
            archive.bind_json("validation-release.json", release)
            archive.bind_json(
                "final-evidence.json",
                {
                    "schema": "rondo-publication-critic-plan079-final-evidence-v1",
                    "scores": scores,
                    "runtime": runtime,
                    "result": result,
                },
            )
            second = BaseQualityArchive(
                runs,
                "plan079-formal-20260825T130000Z-other",
                "formal",
            )
            with self.assertRaisesRegex(
                BaseQualityError, "formal_result_reconciliation_required"
            ):
                second.require_formal_unclaimed()

            commissioning_evidence = (
                commissioning,
                release,
                commissioning_scores,
                commissioning_runtime,
                commissioning_result,
            )
            bundle_receipt = {
                "bundle_manifest_sha256": formal["input"]["bundle_manifest_sha256"]
            }
            with (
                mock.patch(
                    "rondo_eval.publication_critic.base_quality.runner.prepare_validation_release",
                    return_value=(release, bundle_receipt),
                ),
                mock.patch(
                    "rondo_eval.publication_critic.base_quality.runner.verify_runtime_environment",
                    return_value=runtime_receipt,
                ),
            ):
                recovered = run_evaluation(
                    spec_value=formal,
                    release_value=release,
                    snapshot=snapshot,
                    model_lock_path=lock,
                    source_archive=source_archive,
                    environment_lock=environment_lock,
                    runtime_receipt_path=runtime_receipt_path,
                    dependency_freeze=dependency_freeze,
                    image_id="runpod/pytorch:test",
                    bundle_root=root,
                    runs_root=runs,
                    repo_root=source_root,
                    attempt_id="authority-recovery",
                    commissioning_evidence=commissioning_evidence,
                )
                recovered_again = run_evaluation(
                    spec_value=formal,
                    release_value=release,
                    snapshot=snapshot,
                    model_lock_path=lock,
                    source_archive=source_archive,
                    environment_lock=environment_lock,
                    runtime_receipt_path=runtime_receipt_path,
                    dependency_freeze=dependency_freeze,
                    image_id="runpod/pytorch:test",
                    bundle_root=root,
                    runs_root=runs,
                    repo_root=source_root,
                    attempt_id="authority-recovery-again",
                    commissioning_evidence=commissioning_evidence,
                )
            self.assertEqual(recovered, (scores, runtime, result))
            self.assertEqual(recovered_again, recovered)
            self.assertTrue((runs / "formal-authority.json").is_file())


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
