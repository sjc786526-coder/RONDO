"""Fail-closed supervision for Docker work executed under the shared heavy lock.

The module deliberately has no subprocess-backed default.  Callers must inject
both an asynchronous command runner and a counter implementation, which keeps
unit tests offline and prevents importing this module from starting Docker.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Mapping, Protocol, Sequence

from .exit_codes import INFRA_ERROR


SAMPLE_INTERVAL_SECONDS = 5.0
FAILURE_CLEANUP_TIMEOUT_SECONDS = 30.0
DOCKER_GROWTH_WARN_BYTES = 40_000_000_000
DOCKER_GROWTH_STOP_BYTES = 60_000_000_000
DATA_ROOT_FREE_STOP_BYTES = 80 * 1024**3
TASK_LABEL_KEY = "dev.rondo.eval.task"

_TASK_ID = re.compile(r"[0-9A-Za-z][0-9A-Za-z_.-]{5,95}\Z")
_SHA256_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}\Z")
_LOCAL_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_OBJECT_ID = re.compile(r"[0-9a-f]{12,64}\Z")


class DockerOperation(StrEnum):
    PULL = "pull"
    BUILD = "build"
    RUN = "run"
    HOST = "host"
    CLEANUP = "cleanup"


@dataclass(frozen=True)
class HeavyLockLease:
    """Opaque proof supplied by the wrapper that owns the shared heavy lock."""

    token: str
    held: bool

    def validate(self) -> None:
        if not self.held or len(self.token) < 16 or len(self.token) > 256:
            raise DockerSupervisionError("shared heavy lock is not held")
        if any(character.isspace() or character == "\x00" for character in self.token):
            raise DockerSupervisionError("shared heavy lock token is invalid")


class HeavyLockGuard(Protocol):
    """Checks the lease against the upper-level shared lock owner."""

    def is_held(self, lease: HeavyLockLease) -> bool: ...


@dataclass(frozen=True)
class DockerTaskIdentity:
    """Run-unique identity used for names, labels, selection, and cleanup."""

    task_id: str

    def validate(self) -> None:
        if not _TASK_ID.fullmatch(self.task_id):
            raise DockerSupervisionError("Docker task id is invalid or not run-unique")

    @property
    def container_name(self) -> str:
        self.validate()
        return f"rondo-eval-{self.task_id}"

    @property
    def label(self) -> str:
        self.validate()
        return f"{TASK_LABEL_KEY}={self.task_id}"

    @property
    def exact_label_filter(self) -> tuple[str, str]:
        return ("--filter", f"label={self.label}")


@dataclass(frozen=True)
class DockerLimits:
    """Explicit container and wall-clock limits; no field has an implicit default."""

    memory_bytes: int
    memory_swap_bytes: int
    pids_limit: int
    timeout_seconds: int

    def validate(self) -> None:
        if self.memory_bytes <= 0:
            raise DockerSupervisionError("Docker memory limit must be positive")
        if self.memory_swap_bytes < self.memory_bytes:
            raise DockerSupervisionError("Docker memory-swap must be at least memory")
        if self.pids_limit <= 0 or self.timeout_seconds <= 0:
            raise DockerSupervisionError("Docker pids and timeout limits must be positive")


@dataclass(frozen=True)
class DockerCounterReading:
    """One structured equivalent of ``docker system df`` plus host counters."""

    docker_system_df: Mapping[str, object]
    docker_total_bytes: int
    task_bytes: int
    data_root: str
    data_root_filesystem_free_bytes: int
    task_container_ids: tuple[str, ...] = ()
    task_image_ids: tuple[str, ...] = ()

    def validate(self) -> None:
        if not isinstance(self.docker_system_df, Mapping) or not self.docker_system_df:
            raise DockerSupervisionError("docker system df is unavailable")
        for value in (
            self.docker_total_bytes,
            self.task_bytes,
            self.data_root_filesystem_free_bytes,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise DockerSupervisionError("Docker storage counter is unreadable")
        if not self.data_root or not os.path.isabs(self.data_root):
            raise DockerSupervisionError("Docker data-root filesystem is unreadable")
        for object_id in (*self.task_container_ids, *self.task_image_ids):
            if not _OBJECT_ID.fullmatch(object_id):
                raise DockerSupervisionError("task-owned Docker object id is invalid")


class DockerCounter(Protocol):
    """Counter bound to the real data-root and ``identity.exact_label_filter``.

    Implementations must obtain all fields afresh for every call and raise if
    Docker, the exact task selection, data-root, or filesystem counter cannot be
    read.  Reusing a cached successful count would violate this protocol.
    """

    def sample(
        self,
        *,
        identity: DockerTaskIdentity,
        operation: DockerOperation,
    ) -> DockerCounterReading: ...


class RunningCommand(Protocol):
    """A non-blocking process handle returned by an injected runner."""

    def wait(self, timeout_seconds: float) -> int | None:
        """Return an exit status, or ``None`` if still running at the deadline."""

    def terminate(self) -> None: ...

    def kill(self) -> None: ...


class DockerCommandRunner(Protocol):
    """Starts the exact argv without a shell and returns without blocking."""

    def start(self, argv: tuple[str, ...]) -> RunningCommand: ...


@dataclass(frozen=True)
class DockerSample:
    phase: str
    docker_system_df: Mapping[str, object]
    docker_total_bytes: int
    task_bytes: int
    docker_growth_bytes: int
    task_growth_bytes: int
    data_root: str
    data_root_filesystem_free_bytes: int
    task_container_ids: tuple[str, ...]
    task_image_ids: tuple[str, ...]


@dataclass(frozen=True)
class DockerExecutionResult:
    operation: DockerOperation
    argv: tuple[str, ...]
    returncode: int
    samples: tuple[DockerSample, ...]
    warnings: tuple[str, ...]


class DockerSupervisionError(RuntimeError):
    """Infrastructure failure.  Every caller-facing instance maps to exit 70."""

    exit_code = INFRA_ERROR

    def __init__(self, reason: str, *, samples: Sequence[DockerSample] = ()):
        super().__init__(reason)
        self.reason = reason
        self.samples = tuple(samples)


class _CleanupVerificationError(RuntimeError):
    """Internal signal used to avoid recursively retrying failed cleanup."""


class DockerSupervisor:
    """Builds bounded Docker commands and supervises their complete lifetime."""

    def __init__(
        self,
        *,
        runner: DockerCommandRunner,
        counter: DockerCounter,
        lock_guard: HeavyLockGuard,
        cleanup_runner: DockerCommandRunner | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        self._runner = runner
        self._cleanup_runner = cleanup_runner or runner
        self._has_separate_cleanup_runner = (
            cleanup_runner is not None and cleanup_runner is not runner
        )
        self._counter = counter
        self._lock_guard = lock_guard
        self._monotonic = monotonic
        self._owned_container_ids: dict[str, set[str]] = {}

    def pull(
        self,
        identity: DockerTaskIdentity,
        image: str,
        *,
        lease: HeavyLockLease,
        timeout_seconds: int,
        platform: str = "linux/amd64",
    ) -> DockerExecutionResult:
        _require_registry_pinned_image(image)
        if platform != "linux/amd64":
            raise DockerSupervisionError("P1 Docker pulls require linux/amd64")
        return self._execute(
            DockerOperation.PULL,
            identity,
            ("docker", "image", "pull", "--platform", platform, image),
            lease=lease,
            timeout_seconds=timeout_seconds,
        )

    def build(
        self,
        identity: DockerTaskIdentity,
        context: str,
        image_tag: str,
        *,
        lease: HeavyLockLease,
        timeout_seconds: int,
        dockerfile: str | None = None,
    ) -> DockerExecutionResult:
        _require_cli_value(context, "Docker build context")
        _require_cli_value(image_tag, "Docker image tag")
        argv = ["docker", "image", "build", "--label", identity.label, "--tag", image_tag]
        if dockerfile is not None:
            _require_cli_value(dockerfile, "Dockerfile path")
            argv.extend(("--file", dockerfile))
        argv.append(context)
        return self._execute(
            DockerOperation.BUILD,
            identity,
            tuple(argv),
            lease=lease,
            timeout_seconds=timeout_seconds,
        )

    def run(
        self,
        identity: DockerTaskIdentity,
        image: str,
        command: Sequence[str],
        *,
        lease: HeavyLockLease,
        limits: DockerLimits,
    ) -> DockerExecutionResult:
        _require_pinned_image(image)
        limits.validate()
        command_args = _validated_command(command)
        argv = (
            "docker",
            "container",
            "run",
            "--rm",
            "--name",
            identity.container_name,
            "--label",
            identity.label,
            "--memory",
            str(limits.memory_bytes),
            "--memory-swap",
            str(limits.memory_swap_bytes),
            "--pids-limit",
            str(limits.pids_limit),
            image,
            *command_args,
        )
        return self._execute(
            DockerOperation.RUN,
            identity,
            argv,
            lease=lease,
            timeout_seconds=limits.timeout_seconds,
        )

    def supervise_host_command(
        self,
        identity: DockerTaskIdentity,
        command: Sequence[str],
        *,
        lease: HeavyLockLease,
        timeout_seconds: int,
    ) -> DockerExecutionResult:
        """Supervise a host harness that creates labelled Docker objects.

        The injected runner is responsible for accepting only the intended
        harness executable and for supplying a secret-free argv.  Harbor then
        receives the same lock, timeout, storage, and host-disk monitoring as
        direct Docker CLI operations without depending on ``_execute``.
        """

        argv = _validated_command(command)
        if not argv:
            raise DockerSupervisionError("host supervision requires a command")
        executable = argv[0].replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
        if executable in {"docker", "docker.exe"}:
            raise DockerSupervisionError("host supervision cannot execute the Docker CLI")
        if not self._has_separate_cleanup_runner:
            raise DockerSupervisionError(
                "host supervision requires a separate Docker cleanup runner"
            )
        return self._execute(
            DockerOperation.HOST,
            identity,
            argv,
            lease=lease,
            timeout_seconds=timeout_seconds,
        )

    def cleanup_containers(
        self,
        identity: DockerTaskIdentity,
        object_ids: Sequence[str],
        *,
        lease: HeavyLockLease,
        timeout_seconds: int,
    ) -> DockerExecutionResult:
        """Remove only exact container ids observed under this task's label."""

        identity.validate()
        requested = tuple(object_ids)
        if not requested or any(not _OBJECT_ID.fullmatch(value) for value in requested):
            raise DockerSupervisionError("cleanup requires exact Docker container ids")
        owned = self._owned_container_ids.get(identity.task_id, set())
        if len(set(requested)) != len(requested) or not set(requested).issubset(owned):
            raise DockerSupervisionError("refusing to clean a Docker object not owned by this task")
        result = self._execute(
            DockerOperation.CLEANUP,
            identity,
            ("docker", "container", "rm", "--force", *requested),
            lease=lease,
            timeout_seconds=timeout_seconds,
        )
        if result.returncode == 0:
            owned.difference_update(requested)
        return result

    def _execute(
        self,
        operation: DockerOperation,
        identity: DockerTaskIdentity,
        argv: tuple[str, ...],
        *,
        lease: HeavyLockLease,
        timeout_seconds: int,
    ) -> DockerExecutionResult:
        identity.validate()
        if timeout_seconds <= 0:
            raise DockerSupervisionError("Docker wall timeout must be positive")
        self._assert_lock(lease)
        samples: list[DockerSample] = []
        warnings: list[str] = []
        baseline = self._read_counter(identity, operation, lease=lease)
        baseline_sample = self._make_sample("baseline", baseline, baseline)
        samples.append(baseline_sample)
        self._enforce_sample(baseline_sample, warnings)
        if operation in {DockerOperation.RUN, DockerOperation.HOST} and baseline.task_container_ids:
            raise DockerSupervisionError(
                "task container already exists before Docker run",
                samples=samples,
            )

        command_runner = (
            self._cleanup_runner if operation is DockerOperation.CLEANUP else self._runner
        )
        try:
            handle = command_runner.start(argv)
        except Exception as exc:
            raise DockerSupervisionError(
                "Docker command could not be started",
                samples=samples,
            ) from exc

        started_at = self._monotonic()
        try:
            while True:
                self._assert_lock(lease, samples=samples)
                elapsed = self._monotonic() - started_at
                remaining = timeout_seconds - elapsed
                if remaining <= 0:
                    raise DockerSupervisionError("Docker wall timeout exceeded", samples=samples)
                wait_seconds = min(SAMPLE_INTERVAL_SECONDS, remaining)
                returncode = handle.wait(wait_seconds)
                reading = self._read_counter(
                    identity,
                    operation,
                    lease=lease,
                    samples=samples,
                )
                phase = "final" if returncode is not None else "periodic"
                sample = self._make_sample(phase, baseline, reading)
                samples.append(sample)
                self._record_owned_containers(identity, reading)
                self._enforce_sample(sample, warnings, samples=samples)
                if returncode is not None:
                    if (
                        operation in {DockerOperation.RUN, DockerOperation.HOST}
                        and sample.task_container_ids
                        and self._cleanup_task_containers(
                            identity,
                            operation,
                            baseline,
                            samples,
                        )
                    ):
                        raise _CleanupVerificationError
                    return DockerExecutionResult(
                        operation=operation,
                        argv=argv,
                        returncode=returncode,
                        samples=tuple(samples),
                        warnings=tuple(warnings),
                    )
        except _CleanupVerificationError as exc:
            raise DockerSupervisionError(
                "Docker command exited with task containers still present; "
                "automatic cleanup was not verified",
                samples=samples,
            ) from exc
        except DockerSupervisionError as exc:
            self._stop(handle)
            cleanup_failed = self._cleanup_task_containers(
                identity,
                operation,
                baseline,
                samples,
            )
            reason = exc.reason
            if cleanup_failed:
                reason = f"{reason}; automatic task-container cleanup was not verified"
            raise DockerSupervisionError(reason, samples=samples) from exc
        except Exception as exc:
            self._stop(handle)
            cleanup_failed = self._cleanup_task_containers(
                identity,
                operation,
                baseline,
                samples,
            )
            reason = "Docker command supervision failed"
            if cleanup_failed:
                reason = f"{reason}; automatic task-container cleanup was not verified"
            raise DockerSupervisionError(
                reason,
                samples=samples,
            ) from exc

    def _read_counter(
        self,
        identity: DockerTaskIdentity,
        operation: DockerOperation,
        *,
        lease: HeavyLockLease,
        samples: Sequence[DockerSample] = (),
    ) -> DockerCounterReading:
        identity.validate()
        self._assert_lock(lease, samples=samples)
        try:
            reading = self._counter.sample(identity=identity, operation=operation)
            reading.validate()
            return reading
        except DockerSupervisionError as exc:
            if samples and not exc.samples:
                raise DockerSupervisionError(exc.reason, samples=samples) from exc
            raise
        except Exception as exc:
            raise DockerSupervisionError(
                "Docker storage counters are unavailable",
                samples=samples,
            ) from exc

    def _cleanup_task_containers(
        self,
        identity: DockerTaskIdentity,
        operation: DockerOperation,
        baseline: DockerCounterReading,
        samples: list[DockerSample],
    ) -> bool:
        """Remove only task-labelled containers observed at command completion.

        Cleanup is a safety action, so it deliberately bypasses a lost lock.
        It remains bounded, uses a Docker-only runner, and never targets an
        image, volume, name, label expression, or unobserved container id.
        """

        if operation is DockerOperation.CLEANUP:
            return True

        observed_before_sample = {
            object_id
            for recorded in samples
            for object_id in recorded.task_container_ids
        }
        try:
            reading = self._read_counter_without_lock(
                identity,
                DockerOperation.CLEANUP,
            )
        except DockerSupervisionError:
            observed_ids = observed_before_sample
        else:
            sample = self._make_sample("post_stop", baseline, reading)
            samples.append(sample)
            self._record_owned_containers(identity, reading)
            observed_ids = set(reading.task_container_ids)

        cleanup_failed = False
        if observed_ids:
            argv = (
                "docker",
                "container",
                "rm",
                "--force",
                *sorted(observed_ids),
            )
            cleanup_handle: RunningCommand | None = None
            try:
                cleanup_handle = self._cleanup_runner.start(argv)
                returncode = cleanup_handle.wait(FAILURE_CLEANUP_TIMEOUT_SECONDS)
                if returncode is None:
                    self._stop(cleanup_handle)
                    cleanup_failed = True
                elif returncode != 0:
                    cleanup_failed = True
            except Exception:
                if cleanup_handle is not None:
                    self._stop(cleanup_handle)
                cleanup_failed = True

        try:
            verified = self._read_counter_without_lock(
                identity,
                DockerOperation.CLEANUP,
            )
        except DockerSupervisionError:
            return True
        phase = "cleanup_verified" if not verified.task_container_ids else "cleanup_unverified"
        verified_sample = self._make_sample(phase, baseline, verified)
        samples.append(verified_sample)
        self._record_owned_containers(identity, verified)
        if verified.task_container_ids:
            cleanup_failed = True
        elif observed_ids:
            self._owned_container_ids.setdefault(identity.task_id, set()).difference_update(
                observed_ids
            )
        return cleanup_failed

    def _read_counter_without_lock(
        self,
        identity: DockerTaskIdentity,
        operation: DockerOperation,
    ) -> DockerCounterReading:
        """Read exact-label cleanup evidence even after the shared lock is lost."""

        identity.validate()
        try:
            reading = self._counter.sample(identity=identity, operation=operation)
            reading.validate()
            return reading
        except DockerSupervisionError:
            raise
        except Exception as exc:
            raise DockerSupervisionError(
                "Docker cleanup counters are unavailable"
            ) from exc

    def _assert_lock(
        self,
        lease: HeavyLockLease,
        *,
        samples: Sequence[DockerSample] = (),
    ) -> None:
        lease.validate()
        try:
            held = self._lock_guard.is_held(lease)
        except Exception as exc:
            raise DockerSupervisionError(
                "shared heavy lock state is unreadable",
                samples=samples,
            ) from exc
        if held is not True:
            raise DockerSupervisionError("shared heavy lock was lost", samples=samples)

    @staticmethod
    def _make_sample(
        phase: str,
        baseline: DockerCounterReading,
        reading: DockerCounterReading,
    ) -> DockerSample:
        return DockerSample(
            phase=phase,
            docker_system_df=dict(reading.docker_system_df),
            docker_total_bytes=reading.docker_total_bytes,
            task_bytes=reading.task_bytes,
            docker_growth_bytes=max(0, reading.docker_total_bytes - baseline.docker_total_bytes),
            task_growth_bytes=max(0, reading.task_bytes - baseline.task_bytes),
            data_root=reading.data_root,
            data_root_filesystem_free_bytes=reading.data_root_filesystem_free_bytes,
            task_container_ids=tuple(reading.task_container_ids),
            task_image_ids=tuple(reading.task_image_ids),
        )

    @staticmethod
    def _enforce_sample(
        sample: DockerSample,
        warnings: list[str],
        *,
        samples: Sequence[DockerSample] = (),
    ) -> None:
        if sample.data_root_filesystem_free_bytes < DATA_ROOT_FREE_STOP_BYTES:
            raise DockerSupervisionError(
                "Docker data-root filesystem has less than 80 GiB free",
                samples=samples or (sample,),
            )
        growth = max(sample.docker_growth_bytes, sample.task_growth_bytes)
        if growth >= DOCKER_GROWTH_STOP_BYTES:
            raise DockerSupervisionError(
                "Docker storage growth reached the 60 GB stop threshold",
                samples=samples or (sample,),
            )
        if growth >= DOCKER_GROWTH_WARN_BYTES and not warnings:
            warnings.append("Docker storage growth reached the 40 GB warning threshold")

    def _record_owned_containers(
        self,
        identity: DockerTaskIdentity,
        reading: DockerCounterReading,
    ) -> None:
        if reading.task_container_ids:
            self._owned_container_ids.setdefault(identity.task_id, set()).update(
                reading.task_container_ids
            )

    @staticmethod
    def _stop(handle: RunningCommand) -> None:
        try:
            handle.terminate()
            if handle.wait(SAMPLE_INTERVAL_SECONDS) is not None:
                return
        except Exception:
            pass
        try:
            handle.kill()
        except Exception:
            pass


def _require_pinned_image(image: str) -> None:
    if not (_SHA256_IMAGE.fullmatch(image) or _LOCAL_IMAGE_ID.fullmatch(image)):
        raise DockerSupervisionError("Docker image must be pinned by sha256 digest")


def _require_registry_pinned_image(image: str) -> None:
    if not _SHA256_IMAGE.fullmatch(image):
        raise DockerSupervisionError("Docker pull requires a registry image pinned by sha256 digest")


def _require_cli_value(value: str, label: str) -> None:
    if not value or value.startswith("-") or "\x00" in value or "\n" in value or "\r" in value:
        raise DockerSupervisionError(f"{label} is invalid")


def _validated_command(command: Sequence[str]) -> tuple[str, ...]:
    result = tuple(command)
    for value in result:
        if not isinstance(value, str) or "\x00" in value:
            raise DockerSupervisionError("Docker container command is invalid")
    return result
