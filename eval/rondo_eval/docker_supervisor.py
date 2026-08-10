"""Fail-closed supervision for Docker work executed under the shared heavy lock.

The module deliberately has no subprocess-backed default.  Callers must inject
both an asynchronous command runner and a counter implementation, which keeps
unit tests offline and prevents importing this module from starting Docker.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import stat
import time
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Callable, Mapping, Protocol, Sequence

from .exit_codes import INFRA_ERROR


SAMPLE_INTERVAL_SECONDS = 5.0
COUNTER_SAMPLE_TIMEOUT_SECONDS = 5.0
FAILURE_CLEANUP_TIMEOUT_SECONDS = 30.0
HOST_SUCCESS_TEARDOWN_GRACE_SECONDS = 30.0
DOCKER_GROWTH_WARN_BYTES = 40_000_000_000
DOCKER_GROWTH_STOP_BYTES = 60_000_000_000
DATA_ROOT_FREE_STOP_BYTES = 80 * 1024**3
TASK_LABEL_KEY = "dev.rondo.eval.task"

_TASK_ID = re.compile(r"[0-9A-Za-z][0-9A-Za-z_.-]{5,95}\Z")
_SHA256_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}\Z")
_LOCAL_IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}\Z")
_OBJECT_ID = re.compile(r"[0-9a-f]{12,64}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FROZEN_BINARY_TARGET = "/opt/rondo-eval/bin/frozen-agent"
_COMPOSE_PROJECT = re.compile(r"[a-z0-9][a-z0-9_-]{0,62}\Z")
_RESOURCE_NAME = re.compile(r"[0-9A-Za-z][0-9A-Za-z_.-]{0,127}\Z")


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


@dataclass(frozen=True, order=True)
class DockerMountFact:
    """Effective mount fact obtained from ``docker container inspect``."""

    kind: str
    source: str
    destination: str
    read_only: bool
    tmpfs_options: tuple[str, ...] = ()

    def validate(self) -> None:
        if self.kind not in {"bind", "volume", "tmpfs"}:
            raise DockerSupervisionError("Docker container mount type is invalid")
        if (not self.source and self.kind != "tmpfs") or "\x00" in self.source:
            raise DockerSupervisionError("Docker container mount source is invalid")
        if not os.path.isabs(self.destination) or "\x00" in self.destination:
            raise DockerSupervisionError("Docker container mount destination is invalid")
        if not isinstance(self.read_only, bool):
            raise DockerSupervisionError("Docker container mount mode is invalid")
        if (
            len(self.tmpfs_options) != len(set(self.tmpfs_options))
            or any(not value or "," in value or "\x00" in value for value in self.tmpfs_options)
            or (self.kind != "tmpfs" and self.tmpfs_options)
        ):
            raise DockerSupervisionError("Docker tmpfs mount options are invalid")


@dataclass(frozen=True)
class ComposeSecretMountContract:
    """The one Compose-generated secret bind whose host temp path is dynamic."""

    destination: str
    source_basename: str

    def validate(self) -> None:
        if not os.path.isabs(self.destination) or "\x00" in self.destination:
            raise DockerSupervisionError("Compose secret destination is invalid")
        if (
            not self.source_basename
            or self.source_basename in {".", ".."}
            or "/" in self.source_basename
            or "\x00" in self.source_basename
        ):
            raise DockerSupervisionError("Compose secret source identity is invalid")

    def matches(self, mount: DockerMountFact) -> bool:
        self.validate()
        mount.validate()
        source = Path(mount.source)
        return (
            mount.kind == "bind"
            and mount.destination == self.destination
            and mount.read_only
            and source.is_absolute()
            and source.name == self.source_basename
            and os.path.normpath(mount.source) == mount.source
        )


@dataclass(frozen=True)
class DockerImageIdentity:
    """Daemon-resolved identity for one frozen registry digest reference."""

    image_reference: str
    image_id: str

    def validate(self) -> None:
        if not (
            _SHA256_IMAGE.fullmatch(self.image_reference)
            or _LOCAL_IMAGE_ID.fullmatch(self.image_reference)
        ):
            raise DockerSupervisionError("Docker image reference is not content addressed")
        if not _LOCAL_IMAGE_ID.fullmatch(self.image_id):
            raise DockerSupervisionError("Docker daemon image id is invalid")


@dataclass(frozen=True, order=True)
class DockerContainerMetricFact:
    """Cgroup counters sampled from the exact task container."""

    container_id: str
    cpu_usage_microseconds: int
    peak_memory_bytes: int

    def validate(self) -> None:
        if not _OBJECT_ID.fullmatch(self.container_id):
            raise DockerSupervisionError("Docker container metric identity is invalid")
        for value in (self.cpu_usage_microseconds, self.peak_memory_bytes):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise DockerSupervisionError("Docker container metric is invalid")
        if self.peak_memory_bytes == 0:
            raise DockerSupervisionError("Docker container peak memory is unavailable")


@dataclass(frozen=True)
class DockerContainerMetrics:
    """Stable container projection accumulated across supervised samples."""

    container_id: str
    cpu_usage_seconds: float
    peak_memory_bytes: int

    def validate(self) -> None:
        if not _OBJECT_ID.fullmatch(self.container_id):
            raise DockerSupervisionError("Docker result metric identity is invalid")
        if (
            isinstance(self.cpu_usage_seconds, bool)
            or not isinstance(self.cpu_usage_seconds, (int, float))
            or not math.isfinite(self.cpu_usage_seconds)
            or self.cpu_usage_seconds < 0
            or isinstance(self.peak_memory_bytes, bool)
            or not isinstance(self.peak_memory_bytes, int)
            or self.peak_memory_bytes <= 0
        ):
            raise DockerSupervisionError("Docker result metric is invalid")


@dataclass(frozen=True)
class DockerDesktopVhdxEvidence:
    """Stable Docker Desktop storage evidence for one supervised execution."""

    baseline_bytes: int
    peak_bytes: int
    final_bytes: int
    peak_growth_bytes: int

    def validate(self) -> None:
        values = (
            self.baseline_bytes,
            self.peak_bytes,
            self.final_bytes,
            self.peak_growth_bytes,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in values
        ):
            raise DockerSupervisionError("Docker Desktop VHDX evidence is invalid")
        if self.peak_bytes < max(self.baseline_bytes, self.final_bytes):
            raise DockerSupervisionError("Docker Desktop VHDX peak evidence is invalid")
        if self.peak_growth_bytes != self.peak_bytes - self.baseline_bytes:
            raise DockerSupervisionError("Docker Desktop VHDX growth evidence is invalid")


@dataclass(frozen=True)
class DockerSeccompEvidence:
    """Observed effective seccomp identity for one exact task container."""

    profile_kind: str
    profile_sha256: str | None

    def validate(self) -> None:
        if self.profile_kind == "builtin":
            if self.profile_sha256 is not None:
                raise DockerSupervisionError("builtin seccomp evidence is inconsistent")
            return
        if self.profile_kind != "custom" or self.profile_sha256 is None:
            raise DockerSupervisionError("Docker seccomp evidence is invalid")
        if not _SHA256.fullmatch(self.profile_sha256):
            raise DockerSupervisionError("Docker seccomp profile identity is invalid")


@dataclass(frozen=True)
class DockerContainerFact:
    """Security and resource facts for one exact task-labelled container."""

    container_id: str
    user: str
    privileged: bool
    cap_add: tuple[str, ...]
    cap_drop: tuple[str, ...]
    security_opt: tuple[str, ...]
    memory_bytes: int
    memory_swap_bytes: int
    pids_limit: int
    read_only_rootfs: bool
    cgroupns_mode: str
    network_mode: str
    networks: tuple[str, ...]
    mounts: tuple[DockerMountFact, ...]
    compose_project: str
    compose_service: str
    image_reference: str
    image_id: str
    seccomp_profile_sha256: str | None = None

    def validate(self) -> None:
        if not _OBJECT_ID.fullmatch(self.container_id):
            raise DockerSupervisionError("Docker container runtime fact id is invalid")
        if not self.user or "\x00" in self.user:
            raise DockerSupervisionError("Docker container runtime user is invalid")
        if not isinstance(self.privileged, bool) or not isinstance(self.read_only_rootfs, bool):
            raise DockerSupervisionError("Docker container privilege fact is invalid")
        for values in (self.cap_add, self.cap_drop, self.security_opt):
            if len(values) != len(set(values)) or any(
                not value or "\x00" in value for value in values
            ):
                raise DockerSupervisionError("Docker container security fact is invalid")
        seccomp_options = tuple(
            value for value in self.security_opt if value.casefold().startswith("seccomp=")
        )
        if any(value.casefold() == "seccomp=unconfined" for value in seccomp_options):
            raise DockerSupervisionError("unconfined Docker seccomp is forbidden")
        if (self.seccomp_profile_sha256 is None) != (not seccomp_options):
            raise DockerSupervisionError("Docker seccomp profile fact is inconsistent")
        if len(seccomp_options) > 1:
            raise DockerSupervisionError("Docker seccomp profile fact is ambiguous")
        for value in (self.memory_bytes, self.memory_swap_bytes, self.pids_limit):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise DockerSupervisionError("Docker container resource fact is invalid")
        if self.cgroupns_mode != "private":
            raise DockerSupervisionError("Docker container cgroup namespace is not private")
        if not self.network_mode or "\x00" in self.network_mode:
            raise DockerSupervisionError("Docker container network mode is invalid")
        if len(self.networks) != len(set(self.networks)) or any(
            not _RESOURCE_NAME.fullmatch(value) for value in self.networks
        ):
            raise DockerSupervisionError("Docker container network attachment is invalid")
        if not self.networks and self.network_mode != "none":
            raise DockerSupervisionError("Docker container has no effective network attachment")
        if not _COMPOSE_PROJECT.fullmatch(self.compose_project):
            raise DockerSupervisionError("Docker Compose project identity is invalid")
        if not _RESOURCE_NAME.fullmatch(self.compose_service):
            raise DockerSupervisionError("Docker Compose service identity is invalid")
        DockerImageIdentity(self.image_reference, self.image_id).validate()
        if self.seccomp_profile_sha256 is not None and not _SHA256.fullmatch(
            self.seccomp_profile_sha256
        ):
            raise DockerSupervisionError("Docker seccomp profile identity is invalid")
        if len(self.mounts) != len(set(self.mounts)):
            raise DockerSupervisionError("Docker container mounts are ambiguous")
        if len({mount.destination for mount in self.mounts}) != len(self.mounts):
            raise DockerSupervisionError("Docker container mount destinations are ambiguous")
        for mount in self.mounts:
            mount.validate()


@dataclass(frozen=True, order=True)
class ComposeResourceFact:
    """Exact daemon object bound to one Compose project label."""

    kind: str
    object_id: str
    name: str

    def validate(self) -> None:
        if self.kind not in {"network", "volume"}:
            raise DockerSupervisionError("Docker Compose resource kind is invalid")
        if self.kind == "network" and not _OBJECT_ID.fullmatch(self.object_id):
            raise DockerSupervisionError("Docker Compose network id is invalid")
        if self.kind == "volume" and self.object_id != self.name:
            raise DockerSupervisionError("Docker Compose volume identity is invalid")
        if not _RESOURCE_NAME.fullmatch(self.name):
            raise DockerSupervisionError("Docker Compose resource name is invalid")


@dataclass(frozen=True)
class HostContainerContract:
    """Expected effective state for the one Harbor task container.

    This is intentionally a strict equality contract.  The Terminal-Bench
    projection must build it from the already-frozen task/overlay rather than
    teaching the supervisor Harbor-specific defaults.
    """

    user: str
    memory_bytes: int
    memory_swap_bytes: int
    pids_limit: int
    compose_project: str
    compose_service: str
    network_mode: str
    networks: tuple[str, ...]
    mounts: tuple[DockerMountFact, ...]
    cgroupns_mode: str = "private"
    image_reference: str | None = None
    image_id: str | None = None
    require_image_identity: bool = False
    require_container_metrics: bool = False
    compose_secret_mount: ComposeSecretMountContract | None = None
    privileged: bool = False
    cap_add: tuple[str, ...] = ()
    cap_drop: tuple[str, ...] = ()
    security_opt: tuple[str, ...] = ()
    read_only_rootfs: bool = False
    seccomp_profile_sha256: str | None = None
    required_daemon_security_options: tuple[str, ...] = (
        "name=seccomp,profile=builtin",
    )

    def validate(self) -> None:
        if not self.user or "\x00" in self.user:
            raise DockerSupervisionError("expected Docker runtime user is invalid")
        DockerLimits(
            self.memory_bytes,
            self.memory_swap_bytes,
            self.pids_limit,
            1,
        ).validate()
        if not _COMPOSE_PROJECT.fullmatch(self.compose_project):
            raise DockerSupervisionError("expected Docker Compose project is invalid")
        if not _RESOURCE_NAME.fullmatch(self.compose_service):
            raise DockerSupervisionError("expected Docker Compose service is invalid")
        if not self.network_mode or "\x00" in self.network_mode:
            raise DockerSupervisionError("expected Docker network mode is invalid")
        if len(self.networks) != len(set(self.networks)) or any(
            not _RESOURCE_NAME.fullmatch(value) for value in self.networks
        ):
            raise DockerSupervisionError("expected Docker networks are invalid")
        if not self.networks and self.network_mode != "none":
            raise DockerSupervisionError("expected Docker network attachment is invalid")
        if len(self.mounts) != len(set(self.mounts)):
            raise DockerSupervisionError("expected Docker mounts are ambiguous")
        for mount in self.mounts:
            mount.validate()
        if self.cgroupns_mode != "private":
            raise DockerSupervisionError("private Docker cgroup namespace is required")
        if not isinstance(self.require_image_identity, bool) or not isinstance(
            self.require_container_metrics, bool
        ):
            raise DockerSupervisionError("Docker runtime evidence gate is invalid")
        if (self.image_reference is None) != (self.image_id is None):
            raise DockerSupervisionError("Docker image contract is incomplete")
        if self.image_reference is not None and self.image_id is not None:
            DockerImageIdentity(self.image_reference, self.image_id).validate()
        if self.require_image_identity and self.image_reference is None:
            raise DockerSupervisionError("Docker image identity evidence is required")
        if self.compose_secret_mount is not None:
            self.compose_secret_mount.validate()
            if any(
                mount.destination == self.compose_secret_mount.destination
                for mount in self.mounts
            ):
                raise DockerSupervisionError("Compose secret overlaps an exact mount")
        for values in (
            self.cap_add,
            self.cap_drop,
            self.security_opt,
            self.required_daemon_security_options,
        ):
            if len(values) != len(set(values)) or any(
                not value or "\x00" in value for value in values
            ):
                raise DockerSupervisionError("expected Docker security state is invalid")
        if self.privileged:
            raise DockerSupervisionError("privileged task containers are forbidden")
        if "SYS_ADMIN" in self.cap_add:
            raise DockerSupervisionError("SYS_ADMIN is forbidden")
        forbidden = {"seccomp=unconfined", "apparmor=unconfined", "label=disable"}
        if forbidden.intersection(value.casefold() for value in self.security_opt):
            raise DockerSupervisionError("unconfined Docker security options are forbidden")
        if self.seccomp_profile_sha256 is None:
            if any(
                value.casefold().startswith("seccomp=") for value in self.security_opt
            ):
                raise DockerSupervisionError("default seccomp contract cannot name a profile")
        elif not _SHA256.fullmatch(self.seccomp_profile_sha256):
            raise DockerSupervisionError("minimal seccomp profile contract is invalid")

    def validate_observation(
        self,
        fact: DockerContainerFact,
        daemon_security_options: tuple[str, ...],
    ) -> None:
        self.validate()
        fact.validate()
        observed_mounts = list(fact.mounts)
        if self.compose_secret_mount is not None:
            secret_mounts = [
                mount
                for mount in observed_mounts
                if mount.destination == self.compose_secret_mount.destination
            ]
            if len(secret_mounts) != 1 or not self.compose_secret_mount.matches(secret_mounts[0]):
                diagnostic_mounts = secret_mounts if secret_mounts else observed_mounts
                safe_facts = tuple(
                    {
                        "kind": mount.kind,
                        "source_basename": Path(mount.source).name,
                        "source_absolute": Path(mount.source).is_absolute(),
                        "destination": mount.destination,
                        "read_only": mount.read_only,
                    }
                    for mount in diagnostic_mounts
                )
                raise DockerSupervisionError(
                    "effective Docker Compose secret mount differs: "
                    + json.dumps(
                        safe_facts,
                        ensure_ascii=True,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
            observed_mounts.remove(secret_mounts[0])
        expected = (
            self.user,
            self.privileged,
            self.cap_add,
            self.cap_drop,
            self.security_opt,
            self.memory_bytes,
            self.memory_swap_bytes,
            self.pids_limit,
            self.read_only_rootfs,
            self.cgroupns_mode,
            self.network_mode,
            tuple(sorted(self.networks)),
            tuple(sorted(self.mounts)),
            self.compose_project,
            self.compose_service,
            self.image_reference,
            self.image_id,
            self.seccomp_profile_sha256,
        )
        observed = (
            fact.user,
            fact.privileged,
            fact.cap_add,
            fact.cap_drop,
            tuple(
                value
                for value in fact.security_opt
                if not value.casefold().startswith("seccomp=")
            ),
            fact.memory_bytes,
            fact.memory_swap_bytes,
            fact.pids_limit,
            fact.read_only_rootfs,
            fact.cgroupns_mode,
            fact.network_mode,
            tuple(sorted(fact.networks)),
            tuple(sorted(observed_mounts)),
            fact.compose_project,
            fact.compose_service,
            fact.image_reference if self.image_reference is not None else None,
            fact.image_id if self.image_id is not None else None,
            fact.seccomp_profile_sha256,
        )
        if observed != expected:
            fields = (
                "user",
                "privileged",
                "cap_add",
                "cap_drop",
                "security_opt",
                "memory",
                "memory_swap",
                "pids_limit",
                "read_only_rootfs",
                "cgroupns_mode",
                "network_mode",
                "networks",
                "mounts",
                "compose_project",
                "compose_service",
                "image_reference",
                "image_id",
                "seccomp_profile",
            )
            mismatches = tuple(
                field
                for field, expected_value, observed_value in zip(
                    fields,
                    expected,
                    observed,
                    strict=True,
                )
                if expected_value != observed_value
            )
            raise DockerSupervisionError(
                "effective Docker container state differs from contract: "
                + ",".join(mismatches)
                + (
                    "; observed_non_seccomp_security_opt="
                    + json.dumps(observed[4], ensure_ascii=True, separators=(",", ":"))
                    if "security_opt" in mismatches
                    else ""
                )
            )
        if any(value not in daemon_security_options for value in self.required_daemon_security_options):
            raise DockerSupervisionError("effective Docker daemon security state differs from contract")


@dataclass(frozen=True)
class ComposeRunContract:
    """One task container plus the exact Compose resources it may create."""

    container: HostContainerContract
    network_names: tuple[str, ...]
    volume_names: tuple[str, ...] = ()

    def validate(self) -> None:
        self.container.validate()
        if tuple(sorted(self.network_names)) != tuple(sorted(self.container.networks)):
            raise DockerSupervisionError("Compose network contract differs from container")
        for values in (self.network_names, self.volume_names):
            if len(values) != len(set(values)) or any(
                not _RESOURCE_NAME.fullmatch(value) for value in values
            ):
                raise DockerSupervisionError("Compose resource contract is invalid")


@dataclass(frozen=True)
class DockerCounterReading:
    """One structured equivalent of ``docker system df`` plus host counters."""

    docker_system_df: Mapping[str, object]
    docker_total_bytes: int
    task_bytes: int
    data_root: str
    data_root_filesystem_free_bytes: int
    docker_desktop_vhdx_bytes: int | None = None
    task_container_ids: tuple[str, ...] = ()
    task_image_ids: tuple[str, ...] = ()
    task_containers: tuple[DockerContainerFact, ...] = ()
    task_container_metrics: tuple[DockerContainerMetricFact, ...] = ()
    task_networks: tuple[ComposeResourceFact, ...] = ()
    task_volumes: tuple[ComposeResourceFact, ...] = ()
    daemon_security_options: tuple[str, ...] = ()

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
        if self.docker_desktop_vhdx_bytes is not None and (
            isinstance(self.docker_desktop_vhdx_bytes, bool)
            or not isinstance(self.docker_desktop_vhdx_bytes, int)
            or self.docker_desktop_vhdx_bytes < 0
        ):
            raise DockerSupervisionError("Docker Desktop VHDX counter is unreadable")
        for object_id in (*self.task_container_ids, *self.task_image_ids):
            if not _OBJECT_ID.fullmatch(object_id):
                raise DockerSupervisionError("task-owned Docker object id is invalid")
        if tuple(sorted(item.container_id for item in self.task_containers)) != tuple(
            sorted(self.task_container_ids)
        ):
            raise DockerSupervisionError("Docker container facts do not match selected ids")
        for fact in self.task_containers:
            fact.validate()
        metric_ids = tuple(sorted(item.container_id for item in self.task_container_metrics))
        if len(metric_ids) != len(set(metric_ids)) or not set(metric_ids).issubset(
            set(self.task_container_ids)
        ):
            raise DockerSupervisionError("Docker container metrics do not match selected ids")
        for metric in self.task_container_metrics:
            metric.validate()
        for resources, expected_kind in (
            (self.task_networks, "network"),
            (self.task_volumes, "volume"),
        ):
            if len(resources) != len(set(resources)):
                raise DockerSupervisionError("Docker Compose resources are ambiguous")
            for resource in resources:
                resource.validate()
                if resource.kind != expected_kind:
                    raise DockerSupervisionError("Docker Compose resource kind differs")
        if len(self.daemon_security_options) != len(set(self.daemon_security_options)) or any(
            not value or "\x00" in value for value in self.daemon_security_options
        ):
            raise DockerSupervisionError("Docker daemon security facts are invalid")


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
        compose_contract: ComposeRunContract | None = None,
        deadline: float | None = None,
    ) -> DockerCounterReading: ...

    def resolve_image_identity(
        self,
        image_reference: str,
        *,
        deadline: float | None = None,
    ) -> DockerImageIdentity: ...


class RunningCommand(Protocol):
    """A non-blocking process handle returned by an injected runner."""

    def wait(self, timeout_seconds: float) -> int | None:
        """Return an exit status, or ``None`` if still running at the deadline."""

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def close_process_group(self, timeout_seconds: float) -> bool:
        """Stop descendants and prove the dedicated host process group is empty."""


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
    docker_desktop_vhdx_bytes: int | None
    docker_desktop_vhdx_growth_bytes: int
    data_root: str
    data_root_filesystem_free_bytes: int
    task_container_ids: tuple[str, ...]
    task_image_ids: tuple[str, ...]
    task_containers: tuple[DockerContainerFact, ...]
    task_container_metrics: tuple[DockerContainerMetricFact, ...]
    task_networks: tuple[ComposeResourceFact, ...]
    task_volumes: tuple[ComposeResourceFact, ...]
    daemon_security_options: tuple[str, ...]


@dataclass(frozen=True)
class DockerExecutionResult:
    operation: DockerOperation
    argv: tuple[str, ...]
    returncode: int
    samples: tuple[DockerSample, ...]
    warnings: tuple[str, ...]
    image_identity: DockerImageIdentity | None = None
    desktop_vhdx: DockerDesktopVhdxEvidence | None = None
    container_metrics: DockerContainerMetrics | None = None
    effective_seccomp: DockerSeccompEvidence | None = None


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
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self._runner = runner
        self._cleanup_runner = cleanup_runner or runner
        self._has_separate_cleanup_runner = (
            cleanup_runner is not None and cleanup_runner is not runner
        )
        self._counter = counter
        self._lock_guard = lock_guard
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._owned_container_ids: dict[str, set[str]] = {}
        self._owned_networks: dict[str, set[ComposeResourceFact]] = {}
        self._owned_volumes: dict[str, set[ComposeResourceFact]] = {}

    def resolve_image_identity(
        self,
        identity: DockerTaskIdentity,
        image_reference: str,
        *,
        lease: HeavyLockLease,
        timeout_seconds: float = 5.0,
    ) -> DockerImageIdentity:
        """Resolve a pinned image through the guarded, bounded counter path."""

        identity.validate()
        _require_registry_pinned_image(image_reference)
        if timeout_seconds <= 0:
            raise DockerSupervisionError("Docker image identity timeout is invalid")
        self._assert_lock(lease)
        deadline = self._monotonic() + min(
            float(timeout_seconds), COUNTER_SAMPLE_TIMEOUT_SECONDS
        )
        try:
            image_identity = self._counter.resolve_image_identity(
                image_reference,
                deadline=deadline,
            )
            image_identity.validate()
        except DockerSupervisionError:
            raise
        except Exception as exc:
            raise DockerSupervisionError("Docker image identity is unavailable") from exc
        if self._monotonic() >= deadline:
            raise DockerSupervisionError("Docker image identity deadline exceeded")
        self._assert_lock(lease)
        return image_identity

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

    def run_frozen_binary_version(
        self,
        identity: DockerTaskIdentity,
        image: str,
        host_binary: Path,
        binary_sha256: str,
        *,
        lease: HeavyLockLease,
        limits: DockerLimits,
    ) -> DockerExecutionResult:
        """Execute only ``--version`` for one verified host binary in Docker.

        The container target, entrypoint, argument, network isolation, and
        read-only bind semantics are fixed here rather than accepted from the
        caller.  This is the narrow B3 probe, not a general host mount API.
        """

        _require_pinned_image(image)
        limits.validate()
        verified_binary = _verified_frozen_binary(host_binary, binary_sha256)
        mount = (
            f"type=bind,source={verified_binary},"
            f"target={_FROZEN_BINARY_TARGET},readonly"
        )
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
            "--network",
            "none",
            "--read-only",
            "--mount",
            mount,
            "--entrypoint",
            _FROZEN_BINARY_TARGET,
            image,
            "--version",
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
        compose_contract: ComposeRunContract,
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
        compose_contract.validate()
        return self._execute(
            DockerOperation.HOST,
            identity,
            argv,
            lease=lease,
            timeout_seconds=timeout_seconds,
            compose_contract=compose_contract,
        )

    def supervise_diagnostic_command(
        self,
        identity: DockerTaskIdentity,
        argv: Sequence[str],
        *,
        lease: HeavyLockLease,
        limits: DockerLimits,
        compose_contract: ComposeRunContract,
    ) -> DockerExecutionResult:
        """Supervise one fixed, non-privileged Docker diagnostic argv.

        The caller builds the complete command, while this boundary independently
        checks the task identity, resource limits and forbidden privilege knobs.
        It deliberately reuses the host lifecycle path so an exact container must
        be observed and the dedicated Docker CLI process group must be empty.
        """

        identity.validate()
        limits.validate()
        command = _validated_command(argv)
        if not self._has_separate_cleanup_runner:
            raise DockerSupervisionError(
                "diagnostic supervision requires a separate Docker cleanup runner"
            )
        _validate_diagnostic_argv(command, identity, limits)
        compose_contract.validate()
        return self._execute(
            DockerOperation.HOST,
            identity,
            command,
            lease=lease,
            timeout_seconds=limits.timeout_seconds,
            compose_contract=compose_contract,
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
        compose_contract: ComposeRunContract | None = None,
    ) -> DockerExecutionResult:
        identity.validate()
        if timeout_seconds <= 0:
            raise DockerSupervisionError("Docker wall timeout must be positive")
        if operation is DockerOperation.HOST:
            if compose_contract is None:
                raise DockerSupervisionError("host supervision requires a Compose contract")
            compose_contract.validate()
        elif compose_contract is not None:
            raise DockerSupervisionError("Compose contract is valid only for host supervision")
        self._assert_lock(lease)
        started_at = self._monotonic()
        deadline = started_at + timeout_seconds
        samples: list[DockerSample] = []
        warnings: list[str] = []
        baseline = self._read_counter(
            identity,
            operation,
            lease=lease,
            compose_contract=compose_contract,
            deadline=deadline,
        )
        baseline_sample = self._make_sample("baseline", baseline, baseline)
        samples.append(baseline_sample)
        self._enforce_sample(baseline_sample, warnings)
        if operation is DockerOperation.HOST and self._sample_has_compose_resources(baseline_sample):
            raise DockerSupervisionError(
                "task Compose resources already exist before host run",
                samples=samples,
            )
        if operation is DockerOperation.RUN and baseline.task_container_ids:
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

        observed_valid_container = False
        process_group_closed = operation is not DockerOperation.HOST
        command_exited = False
        try:
            while True:
                self._assert_lock(lease, samples=samples)
                elapsed = self._monotonic() - started_at
                remaining = timeout_seconds - elapsed
                if remaining <= 0:
                    raise DockerSupervisionError("Docker wall timeout exceeded", samples=samples)
                wait_seconds = min(SAMPLE_INTERVAL_SECONDS, remaining)
                returncode = handle.wait(wait_seconds)
                if returncode is not None:
                    command_exited = True
                if returncode is not None and operation is DockerOperation.HOST:
                    remaining = deadline - self._monotonic()
                    if remaining <= 0 or not handle.close_process_group(
                        min(SAMPLE_INTERVAL_SECONDS, remaining)
                    ):
                        raise DockerSupervisionError(
                            "host harness process group teardown was not verified",
                            samples=samples,
                        )
                    process_group_closed = True
                reading = self._read_counter(
                    identity,
                    operation,
                    lease=lease,
                    samples=samples,
                    compose_contract=compose_contract,
                    deadline=deadline,
                )
                if compose_contract is not None:
                    self._validate_host_reading(reading, compose_contract, samples=samples)
                    if reading.task_containers:
                        observed_valid_container = True
                phase = "final" if returncode is not None else "periodic"
                sample = self._make_sample(phase, baseline, reading)
                samples.append(sample)
                self._record_owned_containers(identity, reading)
                self._enforce_sample(sample, warnings, samples=samples)
                if returncode is not None:
                    if operation is DockerOperation.HOST and not observed_valid_container:
                        raise DockerSupervisionError(
                            "host harness task container was never observed",
                            samples=samples,
                        )
                    if (
                        operation is DockerOperation.HOST
                        and returncode == 0
                        and self._sample_has_compose_resources(sample)
                        and self._wait_for_successful_host_teardown(
                            identity,
                            lease,
                            baseline,
                            samples,
                            warnings,
                            compose_contract,
                            deadline,
                        )
                    ):
                        durable = self._result_durable_evidence(compose_contract, samples)
                        return DockerExecutionResult(
                            operation=operation,
                            argv=argv,
                            returncode=returncode,
                            samples=tuple(samples),
                            warnings=tuple(warnings),
                            image_identity=durable[0],
                            desktop_vhdx=durable[1],
                            container_metrics=durable[2],
                            effective_seccomp=durable[3],
                        )
                    if (
                        operation in {DockerOperation.RUN, DockerOperation.HOST}
                        and self._sample_has_task_resources(samples[-1])
                        and self._cleanup_task_containers(
                            identity,
                            operation,
                            baseline,
                            samples,
                            compose_contract=compose_contract,
                        )
                    ):
                        raise _CleanupVerificationError
                    durable = self._result_durable_evidence(compose_contract, samples)
                    return DockerExecutionResult(
                        operation=operation,
                        argv=argv,
                        returncode=returncode,
                        samples=tuple(samples),
                        warnings=tuple(warnings),
                        image_identity=durable[0],
                        desktop_vhdx=durable[1],
                        container_metrics=durable[2],
                        effective_seccomp=durable[3],
                    )
        except _CleanupVerificationError as exc:
            raise DockerSupervisionError(
                "Docker command exited with task containers still present; "
                "automatic cleanup was not verified",
                samples=samples,
            ) from exc

        except DockerSupervisionError as exc:
            process_cleanup_failed = False
            if not command_exited or (operation is DockerOperation.HOST and not process_group_closed):
                process_cleanup_failed = not self._stop(
                    handle,
                    close_group=not process_group_closed,
                )
            cleanup_failed = self._cleanup_task_containers(
                identity,
                operation,
                baseline,
                samples,
                compose_contract=compose_contract,
            )
            reason = exc.reason
            if cleanup_failed:
                reason = f"{reason}; automatic task-container cleanup was not verified"
            if process_cleanup_failed:
                reason = f"{reason}; host process-group cleanup was not verified"
            raise DockerSupervisionError(reason, samples=samples) from exc
        except Exception as exc:
            process_cleanup_failed = False
            if not command_exited or (operation is DockerOperation.HOST and not process_group_closed):
                process_cleanup_failed = not self._stop(
                    handle,
                    close_group=not process_group_closed,
                )
            cleanup_failed = self._cleanup_task_containers(
                identity,
                operation,
                baseline,
                samples,
                compose_contract=compose_contract,
            )
            reason = "Docker command supervision failed"
            if cleanup_failed:
                reason = f"{reason}; automatic task-container cleanup was not verified"
            if process_cleanup_failed:
                reason = f"{reason}; host process-group cleanup was not verified"
            raise DockerSupervisionError(
                reason,
                samples=samples,
            ) from exc

    def _wait_for_successful_host_teardown(
        self,
        identity: DockerTaskIdentity,
        lease: HeavyLockLease,
        baseline: DockerCounterReading,
        samples: list[DockerSample],
        warnings: list[str],
        compose_contract: ComposeRunContract,
        command_deadline: float,
    ) -> bool:
        """Allow a successful host harness to finish daemon-side teardown."""

        teardown_deadline = min(
            command_deadline,
            self._monotonic() + HOST_SUCCESS_TEARDOWN_GRACE_SECONDS,
        )
        while True:
            self._assert_lock(lease, samples=samples)
            remaining = teardown_deadline - self._monotonic()
            if remaining <= 0:
                return False
            self._sleeper(min(SAMPLE_INTERVAL_SECONDS, remaining))
            if self._monotonic() >= teardown_deadline:
                return False
            reading = self._read_counter(
                identity,
                DockerOperation.HOST,
                lease=lease,
                samples=samples,
                compose_contract=compose_contract,
                deadline=teardown_deadline,
            )
            self._validate_host_reading(reading, compose_contract, samples=samples)
            sample = self._make_sample("teardown_grace", baseline, reading)
            samples.append(sample)
            self._record_owned_containers(identity, reading)
            self._enforce_sample(sample, warnings, samples=samples)
            if not self._sample_has_compose_resources(sample):
                return True

    def _read_counter(
        self,
        identity: DockerTaskIdentity,
        operation: DockerOperation,
        *,
        lease: HeavyLockLease,
        samples: Sequence[DockerSample] = (),
        compose_contract: ComposeRunContract | None = None,
        deadline: float | None = None,
    ) -> DockerCounterReading:
        identity.validate()
        self._assert_lock(lease, samples=samples)
        if deadline is not None and self._monotonic() >= deadline:
            raise DockerSupervisionError("Docker supervision deadline exceeded", samples=samples)
        sample_deadline = self._counter_sample_deadline(deadline)
        try:
            reading = self._counter.sample(
                identity=identity,
                operation=operation,
                compose_contract=compose_contract,
                deadline=sample_deadline,
            )
            reading.validate()
            if self._monotonic() >= sample_deadline:
                raise DockerSupervisionError(
                    "Docker counter probe exceeded its absolute deadline",
                    samples=samples,
                )
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
        *,
        compose_contract: ComposeRunContract | None = None,
    ) -> bool:
        """Remove only exact task resources observed at command completion.

        Cleanup is a safety action, so it deliberately bypasses a lost lock.
        It remains bounded, uses a Docker-only runner, and targets only exact
        container/network/volume identities already selected and inspected by
        the task/Compose labels.  Images and label expressions are never cleanup
        targets.
        """

        if operation is DockerOperation.CLEANUP:
            return True

        observed_before_sample = {
            object_id
            for recorded in samples
            for object_id in recorded.task_container_ids
        }
        networks_before_sample = {
            resource
            for recorded in samples
            for resource in recorded.task_networks
        }
        volumes_before_sample = {
            resource
            for recorded in samples
            for resource in recorded.task_volumes
        }
        cleanup_deadline = self._monotonic() + FAILURE_CLEANUP_TIMEOUT_SECONDS
        try:
            reading = self._read_counter_without_lock(
                identity,
                DockerOperation.CLEANUP,
                compose_contract=compose_contract,
                deadline=cleanup_deadline,
            )
        except DockerSupervisionError:
            observed_ids = observed_before_sample
            observed_networks = networks_before_sample
            observed_volumes = volumes_before_sample
        else:
            sample = self._make_sample("post_stop", baseline, reading)
            samples.append(sample)
            self._record_owned_containers(identity, reading)
            observed_ids = set(reading.task_container_ids)
            observed_networks = set(reading.task_networks)
            observed_volumes = set(reading.task_volumes)

        cleanup_failed = False
        cleanup_commands: tuple[tuple[str, ...], ...] = tuple(
            command
            for command in (
                (
                    "docker",
                    "container",
                    "rm",
                    "--force",
                    *sorted(observed_ids),
                ) if observed_ids else (),
                (
                    "docker",
                    "network",
                    "rm",
                    *sorted(resource.object_id for resource in observed_networks),
                ) if observed_networks else (),
                (
                    "docker",
                    "volume",
                    "rm",
                    *sorted(resource.name for resource in observed_volumes),
                ) if observed_volumes else (),
            )
            if command
        )
        for argv in cleanup_commands:
            cleanup_handle: RunningCommand | None = None
            try:
                remaining = cleanup_deadline - self._monotonic()
                if remaining <= 0:
                    cleanup_failed = True
                    break
                cleanup_handle = self._cleanup_runner.start(argv)
                returncode = cleanup_handle.wait(remaining)
                if returncode is None:
                    self._stop(cleanup_handle, close_group=False)
                    cleanup_failed = True
                elif returncode != 0:
                    cleanup_failed = True
            except Exception:
                if cleanup_handle is not None:
                    self._stop(cleanup_handle, close_group=False)
                cleanup_failed = True

        try:
            verified = self._read_counter_without_lock(
                identity,
                DockerOperation.CLEANUP,
                compose_contract=compose_contract,
                deadline=cleanup_deadline,
            )
        except DockerSupervisionError:
            return True
        verified_empty = not (
            verified.task_container_ids
            or verified.task_networks
            or verified.task_volumes
        )
        phase = "cleanup_verified" if verified_empty else "cleanup_unverified"
        verified_sample = self._make_sample(phase, baseline, verified)
        samples.append(verified_sample)
        self._record_owned_containers(identity, verified)
        if not verified_empty:
            cleanup_failed = True
        else:
            self._owned_container_ids.setdefault(identity.task_id, set()).difference_update(
                observed_ids
            )
            self._owned_networks.setdefault(identity.task_id, set()).difference_update(
                observed_networks
            )
            self._owned_volumes.setdefault(identity.task_id, set()).difference_update(
                observed_volumes
            )
        return cleanup_failed

    def _read_counter_without_lock(
        self,
        identity: DockerTaskIdentity,
        operation: DockerOperation,
        *,
        compose_contract: ComposeRunContract | None = None,
        deadline: float | None = None,
    ) -> DockerCounterReading:
        """Read exact-label cleanup evidence even after the shared lock is lost."""

        identity.validate()
        try:
            if deadline is not None and self._monotonic() >= deadline:
                raise DockerSupervisionError("Docker cleanup deadline exceeded")
            sample_deadline = self._counter_sample_deadline(deadline)
            reading = self._counter.sample(
                identity=identity,
                operation=operation,
                compose_contract=compose_contract,
                deadline=sample_deadline,
            )
            reading.validate()
            if self._monotonic() >= sample_deadline:
                raise DockerSupervisionError("Docker cleanup probe exceeded its deadline")
            return reading
        except DockerSupervisionError:
            raise
        except Exception as exc:
            raise DockerSupervisionError(
                "Docker cleanup counters are unavailable"
            ) from exc

    def _counter_sample_deadline(self, outer_deadline: float | None) -> float:
        """Give one complete multi-probe sample a fresh, short time budget."""

        now = self._monotonic()
        sample_deadline = now + COUNTER_SAMPLE_TIMEOUT_SECONDS
        if outer_deadline is not None:
            sample_deadline = min(sample_deadline, outer_deadline)
        if sample_deadline <= now:
            raise DockerSupervisionError("Docker counter deadline expired")
        return sample_deadline

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
        if (baseline.docker_desktop_vhdx_bytes is None) != (
            reading.docker_desktop_vhdx_bytes is None
        ):
            raise DockerSupervisionError("Docker Desktop VHDX counter availability changed")
        vhdx_growth = 0
        if (
            baseline.docker_desktop_vhdx_bytes is not None
            and reading.docker_desktop_vhdx_bytes is not None
        ):
            vhdx_growth = max(
                0,
                reading.docker_desktop_vhdx_bytes
                - baseline.docker_desktop_vhdx_bytes,
            )
        return DockerSample(
            phase=phase,
            docker_system_df=dict(reading.docker_system_df),
            docker_total_bytes=reading.docker_total_bytes,
            task_bytes=reading.task_bytes,
            docker_growth_bytes=max(0, reading.docker_total_bytes - baseline.docker_total_bytes),
            task_growth_bytes=max(0, reading.task_bytes - baseline.task_bytes),
            docker_desktop_vhdx_bytes=reading.docker_desktop_vhdx_bytes,
            docker_desktop_vhdx_growth_bytes=vhdx_growth,
            data_root=reading.data_root,
            data_root_filesystem_free_bytes=reading.data_root_filesystem_free_bytes,
            task_container_ids=tuple(reading.task_container_ids),
            task_image_ids=tuple(reading.task_image_ids),
            task_containers=tuple(reading.task_containers),
            task_container_metrics=tuple(reading.task_container_metrics),
            task_networks=tuple(reading.task_networks),
            task_volumes=tuple(reading.task_volumes),
            daemon_security_options=tuple(reading.daemon_security_options),
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
        growth = max(
            sample.docker_growth_bytes,
            sample.task_growth_bytes,
            sample.docker_desktop_vhdx_growth_bytes,
        )
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

        if reading.task_networks:
            self._owned_networks.setdefault(identity.task_id, set()).update(
                reading.task_networks
            )
        if reading.task_volumes:
            self._owned_volumes.setdefault(identity.task_id, set()).update(
                reading.task_volumes
            )

    @staticmethod
    def _sample_has_task_resources(sample: DockerSample) -> bool:
        return bool(sample.task_container_ids or sample.task_networks or sample.task_volumes)

    @staticmethod
    def _sample_has_compose_resources(sample: DockerSample) -> bool:
        return bool(sample.task_container_ids or sample.task_networks or sample.task_volumes)

    @staticmethod
    def _validate_host_reading(
        reading: DockerCounterReading,
        contract: ComposeRunContract,
        *,
        samples: Sequence[DockerSample],
    ) -> None:
        if len(reading.task_containers) > 1:
            raise DockerSupervisionError(
                "more than one exact task container was observed",
                samples=samples,
            )
        for fact in reading.task_containers:
            try:
                contract.container.validate_observation(
                    fact,
                    reading.daemon_security_options,
                )
            except DockerSupervisionError as exc:
                raise DockerSupervisionError(exc.reason, samples=samples) from exc
        if contract.container.require_container_metrics:
            fact_ids = {fact.container_id for fact in reading.task_containers}
            metric_ids = {
                metric.container_id for metric in reading.task_container_metrics
            }
            if metric_ids != fact_ids:
                raise DockerSupervisionError(
                    "required Docker container metrics are unavailable",
                    samples=samples,
                )
        network_names = {resource.name for resource in reading.task_networks}
        volume_names = {resource.name for resource in reading.task_volumes}
        if not network_names.issubset(set(contract.network_names)):
            raise DockerSupervisionError(
                "unexpected Docker Compose network was observed",
                samples=samples,
            )
        if not volume_names.issubset(set(contract.volume_names)):
            raise DockerSupervisionError(
                "unexpected Docker Compose volume was observed",
                samples=samples,
            )

    @staticmethod
    def _result_container_metrics(
        contract: ComposeRunContract | None,
        samples: Sequence[DockerSample],
    ) -> DockerContainerMetrics | None:
        metrics = tuple(
            metric
            for sample in samples
            for metric in sample.task_container_metrics
        )
        if not metrics:
            if contract is not None and contract.container.require_container_metrics:
                raise DockerSupervisionError(
                    "required Docker result metrics were never observed",
                    samples=samples,
                )
            return None
        container_ids = {metric.container_id for metric in metrics}
        if len(container_ids) != 1:
            raise DockerSupervisionError(
                "Docker result metrics changed container identity",
                samples=samples,
            )
        previous: DockerContainerMetricFact | None = None
        for metric in metrics:
            if previous is not None and (
                metric.cpu_usage_microseconds < previous.cpu_usage_microseconds
                or metric.peak_memory_bytes < previous.peak_memory_bytes
            ):
                raise DockerSupervisionError(
                    "Docker container cgroup metrics moved backwards",
                    samples=samples,
                )
            previous = metric
        result = DockerContainerMetrics(
            container_id=next(iter(container_ids)),
            cpu_usage_seconds=max(
                metric.cpu_usage_microseconds for metric in metrics
            )
            / 1_000_000,
            peak_memory_bytes=max(metric.peak_memory_bytes for metric in metrics),
        )
        result.validate()
        return result

    @classmethod
    def _result_durable_evidence(
        cls,
        contract: ComposeRunContract | None,
        samples: Sequence[DockerSample],
    ) -> tuple[
        DockerImageIdentity | None,
        DockerDesktopVhdxEvidence | None,
        DockerContainerMetrics | None,
        DockerSeccompEvidence | None,
    ]:
        facts = tuple(
            fact
            for sample in samples
            for fact in sample.task_containers
        )
        identities = {
            DockerImageIdentity(fact.image_reference, fact.image_id)
            for fact in facts
        }
        if len(identities) > 1:
            raise DockerSupervisionError(
                "Docker result image identity changed",
                samples=samples,
            )
        image_identity = next(iter(identities), None)
        if (
            contract is not None
            and contract.container.require_image_identity
            and image_identity is None
        ):
            raise DockerSupervisionError(
                "required Docker result image identity was never observed",
                samples=samples,
            )
        if image_identity is not None:
            image_identity.validate()

        vhdx_values = tuple(
            sample.docker_desktop_vhdx_bytes
            for sample in samples
            if sample.docker_desktop_vhdx_bytes is not None
        )
        desktop_vhdx: DockerDesktopVhdxEvidence | None = None
        if vhdx_values:
            if len(vhdx_values) != len(samples):
                raise DockerSupervisionError(
                    "Docker Desktop VHDX result evidence is incomplete",
                    samples=samples,
                )
            baseline_bytes = vhdx_values[0]
            peak_bytes = max(vhdx_values)
            desktop_vhdx = DockerDesktopVhdxEvidence(
                baseline_bytes=baseline_bytes,
                peak_bytes=peak_bytes,
                final_bytes=vhdx_values[-1],
                peak_growth_bytes=peak_bytes - baseline_bytes,
            )
            desktop_vhdx.validate()

        seccomp_values = {
            DockerSeccompEvidence(
                profile_kind=(
                    "custom" if fact.seccomp_profile_sha256 is not None else "builtin"
                ),
                profile_sha256=fact.seccomp_profile_sha256,
            )
            for fact in facts
        }
        if len(seccomp_values) > 1:
            raise DockerSupervisionError(
                "Docker result seccomp identity changed",
                samples=samples,
            )
        effective_seccomp = next(iter(seccomp_values), None)
        if effective_seccomp is not None:
            effective_seccomp.validate()

        return (
            image_identity,
            desktop_vhdx,
            cls._result_container_metrics(contract, samples),
            effective_seccomp,
        )

    @staticmethod
    def _stop(handle: RunningCommand, *, close_group: bool) -> bool:
        if close_group:
            try:
                if handle.close_process_group(SAMPLE_INTERVAL_SECONDS):
                    return True
            except Exception:
                pass
        try:
            handle.terminate()
            if handle.wait(SAMPLE_INTERVAL_SECONDS) is not None:
                return not close_group
        except Exception:
            pass
        try:
            handle.kill()
        except Exception:
            return False
        return not close_group


def _require_pinned_image(image: str) -> None:
    if not (_SHA256_IMAGE.fullmatch(image) or _LOCAL_IMAGE_ID.fullmatch(image)):
        raise DockerSupervisionError("Docker image must be pinned by sha256 digest")


def _require_registry_pinned_image(image: str) -> None:
    if not _SHA256_IMAGE.fullmatch(image):
        raise DockerSupervisionError(
            "Docker pull requires a registry image pinned by sha256 digest"
        )


def _require_cli_value(value: str, label: str) -> None:
    if not value or value.startswith("-") or "\x00" in value or "\n" in value or "\r" in value:
        raise DockerSupervisionError(f"{label} is invalid")


def _validated_command(command: Sequence[str]) -> tuple[str, ...]:
    result = tuple(command)
    for value in result:
        if not isinstance(value, str) or "\x00" in value:
            raise DockerSupervisionError("Docker container command is invalid")
    return result


def _validate_diagnostic_argv(
    argv: tuple[str, ...],
    identity: DockerTaskIdentity,
    limits: DockerLimits,
) -> None:
    if argv[:3] != ("docker", "container", "run"):
        raise DockerSupervisionError("diagnostic must use docker container run")
    required_pairs = (
        ("--name", identity.container_name),
        ("--user", "1000:1000"),
        ("--cap-drop", "ALL"),
        ("--memory", str(limits.memory_bytes)),
        ("--memory-swap", str(limits.memory_swap_bytes)),
        ("--pids-limit", str(limits.pids_limit)),
        ("--network", "none"),
    )
    for option, expected in required_pairs:
        positions = [index for index, value in enumerate(argv) if value == option]
        if len(positions) != 1 or positions[0] + 1 >= len(argv) or argv[positions[0] + 1] != expected:
            raise DockerSupervisionError("diagnostic Docker argv differs from its fixed contract")
    label_positions = [index for index, value in enumerate(argv) if value == "--label"]
    if any(index + 1 >= len(argv) for index in label_positions):
        raise DockerSupervisionError("diagnostic Docker labels are incomplete")
    labels = tuple(argv[index + 1] for index in label_positions)
    project_labels = tuple(
        value
        for value in labels
        if re.fullmatch(r"com\.docker\.compose\.project=rondodiag-[0-9a-f]{16}", value)
    )
    profile_labels = tuple(
        value
        for value in labels
        if re.fullmatch(r"dev\.rondo\.eval\.seccomp-profile-sha256=[0-9a-f]{64}", value)
    )
    expected_labels = {
        identity.label,
        "com.docker.compose.service=main",
        *project_labels,
        *profile_labels,
    }
    if (
        len(project_labels) != 1
        or len(profile_labels) > 1
        or len(labels) != 3 + len(profile_labels)
        or len(set(labels)) != len(labels)
        or set(labels) != expected_labels
    ):
        raise DockerSupervisionError("diagnostic Docker labels differ from its fixed contract")
    if argv.count("--rm") != 1 or argv.count("--read-only") != 1:
        raise DockerSupervisionError("diagnostic Docker lifecycle is not fixed")
    lowered = tuple(value.casefold() for value in argv)
    if (
        "--privileged" in lowered
        or "--cap-add" in lowered
        or "seccomp=unconfined" in lowered
        or "sys_admin" in lowered
        or "--detach" in lowered
        or "-d" in lowered
    ):
        raise DockerSupervisionError("diagnostic Docker argv requests forbidden privilege")


def _verified_frozen_binary(host_binary: Path, expected_sha256: str) -> Path:
    if not isinstance(host_binary, Path) or not host_binary.is_absolute():
        raise DockerSupervisionError("frozen host binary path must be absolute")
    raw_path = os.fspath(host_binary)
    if "," in raw_path or any(
        unicodedata.category(character) == "Cc" for character in raw_path
    ):
        raise DockerSupervisionError("frozen host binary path is unsafe for Docker mount")
    if not isinstance(expected_sha256, str) or not _SHA256.fullmatch(expected_sha256):
        raise DockerSupervisionError("frozen host binary sha256 is invalid")
    try:
        resolved = host_binary.resolve(strict=True)
        if resolved != host_binary:
            raise DockerSupervisionError("frozen host binary path contains a symlink")
        path_stat = host_binary.lstat()
        if stat.S_ISLNK(path_stat.st_mode) or not stat.S_ISREG(path_stat.st_mode):
            raise DockerSupervisionError("frozen host binary must be a regular non-symlink")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(host_binary, flags)
    except DockerSupervisionError:
        raise
    except (OSError, ValueError) as exc:
        raise DockerSupervisionError("frozen host binary is unavailable") from exc

    digest = hashlib.sha256()
    try:
        with os.fdopen(descriptor, "rb", closefd=True) as binary:
            opened_stat = os.fstat(binary.fileno())
            if not stat.S_ISREG(opened_stat.st_mode) or (
                opened_stat.st_dev,
                opened_stat.st_ino,
            ) != (path_stat.st_dev, path_stat.st_ino):
                raise DockerSupervisionError("frozen host binary changed before hashing")
            while chunk := binary.read(1024 * 1024):
                digest.update(chunk)
            final_opened_stat = os.fstat(binary.fileno())
    except DockerSupervisionError:
        raise
    except OSError as exc:
        raise DockerSupervisionError("frozen host binary could not be hashed") from exc

    try:
        final_path_stat = host_binary.lstat()
    except OSError as exc:
        raise DockerSupervisionError("frozen host binary changed after hashing") from exc
    stable_fields = ("st_dev", "st_ino", "st_mode", "st_size", "st_mtime_ns", "st_ctime_ns")
    if any(
        getattr(final_opened_stat, field) != getattr(final_path_stat, field)
        for field in stable_fields
    ):
        raise DockerSupervisionError("frozen host binary changed while hashing")
    if not hmac.compare_digest(digest.hexdigest(), expected_sha256):
        raise DockerSupervisionError("frozen host binary sha256 mismatch")
    return resolved
