from __future__ import annotations

import json
import fcntl
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.docker_supervisor import (  # noqa: E402
    ComposeRunContract,
    DockerMountFact,
    HostContainerContract,
    DockerOperation,
    DockerTaskIdentity,
)
from rondo_eval.runtime_bridge import (  # noqa: E402
    CommandOutput,
    DockerCliCounter,
    DockerDesktopHostReading,
    PowerShellDockerDesktopHostProbe,
    RuntimeBridgeError,
    SubprocessCommandHandle,
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
        "memory.high": f"{19 * 1024**3}\n",
        "memory.max": f"{21 * 1024**3}\n",
        "memory.swap.max": f"{5 * 1024**3}\n",
    }
    for name, value in values.items():
        (directory / name).write_text(value, encoding="ascii")
    return proc, root / "cgroup"


class WatchdogBridgeTests(unittest.TestCase):
    def _held_lock(self, root: Path):
        path = root / "rondo-cargo-build.lock"
        path.write_bytes(b"")
        path.chmod(0o600)
        handle = path.open("wb")
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return path, handle

    def test_mints_reusable_lease_and_rereads_live_counters(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = "/user.slice/rondo-build-1000-20260810-123.scope"
            proc, cgroup_root = _write_counter_tree(root, relative)
            lock_path, lock_handle = self._held_lock(root)

            with mock.patch(
                "rondo_eval.runtime_bridge._canonical_lock_path",
                return_value=lock_path,
            ):
                proof = lease_from_watchdog(
                    proc_cgroup_path=proc,
                    cgroup_fs_root=cgroup_root,
                )

            proof.lease.validate()
            self.assertTrue(proof.guard.is_held(proof.lease))
            counter = cgroup_root / relative.lstrip("/") / "memory.current"
            counter.write_text("not-a-number\n", encoding="ascii")
            self.assertFalse(proof.guard.is_held(proof.lease))
            lock_handle.close()

    def test_rejects_released_flock_limit_drift_and_environment_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = "/user.slice/rondo-build-1000-20260810-123.scope"
            proc, cgroup_root = _write_counter_tree(root, relative)
            lock_path, lock_handle = self._held_lock(root)
            with mock.patch(
                "rondo_eval.runtime_bridge._canonical_lock_path",
                return_value=lock_path,
            ):
                proof = lease_from_watchdog(proc_cgroup_path=proc, cgroup_fs_root=cgroup_root)
                lock_handle.close()
                self.assertFalse(proof.guard.is_held(proof.lease))

                lock_path, lock_handle = self._held_lock(root)
                self.addCleanup(lock_handle.close)
                directory = cgroup_root / relative.lstrip("/")
                (directory / "memory.max").write_text("1\n", encoding="ascii")
                with self.assertRaises(RuntimeBridgeError):
                    lease_from_watchdog(proc_cgroup_path=proc, cgroup_fs_root=cgroup_root)
                (directory / "memory.max").write_text(
                    f"{21 * 1024**3}\n", encoding="ascii"
                )
                with mock.patch.dict(os.environ, {"RONDO_BUILD_LOCK": "0"}):
                    with self.assertRaises(RuntimeBridgeError):
                        lease_from_watchdog(proc_cgroup_path=proc, cgroup_fs_root=cgroup_root)

    def test_refuses_missing_or_non_rondo_cgroup_and_detects_movement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            relative = "/user.slice/rondo-build-1000-20260810-123.scope"
            proc, cgroup_root = _write_counter_tree(root, relative)
            lock_path, lock_handle = self._held_lock(root)
            patcher = mock.patch(
                "rondo_eval.runtime_bridge._canonical_lock_path",
                return_value=lock_path,
            )
            patcher.start()
            self.addCleanup(patcher.stop)
            self.addCleanup(lock_handle.close)
            proof = lease_from_watchdog(proc_cgroup_path=proc, cgroup_fs_root=cgroup_root)
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
        self.pid = 4242

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

    def poll(self) -> int | None:
        return None


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
        self.assertNotIn("start_new_session", calls[0][1])
        with self.assertRaises(RuntimeBridgeError):
            runner.start(("harbor", "run"))
        self.assertEqual(len(calls), 1)

    def test_host_handle_closes_its_dedicated_process_group(self) -> None:
        process = FakeProcess()
        signals: list[int] = []

        def killpg(_pid: int, signal_number: int) -> None:
            signals.append(signal_number)
            if signal_number == 0:
                raise ProcessLookupError

        handle = SubprocessCommandHandle(
            process,
            owns_process_group=True,
            killpg=killpg,
        )

        self.assertTrue(handle.close_process_group(1.0))
        self.assertEqual(signals, [15, 0])

    def test_host_handle_reaps_exited_group_leader_before_liveness_probe(self) -> None:
        process = FakeProcess()
        reaped = False
        signals: list[int] = []

        def poll() -> int:
            nonlocal reaped
            reaped = True
            return 0

        process.poll = poll  # type: ignore[method-assign]

        def killpg(_pid: int, signal_number: int) -> None:
            signals.append(signal_number)
            if signal_number == 0 and reaped:
                raise ProcessLookupError

        handle = SubprocessCommandHandle(
            process,
            owns_process_group=True,
            killpg=killpg,
        )

        self.assertTrue(handle.close_process_group(1.0))
        self.assertEqual(signals, [15, 0])

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
        self.assertTrue(calls[0][1]["start_new_session"])


class FakeExecutor:
    def __init__(self, responses: list[str | CommandOutput | Exception]):
        self.responses = list(responses)
        self.commands: list[tuple[str, ...]] = []
        self.timeouts: list[float] = []

    def run(self, argv: tuple[str, ...], *, timeout_seconds: float) -> CommandOutput:
        self.timeouts.append(timeout_seconds)
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

    def sample(self, *, timeout_seconds: float) -> DockerDesktopHostReading:
        self.timeout_seconds = timeout_seconds
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


def _container_inspect(
    *,
    task_id: str = TASK_ID,
    security_opt: list[str] | None = None,
    network_mode: str = "rondoeval0810_default",
    networks: dict[str, object] | None = None,
    tmpfs: dict[str, str] | None = None,
) -> str:
    network_payload = networks if networks is not None else {network_mode: {}}
    return json.dumps(
        [
            {
                "Id": CONTAINER_ID,
                "Config": {
                    "User": "1000:1000",
                    "Labels": {
                        "dev.rondo.eval.task": task_id,
                        "com.docker.compose.project": "rondoeval0810",
                        "com.docker.compose.service": "main",
                    },
                },
                "HostConfig": {
                    "Privileged": False,
                    "CapAdd": None,
                    "CapDrop": None,
                    "SecurityOpt": security_opt,
                    "Memory": 100,
                    "MemorySwap": 100,
                    "PidsLimit": 2,
                    "ReadonlyRootfs": False,
                    "NetworkMode": network_mode,
                    "Tmpfs": tmpfs,
                },
                "NetworkSettings": {"Networks": network_payload},
                "Mounts": [],
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
                json.dumps([
                    str(root),
                    "Docker Engine - Community",
                    ["name=seccomp,profile=builtin"],
                ]),
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
            fact = first.task_containers[0]
            self.assertEqual(fact.user, "1000:1000")
            self.assertFalse(fact.privileged)
            self.assertEqual(fact.memory_bytes, 100)
            self.assertEqual(fact.memory_swap_bytes, 100)
            self.assertEqual(fact.pids_limit, 2)
            self.assertEqual(fact.compose_project, "rondoeval0810")
            self.assertEqual(fact.networks, ("rondoeval0810_default",))
            self.assertEqual(
                first.daemon_security_options,
                ("name=seccomp,profile=builtin",),
            )
            self.assertEqual(first.data_root, str(root))
            self.assertEqual(first.docker_system_df, second.docker_system_df)
            self.assertEqual(len(executor.commands), 12)
            self.assertTrue(all(0 < value <= 30 for value in executor.timeouts))
            expected_filter = f"label=dev.rondo.eval.task={TASK_ID}"
            self.assertEqual(executor.commands[2][5:7], ("--filter", expected_filter))
            self.assertEqual(executor.commands[3][4:6], ("--filter", expected_filter))

    def test_multi_probe_sample_shares_one_absolute_deadline(self) -> None:
        now = [0.0]

        class SlowExecutor(FakeExecutor):
            def run(self, argv, *, timeout_seconds):
                self.timeouts.append(timeout_seconds)
                self.commands.append(argv)
                response = self.responses.pop(0)
                now[0] += 2.0
                return CommandOutput(returncode=0, stdout=response)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            executor = SlowExecutor(
                [
                    _system_df(),
                    json.dumps([
                        str(root),
                        "Docker Engine - Community",
                        ["name=seccomp,profile=builtin"],
                    ]),
                    "",
                    "",
                ]
            )
            counter = DockerCliCounter(
                host_data_root=root,
                executor=executor,
                statvfs=lambda path: os.statvfs(path),
                monotonic=lambda: now[0],
                probe_timeout_seconds=5.0,
            )

            with self.assertRaises(RuntimeBridgeError):
                counter.sample(
                    identity=DockerTaskIdentity(TASK_ID),
                    operation=DockerOperation.RUN,
                )

        self.assertEqual(executor.timeouts, [5.0, 3.0, 1.0])
        self.assertEqual(len(executor.commands), 3)

    def test_normalizes_direct_none_network_nnp_and_effective_tmpfs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            counter, _ = self._native_counter(
                root,
                [
                    _system_df(),
                    json.dumps([
                        str(root),
                        "Docker Engine - Community",
                        ["name=seccomp,profile=builtin"],
                    ]),
                    json.dumps(CONTAINER_ID) + "\n",
                    "",
                    _container_inspect(
                        security_opt=["no-new-privileges=true"],
                        network_mode="none",
                        networks={"none": {}},
                        tmpfs={"/tmp": "rw,nosuid,nodev,noexec,size=64m"},
                    ),
                ],
            )

            reading = counter.sample(
                identity=DockerTaskIdentity(TASK_ID),
                operation=DockerOperation.RUN,
            )

            fact = reading.task_containers[0]
            self.assertEqual(fact.security_opt, ("no-new-privileges:true",))
            self.assertEqual(fact.network_mode, "none")
            self.assertEqual(fact.networks, ())
            self.assertEqual(
                fact.mounts,
                (
                    DockerMountFact(
                        "tmpfs",
                        "",
                        "/tmp",
                        False,
                        ("nodev", "noexec", "nosuid", "rw", "size=64m"),
                    ),
                ),
            )

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
                    json.dumps([
                        str(root),
                        "Docker Engine - Community",
                        ["name=seccomp,profile=builtin"],
                    ]),
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
                    json.dumps([
                        str(Path(second).resolve()),
                        "Docker Engine - Community",
                        ["name=seccomp,profile=builtin"],
                    ]),
                ],
            )
            with self.assertRaises(RuntimeBridgeError):
                counter.sample(
                    identity=DockerTaskIdentity(TASK_ID),
                    operation=DockerOperation.BUILD,
                )
            self.assertEqual(len(executor.commands), 2)

    def test_custom_seccomp_digest_comes_from_daemon_inspect_content(self) -> None:
        profile = '{"defaultAction":"SCMP_ACT_ERRNO","syscalls":[]}'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            responses = [
                _system_df(),
                json.dumps([
                    str(root),
                    "Docker Engine - Community",
                    ["name=seccomp,profile=builtin"],
                ]),
                json.dumps(CONTAINER_ID) + "\n",
                "",
                _container_inspect(security_opt=[f"seccomp={profile}"]),
            ]
            counter, _ = self._native_counter(root, responses)
            reading = counter.sample(
                identity=DockerTaskIdentity(TASK_ID),
                operation=DockerOperation.RUN,
            )

            self.assertEqual(
                reading.task_containers[0].seccomp_profile_sha256,
                hashlib.sha256(
                    json.dumps(
                        json.loads(profile),
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
            )

            responses[-1] = _container_inspect(
                security_opt=["seccomp=/project/self-reported.json"]
            )
            counter, _ = self._native_counter(root, responses)
            with self.assertRaises(RuntimeBridgeError):
                counter.sample(
                    identity=DockerTaskIdentity(TASK_ID),
                    operation=DockerOperation.RUN,
                )

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
                [
                    _system_df(),
                    json.dumps([
                        "/var/lib/docker",
                        "Docker Desktop",
                        ["name=seccomp,profile=builtin"],
                    ]),
                ]
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
                    json.dumps([
                        "/var/lib/docker",
                        "Docker Desktop",
                        ["name=seccomp,profile=builtin"],
                    ]),
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

    def test_compose_resources_are_selected_and_inspected_by_exact_project(self) -> None:
        network_id = "c" * 64
        project = "rondoeval0810"
        network_name = f"{project}_default"
        volume_name = f"{project}_data"
        contract = ComposeRunContract(
            container=HostContainerContract(
                user="1000:1000",
                memory_bytes=100,
                memory_swap_bytes=100,
                pids_limit=2,
                compose_project=project,
                compose_service="main",
                network_mode=network_name,
                networks=(network_name,),
                mounts=(),
            ),
            network_names=(network_name,),
            volume_names=(volume_name,),
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            responses = [
                _system_df(),
                json.dumps([
                    str(root),
                    "Docker Engine - Community",
                    ["name=seccomp,profile=builtin"],
                ]),
                json.dumps(CONTAINER_ID) + "\n",
                "",
                _container_inspect(),
                json.dumps(network_id) + "\n",
                json.dumps([
                    {
                        "Id": network_id,
                        "Name": network_name,
                        "Labels": {"com.docker.compose.project": project},
                    }
                ]),
                json.dumps(volume_name) + "\n",
                json.dumps([
                    {
                        "Name": volume_name,
                        "Labels": {"com.docker.compose.project": project},
                    }
                ]),
            ]
            counter, executor = self._native_counter(root, responses)
            reading = counter.sample(
                identity=DockerTaskIdentity(TASK_ID),
                operation=DockerOperation.HOST,
                compose_contract=contract,
            )

        self.assertEqual(reading.task_networks[0].object_id, network_id)
        self.assertEqual(reading.task_networks[0].name, network_name)
        self.assertEqual(reading.task_volumes[0].name, volume_name)
        expected_filter = f"label=com.docker.compose.project={project}"
        self.assertIn(expected_filter, executor.commands[5])
        self.assertIn(expected_filter, executor.commands[7])

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
