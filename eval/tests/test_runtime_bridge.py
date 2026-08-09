from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.docker_supervisor import DockerOperation, DockerTaskIdentity  # noqa: E402
from rondo_eval.runtime_bridge import (  # noqa: E402
    CommandOutput,
    DockerCliCounter,
    DockerDesktopHostReading,
    PowerShellDockerDesktopHostProbe,
    RuntimeBridgeError,
    SubprocessDockerCommandRunner,
    SubprocessHostCommandRunner,
    lease_from_watchdog,
)


TASK_ID = "20260810-runtime-bridge-r1"
CONTAINER_ID = "a" * 64
IMAGE_ID = "b" * 64


def _write_counter_tree(root: Path, relative: str) -> tuple[Path, Path]:
    proc = root / "proc-cgroup"
    proc.write_text(f"0::{relative}\n", encoding="utf-8")
    directory = root / "cgroup" / relative.lstrip("/")
    directory.mkdir(parents=True)
    values = {
        "cgroup.events": "populated 1\nfrozen 0\n",
        "cgroup.procs": f"{os.getpid()}\n",
        "memory.current": "1024\n",
        "memory.peak": "2048\n",
        "memory.stat": "anon 512\nfile 128\n",
        "memory.swap.current": "0\n",
        "memory.swap.peak": "0\n",
        "memory.pressure": (
            "some avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
            "full avg10=0.00 avg60=0.00 avg300=0.00 total=0\n"
        ),
        "memory.events": "low 0\nhigh 0\nmax 0\noom 0\noom_kill 0\n",
    }
    for name, value in values.items():
        (directory / name).write_text(value, encoding="ascii")
    return proc, root / "cgroup"


class WatchdogBridgeTests(unittest.TestCase):
    def test_mints_reusable_lease_and_rereads_live_counters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = "/user.slice/rondo-build-1000-20260810-123.scope"
            proc, cgroup_root = _write_counter_tree(root, relative)

            proof = lease_from_watchdog(
                proc_cgroup_path=proc,
                cgroup_fs_root=cgroup_root,
            )

            proof.lease.validate()
            self.assertTrue(proof.guard.is_held(proof.lease))
            counter = cgroup_root / relative.lstrip("/") / "memory.current"
            counter.write_text("not-a-number\n", encoding="ascii")
            self.assertFalse(proof.guard.is_held(proof.lease))

    def test_refuses_missing_or_non_rondo_cgroup_and_detects_movement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = "/user.slice/rondo-build-1000-20260810-123.scope"
            proc, cgroup_root = _write_counter_tree(root, relative)
            proof = lease_from_watchdog(
                proc_cgroup_path=proc,
                cgroup_fs_root=cgroup_root,
            )
            proc.write_text("0::/user.slice/not-rondo.scope\n", encoding="utf-8")
            self.assertFalse(proof.guard.is_held(proof.lease))

            with self.assertRaises(RuntimeBridgeError):
                lease_from_watchdog(
                    proc_cgroup_path=proc,
                    cgroup_fs_root=cgroup_root,
                )

            proc.unlink()
            with self.assertRaises(RuntimeBridgeError):
                lease_from_watchdog(
                    proc_cgroup_path=proc,
                    cgroup_fs_root=cgroup_root,
                )


class FakeProcess:
    def __init__(self) -> None:
        self.calls = 0
        self.terminated = False
        self.killed = False

    def wait(self, *, timeout: float) -> int:
        del timeout
        self.calls += 1
        if self.calls == 1:
            raise subprocess.TimeoutExpired("redacted", 1)
        return 0

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True


class SubprocessRunnerTests(unittest.TestCase):
    def test_popen_is_shell_false_silent_and_environment_is_allowlisted(self) -> None:
        process = FakeProcess()
        calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

        def fake_popen(argv, **kwargs):
            calls.append((argv, kwargs))
            return process

        runner = SubprocessDockerCommandRunner(popen=fake_popen)
        with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "must-not-cross"}, clear=False):
            handle = runner.start(("docker", "version"))

        self.assertIsNone(handle.wait(0.1))
        self.assertEqual(handle.wait(0.1), 0)
        self.assertFalse(calls[0][1]["shell"])
        self.assertIs(calls[0][1]["stdout"], subprocess.DEVNULL)
        self.assertIs(calls[0][1]["stderr"], subprocess.DEVNULL)
        self.assertNotIn("OPENAI_API_KEY", calls[0][1]["env"])
        with self.assertRaises(RuntimeBridgeError):
            runner.start(("harbor", "run"))
        self.assertEqual(len(calls), 1)

    def test_host_runner_accepts_only_exact_executable_and_explicit_environment(self) -> None:
        process = FakeProcess()
        calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

        def fake_popen(argv, **kwargs):
            calls.append((argv, kwargs))
            return process

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "harbor"
            executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            executable.chmod(0o700)
            other = root / "other"
            other.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            other.chmod(0o700)
            runner = SubprocessHostCommandRunner(
                executable=executable,
                cwd=root,
                environment={"HARBOR_TELEMETRY": "off"},
                popen=fake_popen,
            )
            with mock.patch.dict(os.environ, {"OPENAI_API_KEY": "must-not-cross"}, clear=False):
                runner.start((str(executable), "run"))
            with self.assertRaises(RuntimeBridgeError):
                runner.start((str(other), "run"))

        self.assertFalse(calls[0][1]["shell"])
        self.assertEqual(calls[0][1]["env"]["HARBOR_TELEMETRY"], "off")
        self.assertNotIn("OPENAI_API_KEY", calls[0][1]["env"])


class FakeExecutor:
    def __init__(self, responses: list[str | CommandOutput | Exception]):
        self.responses = list(responses)
        self.commands: list[tuple[str, ...]] = []

    def run(self, argv: tuple[str, ...]) -> CommandOutput:
        self.commands.append(argv)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        if isinstance(response, CommandOutput):
            return response
        return CommandOutput(returncode=0, stdout=response)


class FakeDesktopProbe:
    def __init__(self, reading: DockerDesktopHostReading):
        self.reading = reading
        self.calls = 0

    def sample(self) -> DockerDesktopHostReading:
        self.calls += 1
        return self.reading


def _system_df() -> str:
    rows = (
        {"Type": "Images", "TotalCount": "1", "Active": "1", "Size": "1GB"},
        {"Type": "Containers", "TotalCount": "1", "Active": "1", "Size": "2MB"},
        {"Type": "Local Volumes", "TotalCount": "0", "Active": "0", "Size": "0B"},
        {"Type": "Build Cache", "TotalCount": "0", "Active": "0", "Size": "0B"},
    )
    return "".join(json.dumps(row) + "\n" for row in rows)


def _container_inspect(*, task_id: str = TASK_ID) -> str:
    return json.dumps(
        [
            {
                "Id": CONTAINER_ID,
                "Config": {"Labels": {"dev.rondo.eval.task": task_id}},
                "SizeRw": 123,
            }
        ]
    )


def _image_inspect(*, task_id: str = TASK_ID) -> str:
    return json.dumps(
        [
            {
                "Id": f"sha256:{IMAGE_ID}",
                "Config": {"Labels": {"dev.rondo.eval.task": task_id}},
                "Size": 456,
            }
        ]
    )


class DockerCounterTests(unittest.TestCase):
    def _native_counter(
        self,
        root: Path,
        responses: list[str | CommandOutput | Exception],
    ) -> tuple[DockerCliCounter, FakeExecutor]:
        executor = FakeExecutor(responses)
        counter = DockerCliCounter(
            host_data_root=root,
            executor=executor,
            statvfs=lambda path: os.statvfs(path),
        )
        return counter, executor

    def test_samples_fresh_structured_facts_and_exact_task_label(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            responses = [
                _system_df(),
                json.dumps([str(root), "Docker Engine - Community"]),
                json.dumps(CONTAINER_ID) + "\n",
                json.dumps(f"sha256:{IMAGE_ID}") + "\n",
                _container_inspect(),
                _image_inspect(),
            ] * 2
            counter, executor = self._native_counter(root, responses)
            identity = DockerTaskIdentity(TASK_ID)

            first = counter.sample(identity=identity, operation=DockerOperation.RUN)
            second = counter.sample(identity=identity, operation=DockerOperation.RUN)

            self.assertEqual(first.task_bytes, 579)
            self.assertEqual(first.docker_total_bytes, 1_002_000_000)
            self.assertEqual(first.task_container_ids, (CONTAINER_ID,))
            self.assertEqual(first.task_image_ids, (IMAGE_ID,))
            self.assertEqual(first.data_root, str(root))
            self.assertEqual(first.docker_system_df, second.docker_system_df)
            self.assertEqual(len(executor.commands), 12)
            expected_filter = f"label=dev.rondo.eval.task={TASK_ID}"
            self.assertEqual(executor.commands[2][5:7], ("--filter", expected_filter))
            self.assertEqual(executor.commands[3][4:6], ("--filter", expected_filter))

    def test_rejects_malicious_output_without_echoing_it(self) -> None:
        secret = "credential-value-that-must-not-appear"
        with tempfile.TemporaryDirectory() as temporary:
            counter, _ = self._native_counter(Path(temporary).resolve(), [secret])
            with self.assertRaises(RuntimeBridgeError) as caught:
                counter.sample(
                    identity=DockerTaskIdentity(TASK_ID),
                    operation=DockerOperation.PULL,
                )
            self.assertNotIn(secret, str(caught.exception))

    def test_executor_failure_does_not_chain_sensitive_text(self) -> None:
        secret = "credential-value-that-must-not-appear"
        with tempfile.TemporaryDirectory() as temporary:
            counter, _ = self._native_counter(
                Path(temporary).resolve(),
                [RuntimeError(secret)],
            )
            with self.assertRaises(RuntimeBridgeError) as caught:
                counter.sample(
                    identity=DockerTaskIdentity(TASK_ID),
                    operation=DockerOperation.PULL,
                )
            self.assertNotIn(secret, str(caught.exception))
            self.assertIsNone(caught.exception.__cause__)

    def test_filter_is_not_trusted_when_inspected_label_is_not_exact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            counter, _ = self._native_counter(
                root,
                [
                    _system_df(),
                    json.dumps([str(root), "Docker Engine - Community"]),
                    json.dumps(CONTAINER_ID) + "\n",
                    "",
                    _container_inspect(task_id=TASK_ID + "-suffix"),
                ],
            )
            with self.assertRaises(RuntimeBridgeError):
                counter.sample(
                    identity=DockerTaskIdentity(TASK_ID),
                    operation=DockerOperation.RUN,
                )

    def test_native_host_path_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            counter, executor = self._native_counter(
                Path(first).resolve(),
                [
                    _system_df(),
                    json.dumps([str(Path(second).resolve()), "Docker Engine - Community"]),
                ],
            )
            with self.assertRaises(RuntimeBridgeError):
                counter.sample(
                    identity=DockerTaskIdentity(TASK_ID),
                    operation=DockerOperation.BUILD,
                )
            self.assertEqual(len(executor.commands), 2)

    def test_docker_desktop_requires_matching_mount_fact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            host = base / "ordinary-mount" / "data"
            host.mkdir(parents=True)
            mountinfo = base / "mountinfo"
            mountinfo.write_text(
                f"42 31 0:1 / {base / 'ordinary-mount'} rw - ext4 /dev/sdz rw\n",
                encoding="utf-8",
            )
            executor = FakeExecutor(
                [_system_df(), json.dumps(["/var/lib/docker", "Docker Desktop"])]
            )
            counter = DockerCliCounter(
                host_data_root=host,
                executor=executor,
                mountinfo_path=mountinfo,
            )
            with self.assertRaises(RuntimeBridgeError):
                counter.sample(
                    identity=DockerTaskIdentity(TASK_ID),
                    operation=DockerOperation.PULL,
                )

    def test_docker_desktop_accepts_explicit_verified_host_volume_probe(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            probe = FakeDesktopProbe(
                DockerDesktopHostReading(root, 190 * 1024**3, 70_000_000_000)
            )
            executor = FakeExecutor(
                [
                    _system_df(),
                    json.dumps(["/var/lib/docker", "Docker Desktop"]),
                    "",
                    "",
                ]
            )
            counter = DockerCliCounter(
                host_data_root=root,
                executor=executor,
                desktop_host_probe=probe,
            )

            reading = counter.sample(
                identity=DockerTaskIdentity(TASK_ID),
                operation=DockerOperation.PULL,
            )

            self.assertEqual(reading.data_root, str(root))
            self.assertEqual(reading.data_root_filesystem_free_bytes, 190 * 1024**3)
            self.assertEqual(probe.calls, 1)

    def test_powershell_probe_parses_only_non_sensitive_storage_facts(self) -> None:
        completed = mock.Mock(
            returncode=0,
            stdout='{"drive":"C","vhd_bytes":69467111424,"free_bytes":196425408512}',
        )
        with mock.patch("rondo_eval.runtime_bridge.subprocess.run", return_value=completed):
            reading = PowerShellDockerDesktopHostProbe().sample()
        self.assertEqual(reading.host_volume_root, Path("/mnt/c"))
        self.assertEqual(reading.vhd_size_bytes, 69467111424)
        self.assertEqual(reading.free_bytes, 196425408512)


if __name__ == "__main__":
    unittest.main()
