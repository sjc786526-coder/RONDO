from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.docker_supervisor import (  # noqa: E402
    DATA_ROOT_FREE_STOP_BYTES,
    COUNTER_SAMPLE_TIMEOUT_SECONDS,
    DOCKER_GROWTH_WARN_BYTES,
    DOCKER_GROWTH_STOP_BYTES,
    ComposeResourceFact,
    ComposeRunContract,
    ComposeSecretMountContract,
    DockerContainerFact,
    DockerContainerMetricFact,
    DockerImageIdentity,
    DockerCounterReading,
    DockerExecutionResult,
    FAILURE_CLEANUP_TIMEOUT_SECONDS,
    HOST_SUCCESS_TEARDOWN_GRACE_SECONDS,
    DockerLimits,
    DockerOperation,
    DockerMountFact,
    DockerSupervisionError,
    DockerSupervisor,
    DockerTaskIdentity,
    HeavyLockLease,
    HostContainerContract,
    SAMPLE_INTERVAL_SECONDS,
)
from rondo_eval.runtime_bridge import RuntimeBridgeError  # noqa: E402


IMAGE = f"example.invalid/rondo/task@sha256:{'a' * 64}"
IMAGE_ID = f"sha256:{'e' * 64}"
CONTAINER_ID = "b" * 64
OTHER_CONTAINER_ID = "c" * 64
COMPOSE_PROJECT = "rondoeval0810"
COMPOSE_NETWORK = f"{COMPOSE_PROJECT}_default"


def container_fact(container_id: str) -> DockerContainerFact:
    return DockerContainerFact(
        container_id=container_id,
        user="1000:1000",
        privileged=False,
        cap_add=(),
        cap_drop=(),
        security_opt=(),
        memory_bytes=100,
        memory_swap_bytes=100,
        pids_limit=2,
        read_only_rootfs=False,
        cgroupns_mode="private",
        network_mode=COMPOSE_NETWORK,
        networks=(COMPOSE_NETWORK,),
        mounts=(),
        compose_project=COMPOSE_PROJECT,
        compose_service="main",
        image_reference=IMAGE,
        image_id=IMAGE_ID,
    )


def reading(
    *,
    total: int = 1_000,
    task: int = 0,
    free: int = DATA_ROOT_FREE_STOP_BYTES + 1,
    containers: tuple[str, ...] = (),
    networks: tuple[ComposeResourceFact, ...] = (),
    volumes: tuple[ComposeResourceFact, ...] = (),
    vhdx: int | None = None,
    metrics: tuple[DockerContainerMetricFact, ...] = (),
) -> DockerCounterReading:
    return DockerCounterReading(
        docker_system_df={"layers_size": total, "containers_size": task},
        docker_total_bytes=total,
        task_bytes=task,
        data_root="/var/lib/docker",
        data_root_filesystem_free_bytes=free,
        docker_desktop_vhdx_bytes=vhdx,
        task_container_ids=containers,
        task_containers=tuple(container_fact(value) for value in containers),
        task_container_metrics=metrics,
        task_networks=networks,
        task_volumes=volumes,
        daemon_security_options=("name=seccomp,profile=builtin",),
    )


class FakeLockGuard:
    def __init__(self, states: list[bool] | None = None):
        self.states = list(states or [True])

    def is_held(self, lease: HeavyLockLease) -> bool:
        del lease
        if len(self.states) > 1:
            return self.states.pop(0)
        return self.states[0]


class FakeCounter:
    def __init__(self, values):
        self.values = list(values)
        self.calls: list[tuple[DockerTaskIdentity, DockerOperation]] = []

    def sample(self, *, identity, operation, compose_contract=None, deadline=None):
        del compose_contract, deadline
        self.calls.append((identity, operation))
        value = self.values.pop(0) if len(self.values) > 1 else self.values[0]
        if isinstance(value, Exception):
            raise value
        return value


class FakeHandle:
    def __init__(self, outcomes, *, group_ok=True):
        self.outcomes = list(outcomes)
        self.waits: list[float] = []
        self.terminated = 0
        self.killed = 0
        self.group_closes: list[float] = []
        self.group_ok = group_ok

    def wait(self, timeout_seconds):
        self.waits.append(timeout_seconds)
        if self.terminated or self.killed:
            return 143
        return self.outcomes.pop(0) if self.outcomes else 0

    def terminate(self):
        self.terminated += 1

    def kill(self):
        self.killed += 1

    def close_process_group(self, timeout_seconds):
        self.group_closes.append(timeout_seconds)
        return self.group_ok


class FailingWaitHandle(FakeHandle):
    def wait(self, timeout_seconds):
        self.waits.append(timeout_seconds)
        if self.terminated or self.killed:
            return 143
        raise RuntimeError("wait failed")


class FakeRunner:
    def __init__(self, handles):
        self.handles = list(handles)
        self.commands: list[tuple[str, ...]] = []

    def start(self, argv):
        self.commands.append(argv)
        return self.handles.pop(0)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class DockerSupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.identity = DockerTaskIdentity("20260810-task-a-r1")
        self.lease = HeavyLockLease("held-lock-token-123456", held=True)
        self.compose_contract = ComposeRunContract(
            container=HostContainerContract(
                user="1000:1000",
                memory_bytes=100,
                memory_swap_bytes=100,
                pids_limit=2,
                compose_project=COMPOSE_PROJECT,
                compose_service="main",
                network_mode=COMPOSE_NETWORK,
                networks=(COMPOSE_NETWORK,),
                mounts=(),
            ),
            network_names=(COMPOSE_NETWORK,),
        )

    def supervisor(
        self,
        *,
        counter,
        handles,
        lock=None,
        cleanup_runner=None,
        monotonic=None,
        sleeper=None,
        counter_sample_timeout_seconds=None,
    ):
        runner = FakeRunner(handles)
        options = dict(
            runner=runner,
            counter=counter,
            lock_guard=lock or FakeLockGuard(),
            cleanup_runner=cleanup_runner,
        )
        if monotonic is not None:
            options["monotonic"] = monotonic
        if sleeper is not None:
            options["sleeper"] = sleeper
        if counter_sample_timeout_seconds is not None:
            options["counter_sample_timeout_seconds"] = counter_sample_timeout_seconds
        supervisor = DockerSupervisor(**options)
        return supervisor, runner

    def test_refuses_before_counting_or_starting_without_shared_lock(self) -> None:
        counter = FakeCounter([reading()])
        supervisor, runner = self.supervisor(
            counter=counter,
            handles=[FakeHandle([0])],
            lock=FakeLockGuard([False]),
        )

        with self.assertRaises(DockerSupervisionError) as caught:
            supervisor.pull(self.identity, IMAGE, lease=self.lease, timeout_seconds=30)

        self.assertEqual(caught.exception.exit_code, 70)
        self.assertEqual(counter.calls, [])
        self.assertEqual(runner.commands, [])

    def test_run_is_foreground_bounded_labeled_and_sampled_every_five_seconds(self) -> None:
        handle = FakeHandle([None, None, 0])
        counter = FakeCounter(
            [
                reading(),
                reading(total=2_000, containers=(CONTAINER_ID,)),
                reading(total=3_000, containers=(CONTAINER_ID,)),
                reading(total=4_000),
            ]
        )
        supervisor, runner = self.supervisor(counter=counter, handles=[handle])
        limits = DockerLimits(
            memory_bytes=512 * 1024**2,
            memory_swap_bytes=768 * 1024**2,
            pids_limit=128,
            timeout_seconds=60,
        )

        result = supervisor.run(
            self.identity,
            IMAGE,
            ("/bin/true",),
            lease=self.lease,
            limits=limits,
        )

        argv = runner.commands[0]
        self.assertNotIn("--detach", argv)
        self.assertNotIn("-d", argv)
        self.assertIn(self.identity.container_name, argv)
        self.assertIn(self.identity.label, argv)
        self.assertEqual(
            self.identity.exact_label_filter,
            ("--filter", f"label={self.identity.label}"),
        )
        self.assertEqual(argv[argv.index("--memory") + 1], str(limits.memory_bytes))
        self.assertEqual(argv[argv.index("--memory-swap") + 1], str(limits.memory_swap_bytes))
        self.assertEqual(argv[argv.index("--pids-limit") + 1], str(limits.pids_limit))
        self.assertEqual(handle.waits, [SAMPLE_INTERVAL_SECONDS] * 3)
        self.assertEqual(
            [sample.phase for sample in result.samples],
            ["baseline", "periodic", "periodic", "final"],
        )

    def test_pull_and_build_have_pre_periodic_and_post_counters(self) -> None:
        first = FakeHandle([None, 0])
        second = FakeHandle([0])
        counter = FakeCounter([reading()] * 5)
        supervisor, runner = self.supervisor(counter=counter, handles=[first, second])

        pulled = supervisor.pull(self.identity, IMAGE, lease=self.lease, timeout_seconds=30)
        built = supervisor.build(
            self.identity,
            ".",
            "rondo-task:test",
            lease=self.lease,
            timeout_seconds=30,
        )

        self.assertEqual(
            [sample.phase for sample in pulled.samples],
            ["baseline", "periodic", "final"],
        )
        self.assertEqual(
            runner.commands[0],
            ("docker", "image", "pull", "--platform", "linux/amd64", IMAGE),
        )
        self.assertEqual([sample.phase for sample in built.samples], ["baseline", "final"])
        self.assertIn(self.identity.label, runner.commands[1])
        self.assertEqual([call[1] for call in counter.calls], [
            DockerOperation.PULL,
            DockerOperation.PULL,
            DockerOperation.PULL,
            DockerOperation.BUILD,
            DockerOperation.BUILD,
        ])

    def test_host_harness_fails_when_exact_task_container_is_never_observed(self) -> None:
        handle = FakeHandle([None, 0])
        counter = FakeCounter([reading(), reading(), reading()])
        cleanup_runner = FakeRunner([])
        supervisor, runner = self.supervisor(
            counter=counter,
            handles=[handle],
            cleanup_runner=cleanup_runner,
        )

        with self.assertRaises(DockerSupervisionError) as caught:
            supervisor.supervise_host_command(
                self.identity,
                ("/project/eval/.venv/bin/harbor", "run", "--help"),
                lease=self.lease,
                timeout_seconds=30,
                compose_contract=self.compose_contract,
            )

        self.assertIn("never observed", caught.exception.reason)
        self.assertEqual(handle.waits, [SAMPLE_INTERVAL_SECONDS] * 2)
        self.assertEqual(
            [call[1] for call in counter.calls],
            [DockerOperation.HOST] * 3 + [DockerOperation.CLEANUP] * 2,
        )
        self.assertEqual(runner.commands[0][0], "/project/eval/.venv/bin/harbor")
        with self.assertRaises(DockerSupervisionError):
            supervisor.supervise_host_command(
                self.identity,
                ("/usr/bin/docker", "ps"),
                lease=self.lease,
                timeout_seconds=30,
                compose_contract=self.compose_contract,
            )

    def test_host_harness_rejects_effective_runtime_drift(self) -> None:
        drifted = replace(container_fact(CONTAINER_ID), privileged=True)
        counter = FakeCounter(
            [
                reading(),
                replace(
                    reading(containers=(CONTAINER_ID,)),
                    task_containers=(drifted,),
                ),
                reading(containers=(CONTAINER_ID,)),
                reading(),
            ]
        )
        cleanup_runner = FakeRunner([FakeHandle([0])])
        supervisor, _ = self.supervisor(
            counter=counter,
            handles=[FakeHandle([0])],
            cleanup_runner=cleanup_runner,
        )

        with self.assertRaises(DockerSupervisionError) as caught:
            supervisor.supervise_host_command(
                self.identity,
                ("/project/eval/.venv/bin/harbor", "run"),
                lease=self.lease,
                timeout_seconds=30,
                compose_contract=self.compose_contract,
            )

        self.assertIn("effective Docker container state", caught.exception.reason)
        self.assertEqual(
            cleanup_runner.commands,
            [("docker", "container", "rm", "--force", CONTAINER_ID)],
        )

    def test_host_cleanup_covers_exact_compose_network_and_volume(self) -> None:
        network = ComposeResourceFact("network", "d" * 64, COMPOSE_NETWORK)
        volume_name = f"{COMPOSE_PROJECT}_data"
        volume = ComposeResourceFact("volume", volume_name, volume_name)
        contract = replace(self.compose_contract, volume_names=(volume_name,))
        active = reading(
            containers=(CONTAINER_ID,),
            networks=(network,),
            volumes=(volume,),
        )
        cleanup_runner = FakeRunner([FakeHandle([0]), FakeHandle([0]), FakeHandle([0])])
        supervisor, _ = self.supervisor(
            counter=FakeCounter([reading(), active, active, reading()]),
            handles=[FakeHandle([7])],
            cleanup_runner=cleanup_runner,
        )

        result = supervisor.supervise_host_command(
            self.identity,
            ("/project/eval/.venv/bin/harbor", "run"),
            lease=self.lease,
            timeout_seconds=30,
            compose_contract=contract,
        )

        self.assertEqual(result.returncode, 7)
        self.assertEqual(
            cleanup_runner.commands,
            [
                ("docker", "container", "rm", "--force", CONTAINER_ID),
                ("docker", "network", "rm", network.object_id),
                ("docker", "volume", "rm", volume.name),
            ],
        )
        self.assertEqual(result.samples[-1].phase, "cleanup_verified")

    def test_host_process_group_must_be_verified_before_final_sampling(self) -> None:
        cleanup_runner = FakeRunner([FakeHandle([0])])
        handle = FakeHandle([0], group_ok=False)
        supervisor, _ = self.supervisor(
            counter=FakeCounter(
                [reading(), reading(containers=(CONTAINER_ID,)), reading()]
            ),
            handles=[handle],
            cleanup_runner=cleanup_runner,
        )

        with self.assertRaises(DockerSupervisionError) as caught:
            supervisor.supervise_host_command(
                self.identity,
                ("/project/eval/.venv/bin/harbor", "run"),
                lease=self.lease,
                timeout_seconds=30,
                compose_contract=self.compose_contract,
            )

        self.assertIn("process group teardown", caught.exception.reason)
        self.assertIn("process-group cleanup was not verified", caught.exception.reason)
        self.assertEqual(len(handle.group_closes), 2)

    def test_host_harness_requires_a_separate_docker_cleanup_runner(self) -> None:
        supervisor, runner = self.supervisor(
            counter=FakeCounter([reading()]),
            handles=[FakeHandle([0])],
        )

        with self.assertRaises(DockerSupervisionError):
            supervisor.supervise_host_command(
                self.identity,
                ("/project/eval/.venv/bin/harbor", "run"),
                lease=self.lease,
                timeout_seconds=30,
                compose_contract=self.compose_contract,
            )

        self.assertEqual(runner.commands, [])

        same_runner = FakeRunner([FakeHandle([0])])
        supervisor = DockerSupervisor(
            runner=same_runner,
            cleanup_runner=same_runner,
            counter=FakeCounter([reading()]),
            lock_guard=FakeLockGuard(),
        )
        with self.assertRaises(DockerSupervisionError):
            supervisor.supervise_host_command(
                self.identity,
                ("/project/eval/.venv/bin/harbor", "run"),
                lease=self.lease,
                timeout_seconds=30,
                compose_contract=self.compose_contract,
            )
        self.assertEqual(same_runner.commands, [])

    def test_successful_host_exit_allows_natural_daemon_teardown(self) -> None:
        clock = FakeClock()
        cleanup_runner = FakeRunner([])
        counter = FakeCounter(
            [
                reading(),
                reading(containers=(CONTAINER_ID,)),
                reading(
                    total=1_000 + DOCKER_GROWTH_WARN_BYTES,
                    containers=(CONTAINER_ID,),
                ),
                reading(),
            ]
        )
        supervisor, host_runner = self.supervisor(
            counter=counter,
            handles=[FakeHandle([0])],
            cleanup_runner=cleanup_runner,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )

        result = supervisor.supervise_host_command(
            self.identity,
            ("/project/eval/.venv/bin/harbor", "run"),
            lease=self.lease,
            timeout_seconds=30,
            compose_contract=self.compose_contract,
        )

        self.assertEqual(len(host_runner.commands), 1)
        self.assertEqual(cleanup_runner.commands, [])
        self.assertEqual(clock.sleeps, [SAMPLE_INTERVAL_SECONDS] * 2)
        self.assertEqual(len(result.warnings), 1)
        self.assertEqual(
            [sample.phase for sample in result.samples],
            ["baseline", "final", "teardown_grace", "cleanup_verified"],
        )

    def test_successful_host_exit_cleans_after_bounded_teardown_grace(self) -> None:
        clock = FakeClock()
        cleanup_handle = FakeHandle([0])
        cleanup_runner = FakeRunner([cleanup_handle])
        counter = FakeCounter(
            [reading(), *[reading(containers=(CONTAINER_ID,))] * 7, reading()]
        )
        supervisor, _ = self.supervisor(
            counter=counter,
            handles=[FakeHandle([0])],
            cleanup_runner=cleanup_runner,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )

        result = supervisor.supervise_host_command(
            self.identity,
            ("/project/eval/.venv/bin/harbor", "run"),
            lease=self.lease,
            timeout_seconds=60,
            compose_contract=self.compose_contract,
        )

        self.assertEqual(
            clock.sleeps,
            [SAMPLE_INTERVAL_SECONDS]
            * int(HOST_SUCCESS_TEARDOWN_GRACE_SECONDS / SAMPLE_INTERVAL_SECONDS),
        )
        self.assertEqual(
            cleanup_runner.commands,
            [("docker", "container", "rm", "--force", CONTAINER_ID)],
        )
        self.assertEqual(
            cleanup_handle.waits,
            [FAILURE_CLEANUP_TIMEOUT_SECONDS - SAMPLE_INTERVAL_SECONDS],
        )
        self.assertEqual(result.samples[-2].phase, "post_stop")
        self.assertEqual(result.samples[-1].phase, "cleanup_verified")

    def test_hung_cleanup_is_stopped_and_reaped_within_one_deadline(self) -> None:
        clock = FakeClock()

        class AdvancingCleanupCounter(FakeCounter):
            def sample(self, **kwargs):
                value = super().sample(**kwargs)
                if kwargs["operation"] is DockerOperation.CLEANUP:
                    clock.now += SAMPLE_INTERVAL_SECONDS
                return value

        class HungCleanupHandle(FakeHandle):
            def __init__(self) -> None:
                super().__init__([])
                self.wait_states: list[tuple[int, int]] = []

            def wait(self, timeout_seconds):
                self.waits.append(timeout_seconds)
                self.wait_states.append((self.terminated, self.killed))
                clock.now += timeout_seconds
                return None

        cleanup_handle = HungCleanupHandle()
        counter = AdvancingCleanupCounter(
            [
                reading(),
                reading(containers=(CONTAINER_ID,)),
                reading(containers=(CONTAINER_ID,)),
            ]
        )
        supervisor, _ = self.supervisor(
            counter=counter,
            handles=[FakeHandle([7])],
            cleanup_runner=FakeRunner([cleanup_handle]),
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )

        with self.assertRaises(DockerSupervisionError) as caught:
            supervisor.supervise_host_command(
                self.identity,
                ("/project/eval/.venv/bin/harbor", "run"),
                lease=self.lease,
                timeout_seconds=60,
                compose_contract=self.compose_contract,
            )

        self.assertIn("cleanup was not verified", caught.exception.reason)
        self.assertEqual(clock.now, FAILURE_CLEANUP_TIMEOUT_SECONDS)
        self.assertEqual(
            sum(cleanup_handle.waits),
            FAILURE_CLEANUP_TIMEOUT_SECONDS - SAMPLE_INTERVAL_SECONDS,
        )
        self.assertEqual(cleanup_handle.terminated, 1)
        self.assertEqual(cleanup_handle.killed, 1)
        self.assertEqual(
            cleanup_handle.wait_states,
            [(0, 0), (1, 0), (1, 1)],
        )

    def test_nonzero_host_exit_skips_grace_and_cleans_immediately(self) -> None:
        clock = FakeClock()
        cleanup_runner = FakeRunner([FakeHandle([0])])
        counter = FakeCounter(
            [
                reading(),
                reading(containers=(CONTAINER_ID,)),
                reading(containers=(CONTAINER_ID,)),
                reading(),
            ]
        )
        supervisor, _ = self.supervisor(
            counter=counter,
            handles=[FakeHandle([7])],
            cleanup_runner=cleanup_runner,
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )

        result = supervisor.supervise_host_command(
            self.identity,
            ("/project/eval/.venv/bin/harbor", "run"),
            lease=self.lease,
            timeout_seconds=30,
            compose_contract=self.compose_contract,
        )

        self.assertEqual(result.returncode, 7)
        self.assertEqual(clock.sleeps, [])
        self.assertEqual(
            cleanup_runner.commands,
            [("docker", "container", "rm", "--force", CONTAINER_ID)],
        )

    def test_success_grace_threshold_fails_immediately_and_cleans(self) -> None:
        cases = (
            (
                "growth",
                reading(
                    task=DOCKER_GROWTH_STOP_BYTES,
                    containers=(CONTAINER_ID,),
                ),
                "60 GB stop threshold",
            ),
            (
                "host-free",
                reading(
                    free=DATA_ROOT_FREE_STOP_BYTES - 1,
                    containers=(CONTAINER_ID,),
                ),
                "less than 80 GiB free",
            ),
        )
        for name, dangerous_reading, expected_reason in cases:
            with self.subTest(name=name):
                clock = FakeClock()
                host_handle = FakeHandle([0])
                cleanup_runner = FakeRunner([FakeHandle([0])])
                counter = FakeCounter(
                    [
                        reading(),
                        reading(containers=(CONTAINER_ID,)),
                        dangerous_reading,
                        reading(containers=(CONTAINER_ID,)),
                        reading(),
                    ]
                )
                supervisor, _ = self.supervisor(
                    counter=counter,
                    handles=[host_handle],
                    cleanup_runner=cleanup_runner,
                    monotonic=clock.monotonic,
                    sleeper=clock.sleep,
                )

                with self.assertRaises(DockerSupervisionError) as caught:
                    supervisor.supervise_host_command(
                        self.identity,
                        ("/project/eval/.venv/bin/harbor", "run"),
                        lease=self.lease,
                        timeout_seconds=60,
                        compose_contract=self.compose_contract,
                    )

                self.assertEqual(clock.sleeps, [SAMPLE_INTERVAL_SECONDS])
                self.assertEqual(host_handle.terminated, 0)
                self.assertEqual(len(host_handle.group_closes), 1)
                self.assertIn(expected_reason, caught.exception.reason)
                self.assertEqual(caught.exception.samples[-1].phase, "cleanup_verified")

    def test_success_grace_lock_or_counter_failure_does_not_wait(self) -> None:
        cases = (
            (
                "lock",
                FakeCounter(
                    [
                        reading(),
                        reading(containers=(CONTAINER_ID,)),
                        reading(containers=(CONTAINER_ID,)),
                        reading(),
                    ]
                ),
                FakeLockGuard([True, True, True, True, True, True, False]),
                0,
            ),
            (
                "counter",
                FakeCounter(
                    [
                        reading(),
                        reading(containers=(CONTAINER_ID,)),
                        OSError("counter unavailable"),
                        reading(containers=(CONTAINER_ID,)),
                        reading(),
                    ]
                ),
                FakeLockGuard(),
                1,
            ),
        )
        for name, counter, guard, expected_sleeps in cases:
            with self.subTest(name=name):
                clock = FakeClock()
                cleanup_runner = FakeRunner([FakeHandle([0])])
                supervisor, _ = self.supervisor(
                    counter=counter,
                    handles=[FakeHandle([0])],
                    cleanup_runner=cleanup_runner,
                    lock=guard,
                    monotonic=clock.monotonic,
                    sleeper=clock.sleep,
                )

                with self.assertRaises(DockerSupervisionError) as caught:
                    supervisor.supervise_host_command(
                        self.identity,
                        ("/project/eval/.venv/bin/harbor", "run"),
                        lease=self.lease,
                        timeout_seconds=60,
                        compose_contract=self.compose_contract,
                    )

                self.assertEqual(
                    clock.sleeps,
                    [SAMPLE_INTERVAL_SECONDS] * expected_sleeps,
                )
                self.assertEqual(caught.exception.samples[-1].phase, "cleanup_verified")
                self.assertEqual(
                    cleanup_runner.commands,
                    [("docker", "container", "rm", "--force", CONTAINER_ID)],
                )

    def test_successful_direct_run_reuses_docker_runner_for_cleanup(self) -> None:
        counter = FakeCounter(
            [
                reading(),
                reading(containers=(CONTAINER_ID,)),
                reading(containers=(CONTAINER_ID,)),
                reading(),
            ]
        )
        supervisor, runner = self.supervisor(
            counter=counter,
            handles=[FakeHandle([0]), FakeHandle([0])],
        )

        result = supervisor.run(
            self.identity,
            IMAGE,
            (),
            lease=self.lease,
            limits=DockerLimits(100, 100, 2, 30),
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            runner.commands[-1],
            ("docker", "container", "rm", "--force", CONTAINER_ID),
        )

    def test_frozen_binary_version_probe_is_fixed_readonly_and_supervised(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "rondo"
            binary.write_bytes(b"frozen-rondo-binary")
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            counter = FakeCounter([reading(), reading()])
            supervisor, runner = self.supervisor(
                counter=counter,
                handles=[FakeHandle([0])],
            )
            limits = DockerLimits(512 * 1024**2, 768 * 1024**2, 64, 30)

            result = supervisor.run_frozen_binary_version(
                self.identity,
                IMAGE,
                binary,
                digest,
                lease=self.lease,
                limits=limits,
            )

        argv = runner.commands[0]
        self.assertEqual(result.returncode, 0)
        self.assertIn(self.identity.label, argv)
        self.assertEqual(argv[argv.index("--memory") + 1], str(limits.memory_bytes))
        self.assertEqual(
            argv[argv.index("--memory-swap") + 1],
            str(limits.memory_swap_bytes),
        )
        self.assertEqual(argv[argv.index("--pids-limit") + 1], str(limits.pids_limit))
        self.assertEqual(argv[argv.index("--network") + 1], "none")
        self.assertIn("--read-only", argv)
        mount = argv[argv.index("--mount") + 1]
        self.assertEqual(
            mount,
            f"type=bind,source={binary},"
            "target=/opt/rondo-eval/bin/frozen-agent,readonly",
        )
        entrypoint = argv[argv.index("--entrypoint") + 1]
        self.assertEqual(entrypoint, "/opt/rondo-eval/bin/frozen-agent")
        self.assertEqual(argv[-2:], (IMAGE, "--version"))
        self.assertEqual(
            [sample.phase for sample in result.samples],
            ["baseline", "final"],
        )

    def test_frozen_binary_version_probe_rejects_unfrozen_or_unsafe_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / "rondo"
            binary.write_bytes(b"frozen-rondo-binary")
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            symlink = root / "rondo-link"
            symlink.symlink_to(binary)
            comma = root / "rondo,evil"
            comma.write_bytes(binary.read_bytes())
            control = root / "rondo\ncontrol"
            control.write_bytes(binary.read_bytes())
            supervisor, runner = self.supervisor(
                counter=FakeCounter([reading()]),
                handles=[FakeHandle([0])],
            )
            limits = DockerLimits(100, 100, 2, 30)
            cases = (
                (binary, "0" * 64, IMAGE),
                (Path("relative-rondo"), digest, IMAGE),
                (symlink, digest, IMAGE),
                (root, digest, IMAGE),
                (comma, digest, IMAGE),
                (control, digest, IMAGE),
                (binary, digest, "example.invalid/rondo/task:latest"),
            )

            for host_binary, expected, image in cases:
                with self.subTest(host_binary=host_binary, image=image):
                    with self.assertRaises(DockerSupervisionError):
                        supervisor.run_frozen_binary_version(
                            self.identity,
                            image,
                            host_binary,
                            expected,
                            lease=self.lease,
                            limits=limits,
                        )

        self.assertEqual(runner.commands, [])

    def test_frozen_binary_version_probe_inherits_stop_and_exact_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "rondo"
            binary.write_bytes(b"frozen-rondo-binary")
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            main_handle = FakeHandle([None])
            runner = FakeRunner([main_handle, FakeHandle([0])])
            counter = FakeCounter(
                [
                    reading(),
                    reading(
                        task=DOCKER_GROWTH_STOP_BYTES,
                        containers=(CONTAINER_ID,),
                    ),
                    reading(containers=(CONTAINER_ID,)),
                    reading(),
                ]
            )
            supervisor = DockerSupervisor(
                runner=runner,
                counter=counter,
                lock_guard=FakeLockGuard(),
            )

            with self.assertRaises(DockerSupervisionError) as caught:
                supervisor.run_frozen_binary_version(
                    self.identity,
                    IMAGE,
                    binary,
                    digest,
                    lease=self.lease,
                    limits=DockerLimits(100, 100, 2, 30),
                )

        self.assertEqual(main_handle.terminated, 1)
        self.assertEqual(
            runner.commands[-1],
            ("docker", "container", "rm", "--force", CONTAINER_ID),
        )
        self.assertEqual(caught.exception.samples[-1].phase, "cleanup_verified")

    def test_warns_at_40_gb_without_stopping(self) -> None:
        counter = FakeCounter(
            [reading(), reading(total=1_000 + DOCKER_GROWTH_WARN_BYTES)]
        )
        supervisor, _ = self.supervisor(counter=counter, handles=[FakeHandle([0])])

        result = supervisor.pull(self.identity, IMAGE, lease=self.lease, timeout_seconds=30)

        self.assertEqual(len(result.warnings), 1)
        self.assertEqual(result.samples[-1].docker_growth_bytes, DOCKER_GROWTH_WARN_BYTES)

    def test_desktop_vhdx_growth_participates_in_warning_and_stop_gates(self) -> None:
        warning_supervisor, _ = self.supervisor(
            counter=FakeCounter(
                [
                    reading(vhdx=1_000),
                    reading(vhdx=1_000 + DOCKER_GROWTH_WARN_BYTES),
                ]
            ),
            handles=[FakeHandle([0])],
        )
        result = warning_supervisor.pull(
            self.identity, IMAGE, lease=self.lease, timeout_seconds=30
        )
        self.assertEqual(result.samples[-1].docker_desktop_vhdx_growth_bytes, DOCKER_GROWTH_WARN_BYTES)
        self.assertEqual(len(result.warnings), 1)

        stop_handle = FakeHandle([None])
        stop_supervisor, _ = self.supervisor(
            counter=FakeCounter(
                [
                    reading(vhdx=1_000),
                    reading(vhdx=1_000 + DOCKER_GROWTH_STOP_BYTES),
                    reading(vhdx=1_000),
                ]
            ),
            handles=[stop_handle],
        )
        with self.assertRaises(DockerSupervisionError):
            stop_supervisor.pull(
                self.identity, IMAGE, lease=self.lease, timeout_seconds=30
            )
        self.assertEqual(stop_handle.terminated, 1)

    def test_counter_probe_cannot_overrun_absolute_command_deadline(self) -> None:
        clock = FakeClock()

        class AdvancingCounter(FakeCounter):
            def __init__(self):
                super().__init__([reading(), reading(), reading(), reading()])
                self.advances = [0.0, 31.0, 0.0, 0.0]

            def sample(self, **kwargs):
                value = super().sample(**kwargs)
                clock.now += self.advances.pop(0)
                return value

        handle = FakeHandle([None])
        supervisor, _ = self.supervisor(
            counter=AdvancingCounter(),
            handles=[handle],
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )

        with self.assertRaises(DockerSupervisionError) as caught:
            supervisor.pull(self.identity, IMAGE, lease=self.lease, timeout_seconds=30)

        self.assertIn("absolute deadline", caught.exception.reason)
        self.assertEqual(handle.terminated, 1)

    def test_counter_failure_preserves_structured_probe_diagnostic(self) -> None:
        failure = RuntimeBridgeError(
            "Docker storage fact command failed",
            failed_probe="docker_system_df",
            probe_timings_ms=(("docker_system_df", 30000),),
        )
        supervisor, runner = self.supervisor(
            counter=FakeCounter([failure]),
            handles=[],
        )

        with self.assertRaises(DockerSupervisionError) as caught:
            supervisor.pull(
                self.identity,
                IMAGE,
                lease=self.lease,
                timeout_seconds=60,
            )

        self.assertEqual(caught.exception.reason, "Docker storage fact command failed")
        self.assertEqual(caught.exception.failed_probe, "docker_system_df")
        self.assertEqual(
            caught.exception.probe_timings_ms,
            (("docker_system_df", 30000),),
        )
        self.assertEqual(runner.commands, [])

    def test_complete_counter_round_may_exceed_sampling_interval(self) -> None:
        clock = FakeClock()

        class BoundedCounter(FakeCounter):
            def __init__(self):
                super().__init__([reading(), reading()])
                self.budgets: list[float] = []

            def sample(self, **kwargs):
                self.budgets.append(kwargs["deadline"] - clock.now)
                clock.now += 6.0
                return super().sample(**kwargs)

        counter = BoundedCounter()
        supervisor, _ = self.supervisor(
            counter=counter,
            handles=[FakeHandle([0])],
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )

        result = supervisor.pull(
            self.identity,
            IMAGE,
            lease=self.lease,
            timeout_seconds=60,
        )

        self.assertEqual(
            [sample.phase for sample in result.samples],
            ["baseline", "final"],
        )
        self.assertEqual(
            counter.budgets,
            [COUNTER_SAMPLE_TIMEOUT_SECONDS, COUNTER_SAMPLE_TIMEOUT_SECONDS],
        )

    def test_counter_round_uses_configured_bounded_timeout(self) -> None:
        clock = FakeClock()

        class BoundedCounter(FakeCounter):
            def __init__(self):
                super().__init__([reading(), reading()])
                self.budgets: list[float] = []

            def sample(self, **kwargs):
                self.budgets.append(kwargs["deadline"] - clock.now)
                return super().sample(**kwargs)

        counter = BoundedCounter()
        supervisor, _ = self.supervisor(
            counter=counter,
            handles=[FakeHandle([0])],
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
            counter_sample_timeout_seconds=60.0,
        )

        supervisor.pull(
            self.identity,
            IMAGE,
            lease=self.lease,
            timeout_seconds=120,
        )

        self.assertEqual(counter.budgets, [60.0, 60.0])

    def test_each_counter_round_gets_short_deadline_bounded_by_global_deadline(self) -> None:
        for global_timeout, expected_budget in (
            (60, COUNTER_SAMPLE_TIMEOUT_SECONDS),
            (3, 3.0),
        ):
            with self.subTest(global_timeout=global_timeout):
                clock = FakeClock()

                class SlowCounter(FakeCounter):
                    def __init__(self):
                        super().__init__([reading()])
                        self.budgets: list[float] = []

                    def sample(self, **kwargs):
                        deadline = kwargs["deadline"]
                        self.budgets.append(deadline - clock.now)
                        clock.now += self.budgets[-1] + 0.1
                        return super().sample(**kwargs)

                counter = SlowCounter()
                supervisor, runner = self.supervisor(
                    counter=counter,
                    handles=[FakeHandle([0])],
                    monotonic=clock.monotonic,
                    sleeper=clock.sleep,
                )

                with self.assertRaises(DockerSupervisionError) as caught:
                    supervisor.pull(
                        self.identity,
                        IMAGE,
                        lease=self.lease,
                        timeout_seconds=global_timeout,
                    )

                self.assertIn("counter probe exceeded", caught.exception.reason)
                self.assertEqual(counter.budgets, [expected_budget])
                self.assertEqual(runner.commands, [])

    def test_counter_round_finishing_at_30_second_deadline_fails_closed(self) -> None:
        clock = FakeClock()

        class BoundaryCounter(FakeCounter):
            def sample(self, **kwargs):
                self.deadline = kwargs["deadline"]
                clock.now += COUNTER_SAMPLE_TIMEOUT_SECONDS
                return super().sample(**kwargs)

        counter = BoundaryCounter([reading()])
        supervisor, runner = self.supervisor(
            counter=counter,
            handles=[],
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )

        with self.assertRaisesRegex(
            DockerSupervisionError,
            "counter probe exceeded",
        ):
            supervisor.pull(
                self.identity,
                IMAGE,
                lease=self.lease,
                timeout_seconds=60,
            )

        self.assertEqual(counter.deadline, COUNTER_SAMPLE_TIMEOUT_SECONDS)
        self.assertEqual(runner.commands, [])

    def test_seccomp_contract_rejects_unsafe_modes_and_binds_profile_digest(self) -> None:
        with self.assertRaises(DockerSupervisionError):
            replace(
                self.compose_contract.container,
                security_opt=("seccomp=unconfined",),
            ).validate()
        with self.assertRaises(DockerSupervisionError):
            replace(
                self.compose_contract.container,
                cap_add=("SYS_ADMIN",),
            ).validate()

        profile_payload = '{"defaultAction":"SCMP_ACT_ERRNO","syscalls":[]}'
        profile_digest = hashlib.sha256(profile_payload.encode()).hexdigest()
        custom = replace(
            self.compose_contract.container,
            seccomp_profile_sha256=profile_digest,
        )
        custom.validate()
        custom.validate_observation(
            replace(
                container_fact(CONTAINER_ID),
                security_opt=(f"seccomp={profile_payload}",),
                seccomp_profile_sha256=profile_digest,
            ),
            ("name=seccomp,profile=builtin",),
        )

    def test_host_contract_binds_daemon_image_identity(self) -> None:
        contract = replace(
            self.compose_contract.container,
            image_reference=IMAGE,
            image_id=IMAGE_ID,
            require_image_identity=True,
        )
        contract.validate_observation(
            container_fact(CONTAINER_ID),
            ("name=seccomp,profile=builtin",),
        )
        with self.assertRaises(DockerSupervisionError) as caught:
            contract.validate_observation(
                replace(container_fact(CONTAINER_ID), image_id=f"sha256:{'f' * 64}"),
                ("name=seccomp,profile=builtin",),
            )
        self.assertIn("image_id", caught.exception.reason)

    def test_image_identity_preflight_is_lock_guarded_and_bounded(self) -> None:
        class ResolvingCounter(FakeCounter):
            def __init__(self):
                super().__init__([reading()])
                self.deadlines = []

            def resolve_image_identity(self, image_reference, *, deadline=None):
                self.deadlines.append(deadline)
                return DockerImageIdentity(image_reference, IMAGE_ID)

        clock = FakeClock()
        counter = ResolvingCounter()
        supervisor, runner = self.supervisor(
            counter=counter,
            handles=[],
            monotonic=clock.monotonic,
            sleeper=clock.sleep,
        )
        resolved = supervisor.resolve_image_identity(
            self.identity,
            IMAGE,
            lease=self.lease,
            timeout_seconds=30,
        )
        self.assertEqual(resolved.image_id, IMAGE_ID)
        self.assertEqual(counter.deadlines, [COUNTER_SAMPLE_TIMEOUT_SECONDS])
        self.assertEqual(runner.commands, [])

    def test_paid_container_metrics_are_required_and_projected(self) -> None:
        contract = replace(
            self.compose_contract,
            container=replace(
                self.compose_contract.container,
                require_container_metrics=True,
            ),
        )
        metric = DockerContainerMetricFact(CONTAINER_ID, 1_250_000, 456_789)
        counter = FakeCounter(
            [
                reading(vhdx=100),
                reading(vhdx=101, containers=(CONTAINER_ID,), metrics=(metric,)),
                reading(vhdx=101),
            ]
        )
        supervisor, _ = self.supervisor(
            counter=counter,
            handles=[FakeHandle([None, 0])],
            cleanup_runner=FakeRunner([]),
        )
        result = supervisor.supervise_host_command(
            self.identity,
            ("/project/eval/.venv/bin/harbor", "trials", "start"),
            lease=self.lease,
            timeout_seconds=30,
            compose_contract=contract,
        )
        self.assertIsNotNone(result.container_metrics)
        assert result.container_metrics is not None
        self.assertEqual(result.container_metrics.cpu_usage_seconds, 1.25)
        self.assertEqual(result.container_metrics.peak_memory_bytes, 456_789)
        self.assertEqual(result.image_identity, DockerImageIdentity(IMAGE, IMAGE_ID))
        assert result.effective_seccomp is not None
        self.assertEqual(result.effective_seccomp.profile_kind, "builtin")
        receipt = result.receipt()
        self.assertEqual(receipt["cleanup"], "verified_empty")
        self.assertEqual(receipt["metrics"]["peak_memory"], 456_789)
        self.assertEqual(receipt["container"]["user"], "1000:1000")

        with self.assertRaises(DockerSupervisionError):
            DockerSupervisor._validate_host_reading(
                reading(containers=(CONTAINER_ID,)), contract, samples=()
            )

    def test_container_metrics_require_effective_private_cgroup_namespace(self) -> None:
        contract = replace(
            self.compose_contract.container,
            require_container_metrics=True,
        )
        contract.validate_observation(
            container_fact(CONTAINER_ID),
            ("name=seccomp,profile=builtin",),
        )
        for mode in ("host", "default", ""):
            with self.subTest(mode=mode), self.assertRaises(DockerSupervisionError):
                contract.validate_observation(
                    replace(container_fact(CONTAINER_ID), cgroupns_mode=mode),
                    ("name=seccomp,profile=builtin",),
                )

    def test_result_projects_vhdx_image_and_custom_seccomp_evidence(self) -> None:
        profile_digest = "f" * 64
        fact = replace(
            container_fact(CONTAINER_ID),
            security_opt=("seccomp={}",),
            seccomp_profile_sha256=profile_digest,
        )
        baseline = reading(vhdx=1_000)
        samples = (
            DockerSupervisor._make_sample("baseline", baseline, baseline),
            DockerSupervisor._make_sample(
                "periodic",
                baseline,
                replace(
                    reading(vhdx=1_500, containers=(CONTAINER_ID,)),
                    task_containers=(fact,),
                ),
            ),
            DockerSupervisor._make_sample(
                "final", baseline, reading(vhdx=1_200)
            ),
        )
        contract = replace(
            self.compose_contract,
            container=replace(
                self.compose_contract.container,
                image_reference=IMAGE,
                image_id=IMAGE_ID,
                require_image_identity=True,
            ),
        )
        image, vhdx, metrics, seccomp = DockerSupervisor._result_durable_evidence(
            contract, samples
        )
        self.assertEqual(image, DockerImageIdentity(IMAGE, IMAGE_ID))
        assert vhdx is not None
        self.assertEqual(vhdx.baseline_bytes, 1_000)
        self.assertEqual(vhdx.peak_bytes, 1_500)
        self.assertEqual(vhdx.final_bytes, 1_200)
        self.assertEqual(vhdx.peak_growth_bytes, 500)
        self.assertIsNone(metrics)
        assert seccomp is not None
        self.assertEqual(seccomp.profile_kind, "custom")
        self.assertEqual(seccomp.profile_sha256, profile_digest)
        result = DockerExecutionResult(
            operation=DockerOperation.HOST,
            argv=("harbor",),
            returncode=0,
            samples=(*samples[:-1], replace(samples[-1], phase="cleanup_verified")),
            warnings=(),
            image_identity=image,
            desktop_vhdx=vhdx,
            container_metrics=metrics,
            effective_seccomp=seccomp,
        )
        receipt = result.oracle_receipt()
        self.assertEqual(receipt["image"]["reference"], IMAGE)
        self.assertEqual(receipt["cleanup"], "verified_empty")
        self.assertNotIn("metrics", receipt)
        with self.assertRaises(DockerSupervisionError):
            result.receipt()

    def test_compose_secret_allows_exactly_one_dynamic_source_mount(self) -> None:
        secret = DockerMountFact(
            "bind", "/tmp/compose-123/rondo_eval_provider_api_key",
            "/run/secrets/rondo_eval_provider_api_key", True,
        )
        contract = replace(
            self.compose_contract.container,
            compose_secret_mount=ComposeSecretMountContract(
                destination="/run/secrets/rondo_eval_provider_api_key",
                source_basename="rondo_eval_provider_api_key",
            ),
        )
        contract.validate_observation(
            replace(container_fact(CONTAINER_ID), mounts=(secret,)),
            ("name=seccomp,profile=builtin",),
        )
        wrong_secret = replace(
            secret,
            source="/tmp/compose-123/generated-secret-name",
        )
        with self.assertRaises(DockerSupervisionError) as caught:
            contract.validate_observation(
                replace(container_fact(CONTAINER_ID), mounts=(wrong_secret,)),
                ("name=seccomp,profile=builtin",),
            )
        self.assertIn("generated-secret-name", caught.exception.reason)
        self.assertNotIn("/tmp/compose-123", caught.exception.reason)
        with self.assertRaises(DockerSupervisionError):
            contract.validate_observation(
                replace(
                    container_fact(CONTAINER_ID),
                    mounts=(secret, DockerMountFact("bind", "/tmp/other", "/extra", True)),
                ),
                ("name=seccomp,profile=builtin",),
            )

    def test_stops_at_60_gb_growth(self) -> None:
        handle = FakeHandle([None])
        counter = FakeCounter(
            [reading(), reading(task=DOCKER_GROWTH_STOP_BYTES)]
        )
        supervisor, _ = self.supervisor(counter=counter, handles=[handle])

        with self.assertRaises(DockerSupervisionError) as caught:
            supervisor.pull(self.identity, IMAGE, lease=self.lease, timeout_seconds=30)

        self.assertEqual(caught.exception.exit_code, 70)
        self.assertEqual(handle.terminated, 1)

    def test_failure_paths_remove_only_observed_container_and_verify_empty(self) -> None:
        cases = (
            (
                "timeout",
                FakeCounter(
                    [reading(), reading(containers=(CONTAINER_ID,)), reading()]
                ),
                FakeLockGuard(),
                iter((0.0, 0.0, 0.0, 0.0, 31.0, *([31.0] * 10))).__next__,
            ),
            (
                "lock",
                FakeCounter(
                    [reading(), reading(containers=(CONTAINER_ID,)), reading()]
                ),
                FakeLockGuard([True, True, True, False]),
                None,
            ),
            (
                "counter",
                FakeCounter(
                    [
                        reading(),
                        OSError("counter unavailable"),
                        reading(containers=(CONTAINER_ID,)),
                        reading(),
                    ]
                ),
                FakeLockGuard(),
                None,
            ),
            (
                "threshold",
                FakeCounter(
                    [
                        reading(),
                        reading(
                            task=DOCKER_GROWTH_STOP_BYTES,
                            containers=(CONTAINER_ID,),
                        ),
                        reading(containers=(CONTAINER_ID,)),
                        reading(),
                    ]
                ),
                FakeLockGuard(),
                None,
            ),
        )
        for name, counter, guard, monotonic in cases:
            with self.subTest(name=name):
                main_handle = FakeHandle([None])
                runner = FakeRunner([main_handle, FakeHandle([0])])
                options = dict(
                    runner=runner,
                    counter=counter,
                    lock_guard=guard,
                )
                if monotonic is not None:
                    options["monotonic"] = monotonic
                supervisor = DockerSupervisor(**options)

                with self.assertRaises(DockerSupervisionError) as caught:
                    supervisor.pull(
                        self.identity,
                        IMAGE,
                        lease=self.lease,
                        timeout_seconds=30,
                    )

                self.assertEqual(caught.exception.exit_code, 70)
                self.assertEqual(main_handle.terminated, 1)
                self.assertEqual(
                    runner.commands[-1],
                    ("docker", "container", "rm", "--force", CONTAINER_ID),
                )
                self.assertEqual(caught.exception.samples[-1].phase, "cleanup_verified")
                self.assertEqual(caught.exception.samples[-1].task_container_ids, ())

    def test_unexpected_wait_failure_also_cleans_observed_container(self) -> None:
        main_handle = FailingWaitHandle([])
        runner = FakeRunner([main_handle, FakeHandle([0])])
        counter = FakeCounter(
            [reading(), reading(containers=(CONTAINER_ID,)), reading()]
        )
        supervisor = DockerSupervisor(
            runner=runner,
            counter=counter,
            lock_guard=FakeLockGuard(),
        )

        with self.assertRaises(DockerSupervisionError) as caught:
            supervisor.pull(
                self.identity,
                IMAGE,
                lease=self.lease,
                timeout_seconds=30,
            )

        self.assertEqual(caught.exception.reason, "Docker command supervision failed")
        self.assertEqual(main_handle.terminated, 1)
        self.assertEqual(
            runner.commands[-1],
            ("docker", "container", "rm", "--force", CONTAINER_ID),
        )
        self.assertEqual(caught.exception.samples[-1].phase, "cleanup_verified")

    def test_failed_cleanup_is_fail_closed_and_never_targets_unobserved_objects(self) -> None:
        main_handle = FakeHandle([None])
        cleanup_handle = FakeHandle([1])
        runner = FakeRunner([main_handle, cleanup_handle])
        counter = FakeCounter(
            [
                reading(),
                reading(
                    task=DOCKER_GROWTH_STOP_BYTES,
                    containers=(CONTAINER_ID,),
                ),
                reading(containers=(CONTAINER_ID,)),
                reading(containers=(CONTAINER_ID, OTHER_CONTAINER_ID)),
            ]
        )
        supervisor = DockerSupervisor(
            runner=runner,
            counter=counter,
            lock_guard=FakeLockGuard(),
        )

        with self.assertRaises(DockerSupervisionError) as caught:
            supervisor.pull(
                self.identity,
                IMAGE,
                lease=self.lease,
                timeout_seconds=30,
            )

        self.assertIn("cleanup was not verified", caught.exception.reason)
        self.assertEqual(
            runner.commands[-1],
            ("docker", "container", "rm", "--force", CONTAINER_ID),
        )
        self.assertNotIn(OTHER_CONTAINER_ID, runner.commands[-1])
        self.assertEqual(
            [sample.phase for sample in caught.exception.samples[-2:]],
            ["post_stop", "cleanup_unverified"],
        )

    def test_low_data_root_space_fails_before_start(self) -> None:
        counter = FakeCounter([reading(free=DATA_ROOT_FREE_STOP_BYTES - 1)])
        supervisor, runner = self.supervisor(counter=counter, handles=[FakeHandle([0])])

        with self.assertRaises(DockerSupervisionError):
            supervisor.pull(self.identity, IMAGE, lease=self.lease, timeout_seconds=30)

        self.assertEqual(runner.commands, [])

    def test_lock_loss_during_baseline_counter_prevents_command_start(self) -> None:
        counter = FakeCounter([reading()])
        supervisor, runner = self.supervisor(
            counter=counter,
            handles=[FakeHandle([0])],
            lock=FakeLockGuard([True, True, False]),
        )

        with self.assertRaises(DockerSupervisionError) as caught:
            supervisor.pull(self.identity, IMAGE, lease=self.lease, timeout_seconds=30)

        self.assertEqual(caught.exception.reason, "shared heavy lock was lost")
        self.assertEqual(len(counter.calls), 1)
        self.assertEqual(runner.commands, [])

    def test_lock_loss_during_final_counter_cannot_return_success(self) -> None:
        counter = FakeCounter([reading(), reading()])
        handle = FakeHandle([0])
        supervisor, _ = self.supervisor(
            counter=counter,
            handles=[handle],
            lock=FakeLockGuard([True, True, True, True, True, False]),
        )

        with self.assertRaises(DockerSupervisionError) as caught:
            supervisor.pull(self.identity, IMAGE, lease=self.lease, timeout_seconds=30)

        self.assertEqual(caught.exception.reason, "shared heavy lock was lost")
        self.assertEqual(handle.terminated, 0)
        self.assertEqual(len(counter.calls), 4)
        self.assertEqual(
            [sample.phase for sample in caught.exception.samples],
            ["baseline", "post_stop", "cleanup_verified"],
        )

    def test_counter_failure_and_lost_lock_stop_active_command(self) -> None:
        for counter, guard in (
            (FakeCounter([reading(), OSError("counter failed")]), FakeLockGuard()),
            (FakeCounter([reading(), reading()]), FakeLockGuard([True, True, True, False])),
        ):
            with self.subTest(guard=guard):
                handle = FakeHandle([None])
                supervisor, _ = self.supervisor(counter=counter, handles=[handle], lock=guard)
                with self.assertRaises(DockerSupervisionError) as caught:
                    supervisor.pull(self.identity, IMAGE, lease=self.lease, timeout_seconds=30)
                self.assertEqual(caught.exception.exit_code, 70)
                self.assertEqual(handle.terminated, 1)

    def test_lock_loss_after_wait_is_detected_before_post_command_counting(self) -> None:
        counter = FakeCounter([reading(), reading()])
        handle = FakeHandle([0])
        supervisor, _ = self.supervisor(
            counter=counter,
            handles=[handle],
            lock=FakeLockGuard([True, True, True, True, False]),
        )

        with self.assertRaises(DockerSupervisionError) as caught:
            supervisor.pull(self.identity, IMAGE, lease=self.lease, timeout_seconds=30)

        self.assertEqual(caught.exception.exit_code, 70)
        self.assertEqual(len(counter.calls), 3)
        self.assertEqual(
            [sample.phase for sample in caught.exception.samples],
            ["baseline", "post_stop", "cleanup_verified"],
        )
        self.assertEqual(handle.terminated, 0)

    def test_cleanup_accepts_only_container_ids_observed_for_this_task(self) -> None:
        run_handle = FakeHandle([0])
        cleanup_handle = FakeHandle([0])
        counter = FakeCounter(
            [
                reading(),
                reading(containers=(CONTAINER_ID,)),
                reading(containers=(CONTAINER_ID,)),
                reading(),
            ]
        )
        supervisor, runner = self.supervisor(
            counter=counter,
            handles=[run_handle, cleanup_handle],
        )
        supervisor.pull(
            self.identity,
            IMAGE,
            lease=self.lease,
            timeout_seconds=30,
        )

        with self.assertRaises(DockerSupervisionError):
            supervisor.cleanup_containers(
                self.identity,
                ("c" * 64,),
                lease=self.lease,
                timeout_seconds=30,
            )
        result = supervisor.cleanup_containers(
            self.identity,
            (CONTAINER_ID,),
            lease=self.lease,
            timeout_seconds=30,
        )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(
            runner.commands[-1],
            ("docker", "container", "rm", "--force", CONTAINER_ID),
        )

    def test_rejects_floating_images_and_missing_limits(self) -> None:
        supervisor, runner = self.supervisor(
            counter=FakeCounter([reading()]),
            handles=[FakeHandle([0])],
        )
        with self.assertRaises(DockerSupervisionError):
            supervisor.pull(
                self.identity,
                "example.invalid/rondo/task:latest",
                lease=self.lease,
                timeout_seconds=30,
            )
        with self.assertRaises(DockerSupervisionError):
            supervisor.pull(
                self.identity,
                f"sha256:{'d' * 64}",
                lease=self.lease,
                timeout_seconds=30,
            )
        with self.assertRaises(DockerSupervisionError):
            DockerLimits(0, 0, 0, 0).validate()
        self.assertEqual(runner.commands, [])

    def test_run_accepts_content_addressed_local_image_id(self) -> None:
        supervisor, runner = self.supervisor(
            counter=FakeCounter([reading(), reading()]),
            handles=[FakeHandle([0])],
        )
        image_id = f"sha256:{'d' * 64}"
        result = supervisor.run(
            self.identity,
            image_id,
            (),
            lease=self.lease,
            limits=DockerLimits(100, 100, 2, 30),
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn(image_id, runner.commands[0])


if __name__ == "__main__":
    unittest.main()
