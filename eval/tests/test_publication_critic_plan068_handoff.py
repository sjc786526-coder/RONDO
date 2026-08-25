from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import unittest


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.local_deployment import (  # noqa: E402
    FORMAL_FREEZE_PREFIX,
    FORMAL_RUN_PREFIX,
    HANDOFF_ROOT,
    SOURCE_BUNDLE_PREFIX,
    VOLUME_ID,
    WINNER_LOCK_KEY,
    DownloadSpec,
    HandoffClient,
    HandoffError,
    exact_base_requirements,
    formal_manifest_requirements,
    parse_artifact_manifest,
)
from rondo_eval.config import RepoPaths  # noqa: E402
from rondo_eval.publication_critic.local_deployment.handoff_cli import (  # noqa: E402
    BUNDLE_MANIFEST,
    DEPENDENCY_FREEZE,
    DEPENDENCY_IDENTITY,
    FLASHOPTIM_WHEEL,
    FORMAL_PENDING,
    FORMAL_START,
    RUNPOD_S3_ENDPOINT,
    RUNPOD_S3_REGION,
    WINNER_LOCK,
    _transfer_one,
    create_handoff_client,
    fixed_requirements,
)


def _canonical_sha256(value: object) -> str:
    raw = (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    return hashlib.sha256(raw).hexdigest()


def _pretty(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )


class _InterruptingBody:
    def __init__(self, data: bytes, fail_after: int | None = None) -> None:
        self.data = data
        self.fail_after = fail_after
        self.offset = 0
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        if self.fail_after is not None and self.offset >= self.fail_after:
            raise RuntimeError("provider failure includes TOP-SECRET")
        if size < 0:
            size = len(self.data) - self.offset
        end = min(len(self.data), self.offset + size)
        if self.fail_after is not None:
            end = min(end, self.fail_after)
        result = self.data[self.offset : end]
        self.offset = end
        return result

    def close(self) -> None:
        self.closed = True


class _FakeS3:
    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = objects or {}
        self.list_responses: list[dict[str, object]] = []
        self.list_calls: list[dict[str, object]] = []
        self.head_calls: list[dict[str, object]] = []
        self.get_calls: list[dict[str, object]] = []
        self.fail_first_get_after: int | None = None
        self._get_count = 0

    def list_objects_v2(self, **request: object) -> dict[str, object]:
        self.list_calls.append(dict(request))
        if not self.list_responses:
            raise RuntimeError("unexpected list with TOP-SECRET")
        return self.list_responses.pop(0)

    def head_object(self, **request: object) -> dict[str, object]:
        self.head_calls.append(dict(request))
        key = str(request["Key"])
        if key not in self.objects:
            raise RuntimeError("missing object with TOP-SECRET")
        return {
            "ContentLength": len(self.objects[key]),
            "ETag": '"not-a-security-hash"',
        }

    def get_object(self, **request: object) -> dict[str, object]:
        self.get_calls.append(dict(request))
        key = str(request["Key"])
        data = self.objects[key]
        range_value = request.get("Range")
        start = 0
        response: dict[str, object] = {}
        if range_value is not None:
            start = int(str(range_value).removeprefix("bytes=").removesuffix("-"))
            response["ContentRange"] = f"bytes {start}-{len(data) - 1}/{len(data)}"
        fail_after = None
        if self._get_count == 0 and self.fail_first_get_after is not None:
            fail_after = self.fail_first_get_after
        self._get_count += 1
        response["Body"] = _InterruptingBody(data[start:], fail_after)
        return response


class _SecretFailingS3:
    def head_object(self, **_request: object) -> dict[str, object]:
        raise RuntimeError("credentials=TOP-SECRET")


class Plan068HandoffTests(unittest.TestCase):
    def test_exact_volume_root_and_prefix_allowlist(self) -> None:
        with self.assertRaisesRegex(HandoffError, "handoff_bucket_not_allowed"):
            HandoffClient(_FakeS3(), bucket="another-volume")
        with self.assertRaisesRegex(HandoffError, "handoff_root_not_allowed"):
            HandoffClient(_FakeS3(), root="another-root/")

        client = HandoffClient(_FakeS3())
        with self.assertRaisesRegex(HandoffError, "handoff_prefix_not_allowed"):
            client.list_level("venv/")
        with self.assertRaisesRegex(HandoffError, "handoff_prefix_not_allowed"):
            client.list_level("bundle/")
        with self.assertRaisesRegex(HandoffError, "handoff_prefix_not_allowed"):
            client.list_level("formal-freeze/")
        with self.assertRaisesRegex(HandoffError, "handoff_prefix_invalid"):
            client.list_level("runs")
        with self.assertRaisesRegex(HandoffError, "handoff_object_not_allowed"):
            client.head("venv/bin/python")

    def test_delimiter_listing_is_bounded_and_root_relative(self) -> None:
        fake = _FakeS3()
        fake.list_responses = [
            {
                "Contents": [
                    {
                        "Key": HANDOFF_ROOT + "dependency-identity-observed.json",
                        "Size": 321,
                        "ETag": '"etag"',
                    }
                ],
                "CommonPrefixes": [{"Prefix": HANDOFF_ROOT + "runs/"}],
                "IsTruncated": True,
                "NextContinuationToken": "page-2",
            },
            {
                "Contents": [],
                "CommonPrefixes": [{"Prefix": HANDOFF_ROOT + "model/"}],
                "IsTruncated": False,
            },
        ]
        listing = HandoffClient(fake).list_level(max_entries=3, max_pages=2)
        self.assertEqual(listing.relative_prefix, "")
        self.assertEqual(
            listing.objects[0].relative_key,
            "dependency-identity-observed.json",
        )
        self.assertEqual(listing.objects[0].size, 321)
        self.assertEqual(listing.common_prefixes, ("runs/", "model/"))
        self.assertEqual(
            fake.list_calls,
            [
                {
                    "Bucket": VOLUME_ID,
                    "Prefix": HANDOFF_ROOT,
                    "Delimiter": "/",
                    "MaxKeys": 3,
                },
                {
                    "Bucket": VOLUME_ID,
                    "Prefix": HANDOFF_ROOT,
                    "Delimiter": "/",
                    "MaxKeys": 1,
                    "ContinuationToken": "page-2",
                },
            ],
        )

    def test_list_page_limit_fails_closed(self) -> None:
        fake = _FakeS3()
        fake.list_responses = [
            {
                "Contents": [],
                "CommonPrefixes": [],
                "IsTruncated": True,
                "NextContinuationToken": "more",
            }
        ]
        with self.assertRaisesRegex(HandoffError, "handoff_list_page_limit_exceeded"):
            HandoffClient(fake).list_level("runs/", max_entries=4, max_pages=1)

    def test_head_is_exact_and_provider_error_does_not_leak_secret(self) -> None:
        key = HANDOFF_ROOT + "model/config.json"
        fake = _FakeS3({key: b"{}\n"})
        remote = HandoffClient(fake).head("model/config.json")
        self.assertEqual(remote.size, 3)
        self.assertEqual(
            fake.head_calls,
            [{"Bucket": VOLUME_ID, "Key": key}],
        )

        with self.assertRaises(HandoffError) as captured:
            HandoffClient(_SecretFailingS3()).head("model/config.json")
        self.assertEqual(str(captured.exception), "handoff_head_failed")
        self.assertNotIn("TOP-SECRET", repr(captured.exception))
        self.assertIsNone(captured.exception.__cause__)

    def test_exact_base_and_formal_manifest_requirements(self) -> None:
        base = exact_base_requirements()
        self.assertEqual(len(base), 9)
        weight = next(item for item in base if item.relative_key.endswith("model.safetensors"))
        self.assertEqual(weight.size, 3_441_189_792)
        manifests = formal_manifest_requirements(FORMAL_RUN_PREFIX)
        self.assertEqual(len(manifests), 5)
        self.assertEqual(
            manifests[0].relative_key,
            FORMAL_RUN_PREFIX + "candidate-c1/candidate-manifest.json",
        )
        with self.assertRaisesRegex(HandoffError, "artifact_prefix_not_allowed"):
            formal_manifest_requirements("model/")

    def test_observed_handoff_prefixes_and_winner_lock_are_frozen(self) -> None:
        self.assertEqual(SOURCE_BUNDLE_PREFIX, "bundle-plan066-final-01/")
        self.assertEqual(FORMAL_FREEZE_PREFIX, "formal-freeze-plan066-final01/")
        self.assertEqual(FORMAL_RUN_PREFIX, "runs/plan066-formal-final01-01/")
        self.assertEqual(WINNER_LOCK_KEY, "controller/winner-lock.json")

        fake = _FakeS3({HANDOFF_ROOT + WINNER_LOCK_KEY: b"{}\n"})
        fake.list_responses = [
            {"Contents": [], "CommonPrefixes": [], "IsTruncated": False},
            {"Contents": [], "CommonPrefixes": [], "IsTruncated": False},
        ]
        client = HandoffClient(fake)
        client.list_level(SOURCE_BUNDLE_PREFIX)
        client.list_level(FORMAL_FREEZE_PREFIX)
        self.assertEqual(client.head(WINNER_LOCK_KEY).size, 3)
        self.assertEqual(
            [call["Prefix"] for call in fake.list_calls],
            [
                HANDOFF_ROOT + SOURCE_BUNDLE_PREFIX,
                HANDOFF_ROOT + FORMAL_FREEZE_PREFIX,
            ],
        )

    def test_manifest_drives_payload_plan_and_rejects_traversal(self) -> None:
        core = {
            "schema": "rondo-publication-critic-plan066-candidate-v1",
            "created_at": "2026-08-24T00:00:00Z",
            "stage": "C1",
            "global_step": 1,
            "identity_sha256": "1" * 64,
            "format": "transformers_model_only_safetensors",
            "files": {
                "config.json": {"bytes": 3, "sha256": hashlib.sha256(b"{}\n").hexdigest()},
                "model.safetensors": {"bytes": 4, "sha256": hashlib.sha256(b"data").hexdigest()},
            },
        }
        manifest = {**core, "content_sha256": _canonical_sha256(core)}
        raw = _pretty(manifest)
        plan = parse_artifact_manifest(
            FORMAL_RUN_PREFIX + "candidate-c1/candidate-manifest.json",
            raw,
            expected_sha256=hashlib.sha256(raw).hexdigest(),
            expected_payload_bytes=7,
        )
        self.assertEqual(plan.payload_bytes, 7)
        self.assertEqual(
            [item.relative_key for item in plan.files],
            [
                FORMAL_RUN_PREFIX + "candidate-c1/config.json",
                FORMAL_RUN_PREFIX + "candidate-c1/model.safetensors",
            ],
        )

        unsafe_core = {**core, "files": {"../escape": core["files"]["config.json"]}}
        unsafe = {**unsafe_core, "content_sha256": _canonical_sha256(unsafe_core)}
        unsafe_raw = _pretty(unsafe)
        with self.assertRaisesRegex(HandoffError, "artifact_relative_path_invalid"):
            parse_artifact_manifest(
                FORMAL_RUN_PREFIX + "candidate-c1/candidate-manifest.json",
                unsafe_raw,
                expected_sha256=hashlib.sha256(unsafe_raw).hexdigest(),
            )

    def test_part_resume_range_atomic_publish_and_private_modes(self) -> None:
        payload = b"0123456789abcdef"
        relative = FORMAL_RUN_PREFIX + "candidate-c1/model.safetensors"
        fake = _FakeS3({HANDOFF_ROOT + relative: payload})
        fake.fail_first_get_after = 5
        client = HandoffClient(fake)
        spec = DownloadSpec(relative, len(payload), hashlib.sha256(payload).hexdigest())
        with tempfile.TemporaryDirectory() as temp:
            destination_root = Path(temp) / "handoff"
            with self.assertRaisesRegex(HandoffError, "download_stream_failed"):
                client.download(spec, destination_root, chunk_bytes=4)
            partial = destination_root / (relative + ".part")
            self.assertEqual(partial.read_bytes(), payload[:5])

            destination = client.download(spec, destination_root, chunk_bytes=4)
            self.assertEqual(destination.read_bytes(), payload)
            self.assertFalse(partial.exists())
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(destination_root.stat().st_mode), 0o700)
            self.assertEqual(
                fake.get_calls[1]["Range"],
                "bytes=5-",
            )

    def test_empty_partial_is_a_valid_retry_point(self) -> None:
        payload = b"retry-after-zero-bytes"
        relative = "model/config.json"
        fake = _FakeS3({HANDOFF_ROOT + relative: payload})
        spec = DownloadSpec(relative, len(payload), hashlib.sha256(payload).hexdigest())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "handoff"
            partial = root / (relative + ".part")
            partial.parent.mkdir(mode=0o700, parents=True)
            partial.write_bytes(b"")
            partial.chmod(0o600)
            destination = HandoffClient(fake).download(spec, root)
            self.assertEqual(destination.read_bytes(), payload)
            self.assertFalse(partial.exists())
            self.assertNotIn("Range", fake.get_calls[0])

    def test_existing_destination_is_rejected_before_provider_use(self) -> None:
        payload = b"payload"
        relative = "model/config.json"
        fake = _FakeS3({HANDOFF_ROOT + relative: payload})
        client = HandoffClient(fake)
        spec = DownloadSpec(relative, len(payload), hashlib.sha256(payload).hexdigest())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "handoff"
            destination = root / relative
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"user-data")
            with self.assertRaisesRegex(HandoffError, "download_destination_exists"):
                client.download(spec, root)
            self.assertEqual(destination.read_bytes(), b"user-data")
            self.assertEqual(fake.head_calls, [])
            self.assertEqual(fake.get_calls, [])

    def test_empty_object_is_published_without_get(self) -> None:
        relative = SOURCE_BUNDLE_PREFIX + "empty-marker"
        fake = _FakeS3({HANDOFF_ROOT + relative: b""})
        spec = DownloadSpec(relative, 0, hashlib.sha256(b"").hexdigest())
        with tempfile.TemporaryDirectory() as temp:
            destination = HandoffClient(fake).download(spec, Path(temp) / "handoff")
            self.assertEqual(destination.read_bytes(), b"")
            self.assertEqual(stat.S_IMODE(destination.stat().st_mode), 0o600)
            self.assertEqual(fake.get_calls, [])

    @unittest.skipUnless(hasattr(os, "symlink"), "symlink support required")
    def test_symlinked_destination_ancestor_is_rejected(self) -> None:
        payload = b"payload"
        relative = "model/config.json"
        fake = _FakeS3({HANDOFF_ROOT + relative: payload})
        client = HandoffClient(fake)
        spec = DownloadSpec(relative, len(payload), hashlib.sha256(payload).hexdigest())
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            outside = base / "outside"
            outside.mkdir()
            link = base / "linked"
            link.symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(HandoffError, "download_root_unsafe"):
                client.download(spec, link / "handoff")
            self.assertEqual(list(outside.iterdir()), [])
            self.assertEqual(fake.head_calls, [])

    def test_hash_mismatch_discards_only_private_partial(self) -> None:
        payload = b"payload"
        relative = "model/config.json"
        fake = _FakeS3({HANDOFF_ROOT + relative: payload})
        spec = DownloadSpec(relative, len(payload), "0" * 64)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "handoff"
            with self.assertRaisesRegex(HandoffError, "download_hash_mismatch"):
                HandoffClient(fake).download(spec, root)
            self.assertFalse((root / (relative + ".part")).exists())
            self.assertFalse((root / relative).exists())

    def test_cli_fixed_requirements_match_observed_remote_keys(self) -> None:
        requirements = {item.relative_key: item for item in fixed_requirements()}
        for item in (
            BUNDLE_MANIFEST,
            DEPENDENCY_FREEZE,
            DEPENDENCY_IDENTITY,
            FLASHOPTIM_WHEEL,
            FORMAL_START,
            FORMAL_PENDING,
            WINNER_LOCK,
        ):
            self.assertEqual(requirements[item.relative_key], item)
        self.assertIn(
            FORMAL_RUN_PREFIX + "candidate-c1/candidate-manifest.json",
            requirements,
        )
        self.assertIn(
            FORMAL_RUN_PREFIX + "checkpoint-c3/checkpoint-manifest.json",
            requirements,
        )

    def test_cli_secret_loader_injects_only_exact_values_into_factory(self) -> None:
        sentinel_access = "sentinel-access"
        sentinel_secret = "sentinel-secret"
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "rondo.secrets.example.env").write_text(
                "RUNPOD_S3_ACCESS_KEY_ID=\nRUNPOD_S3_SECRET_ACCESS_KEY=\n",
                encoding="utf-8",
            )
            env = root / ".env.local"
            env.write_text(
                "RUNPOD_S3_ACCESS_KEY_ID="
                + sentinel_access
                + "\nRUNPOD_S3_SECRET_ACCESS_KEY="
                + sentinel_secret
                + "\n",
                encoding="utf-8",
            )
            env.chmod(0o600)
            captured: dict[str, object] = {}

            def factory(**kwargs: object) -> _FakeS3:
                captured.update(kwargs)
                return _FakeS3()

            client = create_handoff_client(
                RepoPaths(common_root=root, worktree_root=root),
                client_factory=factory,
            )
            self.assertIsInstance(client, HandoffClient)
            self.assertEqual(captured["endpoint_url"], RUNPOD_S3_ENDPOINT)
            self.assertEqual(captured["region_name"], RUNPOD_S3_REGION)
            self.assertEqual(captured["aws_access_key_id"], sentinel_access)
            self.assertEqual(captured["aws_secret_access_key"], sentinel_secret)

    def test_cli_verified_existing_is_not_overwritten(self) -> None:
        payload = b"already-present"
        relative = "model/config.json"
        fake = _FakeS3({HANDOFF_ROOT + relative: payload})
        spec = DownloadSpec(relative, len(payload), hashlib.sha256(payload).hexdigest())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "handoff"
            destination = root / relative
            destination.parent.mkdir(mode=0o700, parents=True)
            destination.write_bytes(payload)
            destination.chmod(0o600)
            record = _transfer_one(HandoffClient(fake), root, spec)
            self.assertEqual(
                record,
                {
                    "key": relative,
                    "size": len(payload),
                    "hash": hashlib.sha256(payload).hexdigest(),
                    "status": "verified_existing",
                },
            )
            self.assertEqual(fake.head_calls, [])
            self.assertEqual(fake.get_calls, [])

    def test_cli_rejects_verified_bytes_with_non_private_mode(self) -> None:
        payload = b"already-present"
        relative = "model/config.json"
        fake = _FakeS3({HANDOFF_ROOT + relative: payload})
        spec = DownloadSpec(relative, len(payload), hashlib.sha256(payload).hexdigest())
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "handoff"
            destination = root / relative
            destination.parent.mkdir(mode=0o700, parents=True)
            destination.write_bytes(payload)
            destination.chmod(0o644)
            with self.assertRaisesRegex(HandoffError, "download_existing_identity_mismatch"):
                _transfer_one(HandoffClient(fake), root, spec)
            self.assertEqual(fake.head_calls, [])
            self.assertEqual(fake.get_calls, [])


if __name__ == "__main__":
    unittest.main()
