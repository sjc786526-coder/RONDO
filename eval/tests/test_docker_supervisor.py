from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.docker_supervisor import (  # noqa: E402
    DATA_ROOT_FREE_STOP_BYTES,
    DOCKER_GROWTH_WARN_BYTES,
    DOCKER_GROWTH_STOP_BYTES,
    DockerCounterReading,
    FAILURE_CLEANUP_TIMEOUT_SECONDS,
    HOST_SUCCESS_TEARDOWN_GRACE_SECONDS,
    DockerLimits,
    DockerOperation,
    DockerSupervisionError,
    DockerSupervisor,
    DockerTaskIdentity,
    HeavyLockLease,
    SAMPLE_INTERVAL_SECONDS,
)


IMAGE = f"example.invalid/rondo/task@sha256:{'a' * 64}"
CONTAINER_ID = "b" * 64
OTHER_CONTAINER_ID = "c" * 64


def reading(
    *,
    total: int = 1_000,
    task: int = 0,
    free: int = DATA_ROOT_FREE_STOP_BYTES + 1,
    containers: tuple[str, ...] = (),
) -> DockerCounterReading:
    return DockerCounterReading(
        docker_system_df={"layers_size": total, "containers_size": task},
        docker_total_bytes=total,
        task_bytes=task,
        data_root="/var/lib/docker",
        data_root_filesystem_free_bytes=free,
        task_container_ids=containers,
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

    def sample(self, *, identity, operation):
        self.calls.append((identity, operation))
        value = self.values.pop(0) if len(self.values) > 1 else self.values[0]
        if isinstance(value, Exception):
            raise value
        return value


class FakeHandle:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.waits: list[float] = []
        self.terminated = 0
        self.killed = 0

    def wait(self, timeout_seconds):
        self.waits.append(timeout_seconds)
        if self.terminated or self.killed:
            return 143
        return self.outcomes.pop(0) if self.outcomes else 0

    def terminate(self):
        self.terminated += 1

    def kill(self):
        self.killed += 1


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

    def supervisor(
        self,
        *,
        counter,
        handles,
        lock=None,
        cleanup_runner=None,
        monotonic=None,
        sleeper=None,
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

    def test_host_harness_has_public_full_lifetime_supervision(self) -> None:
        handle = FakeHandle([None, 0])
        counter = FakeCounter([reading(), reading(), reading()])
        cleanup_runner = FakeRunner([])
        supervisor, runner = self.supervisor(
            counter=counter,
            handles=[handle],
            cleanup_runner=cleanup_runner,
        )

        result = supervisor.supervise_host_command(
            self.identity,
            ("/project/eval/.venv/bin/harbor", "run", "--help"),
            lease=self.lease,
            timeout_seconds=30,
        )

        self.assertEqual(result.operation, DockerOperation.HOST)
        self.assertEqual(handle.waits, [SAMPLE_INTERVAL_SECONDS] * 2)
        self.assertEqual(
            [sample.phase for sample in result.samples],
            ["baseline", "periodic", "final"],
        )
        self.assertEqual(
            [call[1] for call in counter.calls],
            [DockerOperation.HOST] * 3,
        )
        self.assertEqual(runner.commands[0][0], "/project/eval/.venv/bin/harbor")
        with self.assertRaises(DockerSupervisionError):
            supervisor.supervise_host_command(
                self.identity,
                ("/usr/bin/docker", "ps"),
                lease=self.lease,
                timeout_seconds=30,
            )

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
        )

        self.assertEqual(len(host_runner.commands), 1)
        self.assertEqual(cleanup_runner.commands, [])
        self.assertEqual(clock.sleeps, [SAMPLE_INTERVAL_SECONDS] * 2)
        self.assertEqual(len(result.warnings), 1)
        self.assertEqual(
            [sample.phase for sample in result.samples],
            ["baseline", "final", "teardown_grace", "teardown_grace"],
        )

    def test_successful_host_exit_cleans_after_bounded_teardown_grace(self) -> None:
        clock = FakeClock()
        cleanup_handle = FakeHandle([0])
        cleanup_runner = FakeRunner([cleanup_handle])
        counter = FakeCounter(
            [reading(), *[reading(containers=(CONTAINER_ID,))] * 8, reading()]
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
        self.assertEqual(cleanup_handle.waits, [FAILURE_CLEANUP_TIMEOUT_SECONDS])
        self.assertEqual(result.samples[-2].phase, "post_stop")
        self.assertEqual(result.samples[-1].phase, "cleanup_verified")

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
                    )

                self.assertEqual(clock.sleeps, [SAMPLE_INTERVAL_SECONDS])
                self.assertEqual(host_handle.terminated, 1)
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
                FakeLockGuard([True, True, True, True, False]),
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
                iter((0.0, 31.0)).__next__,
            ),
            (
                "lock",
                FakeCounter(
                    [reading(), reading(containers=(CONTAINER_ID,)), reading()]
                ),
                FakeLockGuard([True, True, False]),
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

    def test_counter_failure_and_lost_lock_stop_active_command(self) -> None:
        for counter, guard in (
            (FakeCounter([reading(), OSError("counter failed")]), FakeLockGuard()),
            (FakeCounter([reading(), reading()]), FakeLockGuard([True, True, False])),
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
            lock=FakeLockGuard([True, True, True, False]),
        )

        with self.assertRaises(DockerSupervisionError) as caught:
            supervisor.pull(self.identity, IMAGE, lease=self.lease, timeout_seconds=30)

        self.assertEqual(caught.exception.exit_code, 70)
        self.assertEqual(len(counter.calls), 3)
        self.assertEqual(
            [sample.phase for sample in caught.exception.samples],
            ["baseline", "post_stop", "cleanup_verified"],
        )
        self.assertEqual(handle.terminated, 1)

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
