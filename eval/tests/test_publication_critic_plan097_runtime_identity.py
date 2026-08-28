from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = REPO_ROOT / "eval"
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.local_deployment.worker import (  # noqa: E402
    WorkerError,
    _load_descriptor,
)


def _descriptor(object_id: object) -> dict[str, object]:
    return {
        "worker_protocol": "rondo-publication-critic-worker-v1",
        "object_id": object_id,
        "deployment_artifact_sha256": "a" * 64,
        "qualification_freeze_sha256": "b" * 64,
        "service_descriptor": {},
    }


class RuntimeDescriptorIdentityTests(unittest.TestCase):
    def _load(self, object_id: object) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "descriptor.json"
            path.write_text(json.dumps(_descriptor(object_id)), encoding="utf-8")
            return _load_descriptor(path)

    def test_accepts_legacy_and_bounded_runtime_object_ids(self) -> None:
        for object_id in (
            "base",
            "c1",
            "c2",
            "c3",
            "qualified-plan097",
            "Skywork.Reward_V2-1.7B",
            "a" * 128,
        ):
            with self.subTest(object_id=object_id):
                self.assertEqual(self._load(object_id)["object_id"], object_id)

    def test_rejects_unsafe_or_unbounded_runtime_object_ids(self) -> None:
        for object_id in (
            "",
            "-leading",
            "_leading",
            ".leading",
            "contains/slash",
            "contains space",
            "non-ascii-é",
            "a" * 129,
            7,
        ):
            with self.subTest(object_id=object_id):
                with self.assertRaisesRegex(
                    WorkerError,
                    "worker descriptor identity is invalid",
                ):
                    self._load(object_id)


if __name__ == "__main__":
    unittest.main()
