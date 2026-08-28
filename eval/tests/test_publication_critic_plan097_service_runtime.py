from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
EVAL_ROOT = REPO_ROOT / "eval"
if str(EVAL_ROOT) not in sys.path:
    sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.engineering import service_runtime  # noqa: E402
from rondo_eval.publication_critic.engineering.service_runtime import (  # noqa: E402
    LocalRuntime,
    RuntimeBinaries,
    ServiceRuntimeError,
    start_cloud_service,
)


class ServiceRuntimeTests(unittest.TestCase):
    def test_local_runtime_accepts_the_bounded_venv_python_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            python = root / "python"
            python.symlink_to(Path(sys.executable).resolve())
            snapshot = root / "snapshot"
            repo = root / "repo"
            snapshot.mkdir()
            repo.mkdir()
            descriptor = root / "descriptor.json"
            descriptor.write_text("{}\n", encoding="utf-8")

            LocalRuntime(
                python=python,
                snapshot=snapshot,
                repo_root=repo,
                descriptor=descriptor,
            ).validate()

    def test_cloud_runtime_descriptor_changes_only_private_transport(self) -> None:
        tracked = (
            REPO_ROOT
            / "eval/locks/publication-critic-plan096-cloud-descriptor-v1.json"
        )
        expected = json.loads(tracked.read_text(encoding="utf-8"))
        executable = Path(sys.executable).resolve()
        binaries = RuntimeBinaries(
            codex=executable,
            real_service=executable,
            cloud_service=executable,
            probe=executable,
        )
        secret = "temporary-downstream-secret"
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary) / "runtime-descriptor.json"
            sentinel = object()
            with patch.object(
                service_runtime,
                "_start_service",
                return_value=sentinel,
            ) as start:
                actual = start_cloud_service(
                    binaries=binaries,
                    tracked_descriptor=tracked,
                    runtime_descriptor=runtime,
                    proxy_base_url="http://127.0.0.1:43210/v1",
                    downstream_api_key=secret,
                    call_timeout_ms=150_000,
                    startup_timeout_ms=30_000,
                )

            self.assertIs(actual, sentinel)
            projected = json.loads(runtime.read_text(encoding="utf-8"))
            self.assertEqual(
                projected["provider"]["base_url"],
                "http://127.0.0.1:43210/v1",
            )
            self.assertEqual(
                projected["provider"]["api_key_env"],
                "RONDO_PLAN097_DEEPSEEK_PROXY_KEY",
            )
            projected["provider"] = expected["provider"]
            self.assertEqual(projected, expected)
            self.assertNotIn(secret, runtime.read_text(encoding="utf-8"))
            arguments = start.call_args.kwargs
            self.assertEqual(
                arguments["expected_descriptor"], expected["service_descriptor"]
            )
            self.assertEqual(
                arguments["environment"]["RONDO_PLAN097_DEEPSEEK_PROXY_KEY"],
                secret,
            )

    def test_cloud_runtime_descriptor_is_write_once(self) -> None:
        tracked = (
            REPO_ROOT
            / "eval/locks/publication-critic-plan096-cloud-descriptor-v1.json"
        )
        executable = Path(sys.executable).resolve()
        binaries = RuntimeBinaries(
            codex=executable,
            real_service=executable,
            cloud_service=executable,
            probe=executable,
        )
        with tempfile.TemporaryDirectory() as temporary:
            runtime = Path(temporary) / "runtime-descriptor.json"
            runtime.write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(ServiceRuntimeError, "runtime_output_exists"):
                start_cloud_service(
                    binaries=binaries,
                    tracked_descriptor=tracked,
                    runtime_descriptor=runtime,
                    proxy_base_url="http://127.0.0.1:43210/v1",
                    downstream_api_key="temporary",
                    call_timeout_ms=150_000,
                    startup_timeout_ms=30_000,
                )

    def test_bad_announcement_terminates_the_task_owned_process_group(self) -> None:
        command = [
            sys.executable,
            "-c",
            (
                "import json,time; "
                "print(json.dumps({'protocol':'wrong'}), flush=True); "
                "time.sleep(60)"
            ),
        ]
        with self.assertRaisesRegex(ServiceRuntimeError, "announcement_mismatch"):
            service_runtime._start_service(
                backend="cloud",
                command=command,
                environment={"PATH": os.environ.get("PATH", "")},
                probe=Path(sys.executable),
                expected_argument="--expected-cloud-descriptor",
                expected_descriptor_path=Path("unused.json"),
                expected_descriptor={"identity": {}, "limits": {}},
                descriptor_sha256="a" * 64,
                call_timeout_ms=1_000,
                startup_timeout_ms=1_000,
            )


if __name__ == "__main__":
    unittest.main()
