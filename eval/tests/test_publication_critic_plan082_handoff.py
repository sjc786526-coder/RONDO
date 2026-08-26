from __future__ import annotations

import hashlib
import json
from pathlib import Path
import stat
import sys
import tempfile
import unittest
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.full_model_training.contract import (  # noqa: E402
    FullModelTrainingError,
    canonical_json_bytes,
    pretty_json_bytes,
)
from rondo_eval.publication_critic.full_model_training.plan081_artifacts import (  # noqa: E402
    Plan081ArtifactStore,
)
from rondo_eval.publication_critic.full_model_training.plan081_observation import (  # noqa: E402
    OBSERVATION_SCHEMA,
)
from rondo_eval.publication_critic.full_model_training.plan082_formal import (  # noqa: E402
    RESULT_SCHEMA,
)
from rondo_eval.publication_critic.full_model_training.plan082_handoff import (  # noqa: E402
    BOOTSTRAP_SCHEMA,
    HANDOFF_SCHEMA,
    HandoffError,
    Plan082Handoff,
    bootstrap_manifest_specs,
    create_bootstrap_manifest,
    create_handoff_binding,
    create_handoff_client,
    create_retained_bootstrap_manifest,
    download,
    inventory,
    local_handoff_preflight,
    load_handoff,
    validate_handoff,
)
from rondo_eval.publication_critic.local_deployment.handoff import (  # noqa: E402
    ScopedHandoffClient,
)
from rondo_eval.config import RepoPaths  # noqa: E402


class _Body:
    def __init__(self, value: bytes, fail_after: int | None = None) -> None:
        self.value = value
        self.offset = 0
        self.fail_after = fail_after

    def read(self, size: int = -1) -> bytes:
        if self.fail_after is not None and self.offset >= self.fail_after:
            raise RuntimeError("secret provider detail")
        if size < 0:
            size = len(self.value) - self.offset
        end = min(len(self.value), self.offset + size)
        if self.fail_after is not None:
            end = min(end, self.fail_after)
        result = self.value[self.offset : end]
        self.offset = end
        return result

    def close(self) -> None:
        pass


class _FakeS3:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.head_calls: list[dict] = []
        self.get_calls: list[dict] = []
        self.fail_first_after: int | None = None
        self.get_count = 0

    def head_object(self, **request):
        self.head_calls.append(dict(request))
        value = self.objects[str(request["Key"])]
        return {"ContentLength": len(value), "ETag": '"fixture"'}

    def get_object(self, **request):
        self.get_calls.append(dict(request))
        value = self.objects[str(request["Key"])]
        start = 0
        response = {}
        if "Range" in request:
            start = int(str(request["Range"]).removeprefix("bytes=").removesuffix("-"))
            response["ContentRange"] = f"bytes {start}-{len(value) - 1}/{len(value)}"
        fail_after = self.fail_first_after if self.get_count == 0 else None
        self.get_count += 1
        response["Body"] = _Body(value[start:], fail_after=fail_after)
        return response


def _binding(bootstrap: bytes) -> dict:
    return {
        "schema": HANDOFF_SCHEMA,
        "freeze_sha256": "a" * 64,
        "volume_id": "plan082volume",
        "region": "us-ca-1",
        "endpoint": "https://s3api-us-ca-1.runpod.io/",
        "task_root": "rondo-plan082-formal-fixture/",
        "allowed_prefixes": ["runs/formal/", "freeze/"],
        "destination_relative": "eval-data/publication-critic/plan082/handoff/plan082-formal-fixture",
        "bootstrap_manifest": {
            "relative_key": "bootstrap-manifest.json",
            "bytes": len(bootstrap),
            "sha256": hashlib.sha256(bootstrap).hexdigest(),
        },
        "limits": {"max_objects": 16, "max_total_bytes": 1024 * 1024},
    }


def _bootstrap(payload: bytes) -> bytes:
    core = {
        "schema": BOOTSTRAP_SCHEMA,
        "freeze_sha256": "a" * 64,
        "objects": [
            {
                "relative_key": "runs/formal/checkpoint.bin",
                "bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "roles": ["latest", "recovery"],
            }
        ],
    }
    return pretty_json_bytes(
        {
            **core,
            "content_sha256": hashlib.sha256(canonical_json_bytes(core)).hexdigest(),
        }
    )


class Plan082HandoffTests(unittest.TestCase):
    def test_retained_bootstrap_is_derived_from_verified_artifact_files(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            task_root = Path(directory) / "rondo-plan082-formal-fixture"
            artifact_root = task_root / "runs" / "formal"
            store = Plan081ArtifactStore(artifact_root)
            snapshot_id = "snapshot-attempt-001-step-000001"
            checkpoint_id = "checkpoint-attempt-001-step-000001"
            base_observation = store.write_observation(
                "base-step-000000", {"schema": OBSERVATION_SCHEMA, "step": 0}
            )
            training_observation = store.write_observation(
                "observation-attempt-001-step-000001",
                {"schema": OBSERVATION_SCHEMA, "step": 1},
            )
            snapshot = store.save_snapshot(
                snapshot_id,
                model_saver=lambda payload: (payload / "weights.bin").write_bytes(
                    b"snapshot"
                ),
                metadata={"global_step": 1},
            )
            checkpoint = store.save_checkpoint(
                checkpoint_id,
                model_saver=lambda payload: (payload / "weights.bin").write_bytes(
                    b"checkpoint"
                ),
                training_state={"step": 1},
                controller_state={"step": 1},
                metadata={"global_step": 1},
            )
            result = {
                "schema": RESULT_SCHEMA,
                "freeze_content_sha256": "a" * 64,
                "retention": {
                    "observations": [
                        {
                            "artifact_id": "base-step-000000",
                            "sha256": base_observation["sha256"],
                            "roles": ["base_observation"],
                        },
                        {
                            "artifact_id": "observation-attempt-001-step-000001",
                            "sha256": training_observation["sha256"],
                            "roles": ["validation_observation"],
                        },
                    ],
                    "checkpoints": [
                        {
                            "artifact_id": checkpoint_id,
                            "content_sha256": checkpoint["content_sha256"],
                            "roles": ["latest_checkpoint", "recovery_proven"],
                        }
                    ],
                    "snapshots": [
                        {
                            "artifact_id": snapshot_id,
                            "content_sha256": snapshot["content_sha256"],
                            "roles": ["training_best_snapshot"],
                        }
                    ],
                },
            }
            destination = task_root / "bootstrap.json"
            create_retained_bootstrap_manifest(
                destination,
                freeze_sha256="a" * 64,
                task_root=task_root,
                artifact_root=artifact_root,
                formal_result=result,
            )
            value = json.loads(destination.read_text(encoding="utf-8"))
            keys = {row["relative_key"] for row in value["objects"]}
            self.assertIn(
                f"runs/formal/recovery-checkpoints/{checkpoint_id}/artifact-manifest.json",
                keys,
            )
            self.assertIn(
                f"runs/formal/model-snapshots/{snapshot_id}/payload/weights.bin",
                keys,
            )
            self.assertIn(
                "runs/formal/observations/base-step-000000/observation.json",
                keys,
            )
            self.assertIn(
                "runs/formal/observations/observation-attempt-001-step-000001/observation.json",
                keys,
            )
            self.assertTrue(
                all(
                    Path(row["relative_key"]).is_relative_to("runs/formal")
                    for row in value["objects"]
                )
            )

            stale = json.loads(json.dumps(result))
            stale["retention"]["checkpoints"][0]["content_sha256"] = "b" * 64
            with self.assertRaisesRegex(
                HandoffError, "plan082_retained_artifact_identity_mismatch"
            ):
                create_retained_bootstrap_manifest(
                    task_root / "stale.json",
                    freeze_sha256="a" * 64,
                    task_root=task_root,
                    artifact_root=artifact_root,
                    formal_result=stale,
                )

            missing = json.loads(json.dumps(result))
            missing["retention"]["snapshots"][0]["artifact_id"] = (
                "snapshot-attempt-001-step-000002"
            )
            with self.assertRaisesRegex(
                HandoffError, "plan082_retained_artifact_set_mismatch"
            ):
                create_retained_bootstrap_manifest(
                    task_root / "missing.json",
                    freeze_sha256="a" * 64,
                    task_root=task_root,
                    artifact_root=artifact_root,
                    formal_result=missing,
                )

            missing_observation = json.loads(json.dumps(result))
            missing_observation["retention"]["observations"].pop()
            with self.assertRaisesRegex(
                HandoffError, "plan082_retained_artifact_set_mismatch"
            ):
                create_retained_bootstrap_manifest(
                    task_root / "missing-observation.json",
                    freeze_sha256="a" * 64,
                    task_root=task_root,
                    artifact_root=artifact_root,
                    formal_result=missing_observation,
                )

            link = (
                artifact_root
                / "model-snapshots"
                / snapshot_id
                / "payload"
                / "unexpected-link"
            )
            link.symlink_to("weights.bin")
            with self.assertRaises(FullModelTrainingError):
                create_retained_bootstrap_manifest(
                    task_root / "nonregular.json",
                    freeze_sha256="a" * 64,
                    task_root=task_root,
                    artifact_root=artifact_root,
                    formal_result=result,
                )

            unrelated_root = Path(directory) / "unrelated-task"
            unrelated_root.mkdir()
            with self.assertRaisesRegex(
                HandoffError, "plan082_handoff_artifact_root_invalid"
            ):
                create_retained_bootstrap_manifest(
                    task_root / "outside-root.json",
                    freeze_sha256="a" * 64,
                    task_root=unrelated_root,
                    artifact_root=artifact_root,
                    formal_result=result,
                )

    def test_local_handoff_preflight_binds_source_environment_without_secrets(
        self,
    ) -> None:
        manifest = _bootstrap(b"payload")
        binding = validate_handoff(_binding(manifest))
        requirements = {
            "boto3": "1.40.21",
            "botocore": "1.40.21",
            "jmespath": "1.0.1",
            "s3transfer": "0.13.1",
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            source = root / "source"
            source.mkdir()
            requirements_path = root / "requirements.txt"
            requirements_path.write_text(
                "".join(
                    f"{name}=={version}\n" for name, version in requirements.items()
                ),
                encoding="utf-8",
            )
            with (
                mock.patch(
                    "rondo_eval.publication_critic.full_model_training."
                    "plan082_handoff.importlib.metadata.version",
                    side_effect=requirements.__getitem__,
                ),
                mock.patch(
                    "rondo_eval.publication_critic.full_model_training."
                    "plan082_handoff.load_allowlisted_secret_values"
                ) as secret_loader,
            ):
                receipt = local_handoff_preflight(
                    binding,
                    operation="inventory",
                    requirements_path=requirements_path,
                    source_root=source,
                    destination_root=root / "destination",
                )
            secret_loader.assert_not_called()
            self.assertFalse(receipt["secret_access"])
            self.assertFalse(receipt["network_access"])
            self.assertEqual(receipt["source_root"], str(source))
            self.assertEqual(receipt["dependencies"], requirements)

            with (
                mock.patch(
                    "rondo_eval.publication_critic.full_model_training.plan082_handoff."
                    "importlib.metadata.version",
                    return_value="0.0",
                ),
                self.assertRaisesRegex(
                    HandoffError, "plan082_handoff_dependency_version_mismatch"
                ),
            ):
                local_handoff_preflight(
                    binding,
                    operation="download",
                    requirements_path=requirements_path,
                    source_root=source,
                    destination_root=root / "destination",
                )

    def test_pure_producers_create_valid_bootstrap_and_binding(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bootstrap = root / "bootstrap.json"
            create_bootstrap_manifest(
                bootstrap,
                freeze_sha256="a" * 64,
                objects=[
                    {
                        "relative_key": "runs/formal/checkpoint.bin",
                        "bytes": 7,
                        "sha256": "b" * 64,
                        "roles": ["candidate", "recovery"],
                    }
                ],
            )
            binding_path = root / "binding.json"
            create_handoff_binding(
                binding_path,
                freeze_sha256="a" * 64,
                volume_id="plan082volume",
                region="us-ca-1",
                task_root="rondo-plan082-formal-fixture/",
                allowed_prefixes=["runs/formal/"],
                run_id="plan082-formal-fixture",
                bootstrap_key="bootstrap-manifest.json",
                bootstrap_path=bootstrap,
                max_objects=16,
                max_total_bytes=1024,
            )
            binding = load_handoff(binding_path)
            specs = bootstrap_manifest_specs(bootstrap.read_bytes(), binding=binding)
            self.assertEqual(specs[0].relative_key, "runs/formal/checkpoint.bin")
            self.assertEqual(binding.endpoint, "https://s3api-us-ca-1.runpod.io/")
            with self.assertRaisesRegex(HandoffError, "plan082_bootstrap_invalid"):
                create_handoff_binding(
                    root / "mismatched-binding.json",
                    freeze_sha256="c" * 64,
                    volume_id="plan082volume",
                    region="us-ca-1",
                    task_root="rondo-plan082-formal-fixture/",
                    allowed_prefixes=["runs/formal/"],
                    run_id="plan082-formal-fixture",
                    bootstrap_key="bootstrap-manifest.json",
                    bootstrap_path=bootstrap,
                    max_objects=16,
                    max_total_bytes=1024,
                )

    def test_binding_is_parameterized_and_rejects_plan068_resource(self) -> None:
        manifest = _bootstrap(b"payload")
        binding = validate_handoff(_binding(manifest))
        self.assertEqual(binding.volume_id, "plan082volume")
        self.assertEqual(binding.region, "us-ca-1")
        bad = {**_binding(manifest), "volume_id": "hi3iaz8rsr"}
        with self.assertRaisesRegex(
            HandoffError, "plan082_handoff_provider_binding_invalid"
        ):
            validate_handoff(bad)
        bad_endpoint = {
            **_binding(manifest),
            "endpoint": "https://user@s3api-us-ca-1.runpod.io/",
        }
        with self.assertRaisesRegex(
            HandoffError, "plan082_handoff_provider_binding_invalid"
        ):
            validate_handoff(bad_endpoint)

    def test_bootstrap_first_inventory_and_download_are_manifest_driven(self) -> None:
        payload = b"formal checkpoint payload"
        manifest = _bootstrap(payload)
        binding = validate_handoff(_binding(manifest))
        objects = {
            binding.task_root + "bootstrap-manifest.json": manifest,
            binding.task_root + "runs/formal/checkpoint.bin": payload,
        }
        fake = _FakeS3(objects)
        client = ScopedHandoffClient(fake, scope=binding.scope)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "handoff"
            records = inventory(client, binding, destination)
            self.assertEqual(
                [row["status"] for row in records], ["downloaded", "missing"]
            )
            records = download(client, binding, destination)
            self.assertEqual(
                [row["status"] for row in records],
                ["verified_existing", "downloaded"],
            )
            self.assertEqual(
                (destination / "runs/formal/checkpoint.bin").read_bytes(),
                payload,
            )
            self.assertEqual(
                stat.S_IMODE(
                    (destination / "runs/formal/checkpoint.bin").stat().st_mode
                ),
                0o600,
            )
            repeated = download(client, binding, destination)
            self.assertTrue(
                all(row["status"] == "verified_existing" for row in repeated)
            )

    def test_partial_range_resume_and_wrong_existing_file_rejection(self) -> None:
        payload = b"0123456789abcdef"
        manifest = _bootstrap(payload)
        binding = validate_handoff(_binding(manifest))
        objects = {
            binding.task_root + "bootstrap-manifest.json": manifest,
            binding.task_root + "runs/formal/checkpoint.bin": payload,
        }
        fake = _FakeS3(objects)
        fake.fail_first_after = 5
        client = ScopedHandoffClient(fake, scope=binding.scope)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "handoff"
            with self.assertRaisesRegex(HandoffError, "download_stream_failed"):
                download(client, binding, destination)
            partial = destination / "bootstrap-manifest.json.part"
            self.assertEqual(partial.stat().st_size, 5)
            download(client, binding, destination)
            self.assertEqual(fake.get_calls[1]["Range"], "bytes=5-")

            checkpoint = destination / "runs/formal/checkpoint.bin"
            checkpoint.write_bytes(b"wrong but same length"[: len(payload)])
            checkpoint.chmod(0o600)
            with self.assertRaisesRegex(
                HandoffError, "download_existing_identity_mismatch"
            ):
                download(client, binding, destination)

    def test_manifest_rejects_escape_duplicates_and_unbounded_payload(self) -> None:
        payload = b"payload"
        manifest = _bootstrap(payload)
        binding = validate_handoff(_binding(manifest))
        self.assertEqual(len(bootstrap_manifest_specs(manifest, binding=binding)), 1)
        value = json.loads(manifest)
        value["objects"][0]["relative_key"] = "../checkpoint.bin"
        core = {key: item for key, item in value.items() if key != "content_sha256"}
        unsafe = pretty_json_bytes(
            {
                **core,
                "content_sha256": hashlib.sha256(
                    canonical_json_bytes(core)
                ).hexdigest(),
            }
        )
        unsafe_binding = validate_handoff(_binding(unsafe))
        with self.assertRaisesRegex(
            HandoffError, "plan082_handoff_relative_path_invalid"
        ):
            bootstrap_manifest_specs(unsafe, binding=unsafe_binding)

    def test_direct_dataclass_cannot_redirect_secret_bearing_client(self) -> None:
        manifest = _bootstrap(b"payload")
        valid = validate_handoff(_binding(manifest))
        malicious = Plan082Handoff(
            **{
                **valid.__dict__,
                "endpoint": "https://attacker.example/",
            }
        )
        with tempfile.TemporaryDirectory() as directory:
            paths = RepoPaths(Path(directory), Path(directory))
            with mock.patch(
                "rondo_eval.publication_critic.full_model_training.plan082_handoff."
                "load_allowlisted_secret_values"
            ) as loader:
                with self.assertRaisesRegex(
                    HandoffError, "plan082_handoff_provider_binding_invalid"
                ):
                    create_handoff_client(paths, malicious, client_factory=mock.Mock())
                loader.assert_not_called()

    def test_manifest_rejects_partial_and_file_tree_collisions(self) -> None:
        def manifest_for(keys: list[str]) -> tuple[bytes, object]:
            objects = [
                {
                    "relative_key": key,
                    "bytes": 1,
                    "sha256": hashlib.sha256(key.encode()).hexdigest(),
                    "roles": ["artifact"],
                }
                for key in keys
            ]
            core = {
                "schema": BOOTSTRAP_SCHEMA,
                "freeze_sha256": "a" * 64,
                "objects": objects,
            }
            raw = pretty_json_bytes(
                {
                    **core,
                    "content_sha256": hashlib.sha256(
                        canonical_json_bytes(core)
                    ).hexdigest(),
                }
            )
            return raw, validate_handoff(_binding(raw))

        for keys in (
            ["runs/formal/a", "runs/formal/a.part"],
            ["runs/formal/a", "runs/formal/a/b"],
            ["runs/formal/a", "runs/formal/a.part/b"],
        ):
            raw, binding = manifest_for(keys)
            with (
                self.subTest(keys=keys),
                self.assertRaisesRegex(
                    HandoffError,
                    "plan082_bootstrap_(objects_invalid|path_collision)",
                ),
            ):
                bootstrap_manifest_specs(raw, binding=binding)


if __name__ == "__main__":
    unittest.main()
