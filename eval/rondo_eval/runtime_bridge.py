"""Production adapters for the eval runtime's injected process interfaces.

Nothing in this module starts a process at import time.  The watchdog proof is
also intentionally independent from Docker so the same lease can guard any
heavy local operation that is launched by ``with-build-lock.sh``.
"""

from __future__ import annotations

import json
import errno
import fcntl
import hashlib
import os
import re
import secrets
import signal
import stat
import subprocess
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping, Protocol, Sequence

if TYPE_CHECKING:
    from .docker_supervisor import (
        ComposeRunContract,
        DockerCounterReading,
        DockerImageIdentity,
        DockerOperation,
        DockerTaskIdentity,
    )


_WATCHDOG_SCOPE = re.compile(r"rondo-build-[0-9]+-[0-9]+-[0-9]+[.]scope\Z")
_OBJECT_ID = re.compile(r"(?:sha256:)?([0-9a-f]{64})\Z")
_REQUIRED_CGROUP_COUNTERS = (
    "cgroup.events",
    "cgroup.procs",
    "memory.current",
    "memory.peak",
    "memory.stat",
    "memory.swap.current",
    "memory.swap.peak",
    "memory.pressure",
    "memory.events",
    "memory.high",
    "memory.max",
    "memory.swap.max",
)
_DEFAULT_MEMORY_HIGH_BYTES = 19 * 1024**3
_DEFAULT_MEMORY_MAX_BYTES = 21 * 1024**3
_DEFAULT_SWAP_MAX_BYTES = 5 * 1024**3
_WATCHDOG_HEARTBEAT_MAX_AGE_NS = 15_000_000_000
# WSL's wall clock can step backwards while the wrapper is refreshing this
# mtime.  Treat an equally bounded future timestamp as fresh; PID/start-ticks,
# script, inode, lock, and cgroup identity checks still have to match.
_WATCHDOG_HEARTBEAT_FUTURE_TOLERANCE_NS = _WATCHDOG_HEARTBEAT_MAX_AGE_NS
_DOCKER_FACT_COMMAND_MAX_ATTEMPTS = 2
_DOCKER_FACT_COMMAND_RETRY_DELAY_SECONDS = 1.0
_WATCHDOG_ENV = (
    "RONDO_WATCHDOG_WRAPPER_PID",
    "RONDO_WATCHDOG_WRAPPER_START_TICKS",
    "RONDO_WATCHDOG_HEARTBEAT_PATH",
    "RONDO_WATCHDOG_SCRIPT_PATH",
)
_DF_TYPES = ("Images", "Containers", "Local Volumes", "Build Cache")
_SIZE = re.compile(r"([0-9]+(?:[.][0-9]+)?)(B|kB|MB|GB|TB|PB|KiB|MiB|GiB|TiB|PiB)\Z")
_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*\Z")
_RESOURCE_NAME = re.compile(r"[0-9A-Za-z][0-9A-Za-z_.-]{0,127}\Z")
_SHA256_IMAGE = re.compile(r"[^\s]+@sha256:[0-9a-f]{64}\Z")
_CONTAINER_CGROUP_METRIC_SCRIPT = """
cpu_usage_usec=
while read -r key value rest; do
  if [ "$key" = usage_usec ]; then cpu_usage_usec="$value"; fi
done < /sys/fs/cgroup/cpu.stat
IFS= read -r memory_peak_bytes < /sys/fs/cgroup/memory.peak
case "$cpu_usage_usec" in ''|*[!0-9]*) exit 70;; esac
case "$memory_peak_bytes" in ''|*[!0-9]*) exit 70;; esac
printf 'cpu_usage_microseconds=%s\\npeak_memory_bytes=%s\\n' "$cpu_usage_usec" "$memory_peak_bytes"
""".strip()
_SIZE_FACTORS = {
    "B": 1,
    "kB": 1_000,
    "MB": 1_000**2,
    "GB": 1_000**3,
    "TB": 1_000**4,
    "PB": 1_000**5,
    "KiB": 1024,
    "MiB": 1024**2,
    "GiB": 1024**3,
    "TiB": 1024**4,
    "PiB": 1024**5,
}


class RuntimeBridgeError(RuntimeError):
    """Fail-closed infrastructure error with a deliberately redacted message."""

    def __init__(
        self,
        message: str,
        *,
        failed_probe: str | None = None,
        probe_timings_ms: Sequence[tuple[str, int]] = (),
    ) -> None:
        super().__init__(message)
        self.failed_probe = failed_probe
        self.probe_timings_ms = tuple(probe_timings_ms)


@dataclass(frozen=True)
class WatchdogLease:
    """Opaque proof that was minted for the current supervised process."""

    token: str
    held: bool = True

    def validate(self) -> None:
        if not self.held or not re.fullmatch(r"[0-9a-f]{48}", self.token):
            raise RuntimeBridgeError("watchdog lease is invalid")


@dataclass(frozen=True)
class WatchdogProof:
    """Lease and its live guard, suitable for any heavy-operation entrypoint."""

    lease: WatchdogLease
    guard: "CgroupWatchdogGuard"


@dataclass(frozen=True)
class MachineWatchdogIdentity:
    common_root: Path
    checkout_root: Path
    root_device: int
    root_inode: int
    metrics_root: Path | None
    cargo_target: Path | None
    watcher: "WatcherProcessIdentity"


@dataclass(frozen=True)
class WatcherProcessIdentity:
    pid: int
    start_ticks: int
    heartbeat_path: Path
    heartbeat_device: int
    heartbeat_inode: int
    script_path: Path


class CgroupWatchdogGuard:
    """Revalidates the same cgroup and all required counters on every check."""

    def __init__(
        self,
        *,
        token: str,
        proc_cgroup_path: Path,
        cgroup_fs_root: Path,
        relative_cgroup: str,
        cgroup_directory: Path,
        pid: int,
        lock_path: Path,
        lock_identity: tuple[int, int],
        machine_identity: MachineWatchdogIdentity,
        watcher_proc_root: Path,
        watchdog_environment: Mapping[str, str] | None,
        heartbeat_clock_ns: Callable[[], int],
    ) -> None:
        self._token = token
        self._proc_cgroup_path = proc_cgroup_path
        self._cgroup_fs_root = cgroup_fs_root
        self._relative_cgroup = relative_cgroup
        self._cgroup_directory = cgroup_directory
        self._pid = pid
        self._lock_path = lock_path
        self._lock_identity = lock_identity
        self._machine_identity = machine_identity
        self._watcher_proc_root = watcher_proc_root
        self._watchdog_environment = watchdog_environment
        self._heartbeat_clock_ns = heartbeat_clock_ns

    def is_held(self, lease: object) -> bool:
        try:
            token = getattr(lease, "token")
            held = getattr(lease, "held")
            if held is not True or not secrets.compare_digest(token, self._token):
                return False
            relative = _read_process_cgroup(self._proc_cgroup_path)
            if relative != self._relative_cgroup:
                return False
            current_directory = _resolve_cgroup_directory(
                self._cgroup_fs_root,
                relative,
            )
            if current_directory != self._cgroup_directory:
                return False
            _read_required_cgroup_counters(current_directory, self._pid)
            if _canonical_lock_is_held(self._lock_path) != self._lock_identity:
                return False
            if _machine_watchdog_identity(
                watcher_proc_root=self._watcher_proc_root,
                watchdog_environment=self._watchdog_environment,
                heartbeat_clock_ns=self._heartbeat_clock_ns,
            ) != self._machine_identity:
                return False
            return True
        except (AttributeError, OSError, RuntimeBridgeError, TypeError):
            return False


def lease_from_watchdog(
    *,
    proc_cgroup_path: Path = Path("/proc/self/cgroup"),
    cgroup_fs_root: Path = Path("/sys/fs/cgroup"),
    watcher_proc_root: Path = Path("/proc"),
    watchdog_environment: Mapping[str, str] | None = None,
    heartbeat_clock_ns: Callable[[], int] = time.time_ns,
) -> WatchdogProof:
    """Mint a lease only when this process is inside a live RONDO scope.

    The injectable paths exist solely for hermetic tests.  Cgroup membership
    is always proved for the calling process itself.
    """

    pid = os.getpid()
    try:
        machine_identity = _machine_watchdog_identity(
            watcher_proc_root=watcher_proc_root,
            watchdog_environment=watchdog_environment,
            heartbeat_clock_ns=heartbeat_clock_ns,
        )
        lock_path = _canonical_lock_path(os.getuid())
        lock_identity = _canonical_lock_is_held(lock_path)
        root = cgroup_fs_root.resolve(strict=True)
        relative = _read_process_cgroup(proc_cgroup_path)
        directory = _resolve_cgroup_directory(root, relative)
        _read_required_cgroup_counters(directory, pid)
    except (OSError, RuntimeBridgeError) as exc:
        raise RuntimeBridgeError("current process has no usable RONDO watchdog scope") from exc

    token = secrets.token_hex(24)
    guard = CgroupWatchdogGuard(
        token=token,
        proc_cgroup_path=proc_cgroup_path,
        cgroup_fs_root=root,
        relative_cgroup=relative,
        cgroup_directory=directory,
        pid=pid,
        lock_path=lock_path,
        lock_identity=lock_identity,
        machine_identity=machine_identity,
        watcher_proc_root=watcher_proc_root,
        watchdog_environment=watchdog_environment,
        heartbeat_clock_ns=heartbeat_clock_ns,
    )
    lease = WatchdogLease(token=token)
    if guard.is_held(lease) is not True:
        raise RuntimeBridgeError("current process has no usable RONDO watchdog scope")
    return WatchdogProof(lease=lease, guard=guard)


def _read_process_cgroup(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    matches: list[str] = []
    for line in text.splitlines():
        fields = line.split(":", 2)
        if len(fields) == 3 and fields[0] == "0" and fields[1] == "":
            matches.append(fields[2])
    if len(matches) != 1:
        raise RuntimeBridgeError("cgroup v2 membership is unavailable")
    relative = matches[0]
    if not relative.startswith("/") or "\x00" in relative:
        raise RuntimeBridgeError("cgroup v2 membership is invalid")
    if not _WATCHDOG_SCOPE.fullmatch(Path(relative).name):
        raise RuntimeBridgeError("process is outside a RONDO watchdog scope")
    return relative


def _resolve_cgroup_directory(root: Path, relative: str) -> Path:
    candidate = (root / relative.lstrip("/")).resolve(strict=True)
    if candidate == root or not candidate.is_relative_to(root):
        raise RuntimeBridgeError("watchdog cgroup path escapes cgroup fs")
    if not candidate.is_dir() or not _WATCHDOG_SCOPE.fullmatch(candidate.name):
        raise RuntimeBridgeError("watchdog cgroup directory is invalid")
    return candidate


def _read_required_cgroup_counters(directory: Path, pid: int) -> None:
    values = {
        name: (directory / name).read_text(encoding="ascii")
        for name in _REQUIRED_CGROUP_COUNTERS
    }
    events = _parse_keyed_uints(values["cgroup.events"])
    if events.get("populated") != 1:
        raise RuntimeBridgeError("watchdog cgroup is not populated")
    procs = values["cgroup.procs"].splitlines()
    if str(pid) not in procs or any(not item.isascii() or not item.isdigit() for item in procs):
        raise RuntimeBridgeError("current process is not a watchdog cgroup member")
    for name in (
        "memory.current",
        "memory.peak",
        "memory.swap.current",
        "memory.swap.peak",
    ):
        _parse_uint(values[name])
    expected_limits = {
        "memory.high": _DEFAULT_MEMORY_HIGH_BYTES,
        "memory.max": _DEFAULT_MEMORY_MAX_BYTES,
        "memory.swap.max": _DEFAULT_SWAP_MAX_BYTES,
    }
    if any(_parse_uint(values[name]) != expected for name, expected in expected_limits.items()):
        raise RuntimeBridgeError("watchdog cgroup limits differ from project defaults")
    for name in ("memory.stat", "memory.events"):
        if not _parse_keyed_uints(values[name]):
            raise RuntimeBridgeError("watchdog keyed counter is invalid")
    _parse_pressure(values["memory.pressure"])


def _reject_watchdog_overrides(common_root: Path) -> tuple[Path | None, Path | None]:
    allowed = {"RONDO_BUILD_METRICS_DIR"}
    if any(
        name.startswith("RONDO_BUILD_") and name not in allowed
        for name in os.environ
    ):
        raise RuntimeBridgeError("watchdog overrides are forbidden for production proof")
    project_override = os.environ.get("RONDO_PROJECT_ROOT")
    if project_override is not None and _project_path(project_override) != common_root:
        raise RuntimeBridgeError("watchdog project root differs from RONDO common root")
    metrics_root = _optional_project_directory(
        os.environ.get("RONDO_BUILD_METRICS_DIR"), common_root, "watchdog metrics root"
    )
    cargo_target = _optional_project_directory(
        os.environ.get("CARGO_TARGET_DIR"), common_root, "Cargo target root"
    )
    return metrics_root, cargo_target


def _machine_watchdog_identity(
    *,
    watcher_proc_root: Path = Path("/proc"),
    watchdog_environment: Mapping[str, str] | None = None,
    heartbeat_clock_ns: Callable[[], int] = time.time_ns,
) -> MachineWatchdogIdentity:
    module_checkout = _repository_checkout_root(Path(__file__).resolve(strict=True))
    current_checkout = _repository_checkout_root(Path.cwd().resolve(strict=True))
    module_root = _repository_common_root(module_checkout)
    current_root = _repository_common_root(current_checkout)
    if module_root != current_root or module_checkout != current_checkout:
        raise RuntimeBridgeError("watchdog process is outside the RONDO common root")
    root_stat = module_root.stat()
    metrics_root, cargo_target = _reject_watchdog_overrides(module_root)
    watcher = _watcher_process_identity(
        common_root=module_root,
        expected_script=(
            module_checkout / "mydev" / "scripts" / "with-build-lock.sh"
        ),
        proc_root=watcher_proc_root,
        environment=(os.environ if watchdog_environment is None else watchdog_environment),
        heartbeat_clock_ns=heartbeat_clock_ns,
    )
    return MachineWatchdogIdentity(
        common_root=module_root,
        checkout_root=module_checkout,
        root_device=root_stat.st_dev,
        root_inode=root_stat.st_ino,
        metrics_root=metrics_root,
        cargo_target=cargo_target,
        watcher=watcher,
    )


def _watcher_process_identity(
    *,
    common_root: Path,
    expected_script: Path,
    proc_root: Path,
    environment: Mapping[str, str],
    heartbeat_clock_ns: Callable[[], int],
) -> WatcherProcessIdentity:
    values = {name: environment.get(name) for name in _WATCHDOG_ENV}
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise RuntimeBridgeError("watchdog liveness environment is incomplete")
    try:
        pid = _parse_uint(values["RONDO_WATCHDOG_WRAPPER_PID"] or "")
        start_ticks = _parse_uint(
            values["RONDO_WATCHDOG_WRAPPER_START_TICKS"] or ""
        )
    except RuntimeBridgeError as exc:
        raise RuntimeBridgeError("watchdog process identity is invalid") from exc
    if pid <= 1 or start_ticks <= 0:
        raise RuntimeBridgeError("watchdog process identity is invalid")

    script_value = values["RONDO_WATCHDOG_SCRIPT_PATH"] or ""
    heartbeat_value = values["RONDO_WATCHDOG_HEARTBEAT_PATH"] or ""
    script_path = _project_path(script_value)
    canonical_expected_script = expected_script.resolve(strict=True)
    if script_path != canonical_expected_script:
        raise RuntimeBridgeError("watchdog script differs from the active RONDO checkout")
    script_stat = script_path.lstat()
    if (
        stat.S_ISLNK(script_stat.st_mode)
        or not stat.S_ISREG(script_stat.st_mode)
        or not os.access(script_path, os.X_OK)
    ):
        raise RuntimeBridgeError("watchdog script is unavailable")

    heartbeat_path = Path(heartbeat_value)
    if (
        not heartbeat_path.is_absolute()
        or Path(os.path.normpath(heartbeat_value)) != heartbeat_path
        or heartbeat_path.name != "watchdog-heartbeat"
    ):
        raise RuntimeBridgeError("watchdog heartbeat path is invalid")
    heartbeat_parent = heartbeat_path.parent
    parent_stat = heartbeat_parent.lstat()
    heartbeat_stat = heartbeat_path.lstat()
    if (
        stat.S_ISLNK(parent_stat.st_mode)
        or not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_uid != os.getuid()
        or stat.S_IMODE(parent_stat.st_mode) != 0o700
        or stat.S_ISLNK(heartbeat_stat.st_mode)
        or not stat.S_ISREG(heartbeat_stat.st_mode)
        or heartbeat_stat.st_uid != os.getuid()
        or stat.S_IMODE(heartbeat_stat.st_mode) != 0o600
    ):
        raise RuntimeBridgeError("watchdog heartbeat path is unsafe")
    resolved_heartbeat = heartbeat_path.resolve(strict=True)
    if not resolved_heartbeat.is_relative_to(common_root):
        raise RuntimeBridgeError("watchdog heartbeat is outside RONDO common root")
    now_ns = heartbeat_clock_ns()
    if isinstance(now_ns, bool) or not isinstance(now_ns, int) or now_ns < 0:
        raise RuntimeBridgeError("watchdog heartbeat clock is unavailable")
    age_ns = now_ns - heartbeat_stat.st_mtime_ns
    if (
        age_ns < -_WATCHDOG_HEARTBEAT_FUTURE_TOLERANCE_NS
        or age_ns > _WATCHDOG_HEARTBEAT_MAX_AGE_NS
    ):
        raise RuntimeBridgeError("watchdog heartbeat is stale")

    proc_directory = proc_root / str(pid)
    process_start_ticks, process_state = _read_process_stat(
        proc_directory / "stat", pid
    )
    if process_start_ticks != start_ticks or process_state in {"Z", "X", "x"}:
        raise RuntimeBridgeError("watchdog process identity changed")
    cmdline = _read_bounded_bytes(proc_directory / "cmdline", 65_536)
    arguments = tuple(value for value in cmdline.split(b"\0") if value)
    if os.fsencode(script_path) not in arguments:
        raise RuntimeBridgeError("watchdog process is not the canonical wrapper")

    return WatcherProcessIdentity(
        pid=pid,
        start_ticks=start_ticks,
        heartbeat_path=resolved_heartbeat,
        heartbeat_device=heartbeat_stat.st_dev,
        heartbeat_inode=heartbeat_stat.st_ino,
        script_path=script_path,
    )


def _read_process_stat(path: Path, expected_pid: int) -> tuple[int, str]:
    try:
        payload = _read_bounded_bytes(path, 4096).decode("ascii")
    except UnicodeError as exc:
        raise RuntimeBridgeError("watchdog process stat is invalid") from exc
    closing = payload.rfind(")")
    prefix = f"{expected_pid} ("
    if (
        not payload.startswith(prefix)
        or closing < len(prefix)
        or payload[closing + 1:closing + 2] != " "
    ):
        raise RuntimeBridgeError("watchdog process stat is invalid")
    fields = payload[closing + 2:].split()
    if len(fields) < 20 or len(fields[0]) != 1:
        raise RuntimeBridgeError("watchdog process stat is incomplete")
    return _parse_uint(fields[19]), fields[0]


def _read_bounded_bytes(path: Path, limit: int) -> bytes:
    try:
        with path.open("rb") as handle:
            payload = handle.read(limit + 1)
    except OSError as exc:
        raise RuntimeBridgeError("watchdog process evidence is unavailable") from exc
    if not payload or len(payload) > limit:
        raise RuntimeBridgeError("watchdog process evidence is invalid")
    return payload


def _project_path(value: str) -> Path:
    if not value or "\x00" in value:
        raise RuntimeBridgeError("watchdog project path is invalid")
    path = Path(value)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        return path.resolve(strict=True)
    except OSError as exc:
        raise RuntimeBridgeError("watchdog project path is unavailable") from exc


def _optional_project_directory(
    value: str | None,
    common_root: Path,
    label: str,
) -> Path | None:
    if value is None:
        return None
    raw_path = Path(value)
    if not raw_path.is_absolute():
        raw_path = Path.cwd() / raw_path
    try:
        raw_stat = raw_path.lstat()
    except OSError as exc:
        raise RuntimeBridgeError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(raw_stat.st_mode):
        raise RuntimeBridgeError(f"{label} is unsafe")
    resolved = _project_path(value)
    try:
        path_stat = resolved.lstat()
    except OSError as exc:
        raise RuntimeBridgeError(f"{label} is unavailable") from exc
    if (
        stat.S_ISLNK(path_stat.st_mode)
        or not stat.S_ISDIR(path_stat.st_mode)
        or not resolved.is_relative_to(common_root)
        or resolved == common_root
    ):
        raise RuntimeBridgeError(f"{label} must be a directory inside RONDO common root")
    return resolved


def _repository_common_root(start: Path) -> Path:
    checkout = _repository_checkout_root(start)
    git_entry = checkout / ".git"
    entry_stat = git_entry.lstat()
    if stat.S_ISLNK(entry_stat.st_mode):
        raise RuntimeBridgeError("RONDO Git metadata path is unsafe")
    if stat.S_ISDIR(entry_stat.st_mode):
        git_directory = git_entry.resolve(strict=True)
    elif stat.S_ISREG(entry_stat.st_mode):
        line = git_entry.read_text(encoding="utf-8").strip()
        prefix = "gitdir: "
        if not line.startswith(prefix) or "\n" in line or "\x00" in line:
            raise RuntimeBridgeError("RONDO worktree metadata is invalid")
        raw_git_directory = Path(line[len(prefix):])
        if not raw_git_directory.is_absolute():
            raw_git_directory = checkout / raw_git_directory
        git_directory = raw_git_directory.resolve(strict=True)
    else:
        raise RuntimeBridgeError("RONDO Git metadata path is invalid")
    common_pointer = git_directory / "commondir"
    if common_pointer.exists():
        pointer_stat = common_pointer.lstat()
        if stat.S_ISLNK(pointer_stat.st_mode) or not stat.S_ISREG(pointer_stat.st_mode):
            raise RuntimeBridgeError("RONDO common metadata pointer is unsafe")
        raw_common = Path(common_pointer.read_text(encoding="utf-8").strip())
        common_git = (git_directory / raw_common).resolve(strict=True)
    else:
        common_git = git_directory
    if common_git.name != ".git" or not common_git.is_dir():
        raise RuntimeBridgeError("RONDO Git common directory is invalid")
    return common_git.parent.resolve(strict=True)


def _repository_checkout_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate.resolve(strict=True)
    raise RuntimeBridgeError("RONDO Git checkout root is unavailable")


def _canonical_lock_path(uid: int) -> Path:
    runtime = Path(f"/run/user/{uid}")
    try:
        runtime_stat = runtime.lstat()
    except OSError:
        runtime = Path(f"/tmp/rondo-runtime-{uid}")
        try:
            runtime_stat = runtime.lstat()
        except OSError as exc:
            raise RuntimeBridgeError("canonical watchdog runtime directory is unavailable") from exc
    if (
        stat.S_ISLNK(runtime_stat.st_mode)
        or not stat.S_ISDIR(runtime_stat.st_mode)
        or runtime_stat.st_uid != uid
        or runtime_stat.st_mode & 0o077 != 0
    ):
        raise RuntimeBridgeError("canonical watchdog runtime directory is unsafe")
    return runtime / "rondo-cargo-build.lock"


def _canonical_lock_is_held(path: Path) -> tuple[int, int]:
    """Return stable lock identity only when another open description holds flock."""

    try:
        path_stat = path.lstat()
        if (
            stat.S_ISLNK(path_stat.st_mode)
            or not stat.S_ISREG(path_stat.st_mode)
            or path_stat.st_uid != os.getuid()
            or stat.S_IMODE(path_stat.st_mode) != 0o600
        ):
            raise RuntimeBridgeError("canonical watchdog lock file is unsafe")
        descriptor = os.open(path, os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    except RuntimeBridgeError:
        raise
    except OSError as exc:
        raise RuntimeBridgeError("canonical watchdog lock is unavailable") from exc
    try:
        opened = os.fstat(descriptor)
        if (opened.st_dev, opened.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            raise RuntimeBridgeError("canonical watchdog lock changed while opening")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise RuntimeBridgeError("canonical watchdog flock state is unreadable") from exc
        else:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            raise RuntimeBridgeError("canonical watchdog flock is not held")
        return (opened.st_dev, opened.st_ino)
    finally:
        os.close(descriptor)


def _parse_uint(value: str) -> int:
    stripped = value.strip()
    if not stripped.isascii() or not stripped.isdigit():
        raise RuntimeBridgeError("watchdog numeric counter is invalid")
    return int(stripped)


def _parse_keyed_uints(value: str) -> dict[str, int]:
    result: dict[str, int] = {}
    for line in value.splitlines():
        fields = line.split()
        if len(fields) != 2 or not fields[0].isascii() or not fields[0].replace("_", "").isalnum():
            raise RuntimeBridgeError("watchdog keyed counter is invalid")
        if fields[0] in result:
            raise RuntimeBridgeError("watchdog keyed counter is ambiguous")
        result[fields[0]] = _parse_uint(fields[1])
    return result


def _parse_pressure(value: str) -> None:
    kinds: set[str] = set()
    for line in value.splitlines():
        fields = line.split()
        if len(fields) < 2 or fields[0] not in {"some", "full"} or fields[0] in kinds:
            raise RuntimeBridgeError("watchdog pressure counter is invalid")
        kinds.add(fields[0])
        pairs: dict[str, str] = {}
        for field in fields[1:]:
            key, separator, item = field.partition("=")
            if separator != "=" or key in pairs:
                raise RuntimeBridgeError("watchdog pressure counter is invalid")
            pairs[key] = item
        if set(pairs) != {"avg10", "avg60", "avg300", "total"}:
            raise RuntimeBridgeError("watchdog pressure counter is incomplete")
        try:
            for key in ("avg10", "avg60", "avg300"):
                if not Decimal(pairs[key]).is_finite() or Decimal(pairs[key]) < 0:
                    raise RuntimeBridgeError("watchdog pressure counter is invalid")
        except InvalidOperation as exc:
            raise RuntimeBridgeError("watchdog pressure counter is invalid") from exc
        _parse_uint(pairs["total"])
    if kinds != {"some", "full"}:
        raise RuntimeBridgeError("watchdog pressure counter is incomplete")


def _sanitized_subprocess_env() -> dict[str, str]:
    allowed = (
        "PATH",
        "HOME",
        "DOCKER_HOST",
        "DOCKER_CONTEXT",
        "DOCKER_CONFIG",
        "XDG_RUNTIME_DIR",
    )
    result = {name: os.environ[name] for name in allowed if name in os.environ}
    result["LC_ALL"] = "C"
    return result


class PopenFactory(Protocol):
    def __call__(self, argv: Sequence[str], **kwargs: object) -> subprocess.Popen[str]: ...


class SubprocessCommandHandle:
    """Non-blocking handle matching ``docker_supervisor.RunningCommand``."""

    def __init__(
        self,
        process: subprocess.Popen[str],
        *,
        owns_process_group: bool = False,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        killpg: Callable[[int, int], None] = os.killpg,
    ) -> None:
        self._process = process
        self._process_group = process.pid if owns_process_group else None
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._killpg = killpg

    def wait(self, timeout_seconds: float) -> int | None:
        try:
            return self._process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            return None

    def terminate(self) -> None:
        self._process.terminate()

    def kill(self) -> None:
        self._process.kill()

    def close_process_group(self, timeout_seconds: float) -> bool:
        """Terminate and verify the dedicated host-harness process group."""

        if self._process_group is None or timeout_seconds <= 0:
            return False
        deadline = self._monotonic() + timeout_seconds
        midpoint = self._monotonic() + timeout_seconds / 2
        try:
            self._killpg(self._process_group, signal.SIGTERM)
        except ProcessLookupError:
            return True
        except OSError:
            return False
        while self._monotonic() < midpoint:
            if not self._process_group_exists():
                return True
            self._sleeper(min(0.05, midpoint - self._monotonic()))
        try:
            self._killpg(self._process_group, signal.SIGKILL)
        except ProcessLookupError:
            return True
        except OSError:
            return False
        while self._monotonic() < deadline:
            if not self._process_group_exists():
                return True
            self._sleeper(min(0.05, deadline - self._monotonic()))
        return not self._process_group_exists()

    def _process_group_exists(self) -> bool:
        assert self._process_group is not None
        # Reap an exited group leader before probing the process group.  A
        # zombie leader otherwise keeps killpg(..., 0) successful and makes a
        # completed cleanup look unverifiable until the parent later waits.
        self._process.poll()
        try:
            self._killpg(self._process_group, 0)
        except ProcessLookupError:
            return False
        except OSError:
            return True
        return True


class SubprocessDockerCommandRunner:
    """Run a Docker argv directly, without a shell or inherited secrets."""

    def __init__(self, *, popen: PopenFactory = subprocess.Popen) -> None:
        self._popen = popen

    def start(self, argv: tuple[str, ...]) -> SubprocessCommandHandle:
        _validate_argv(argv)
        if argv[0] != "docker":
            raise RuntimeBridgeError("Docker runner accepts only the Docker CLI")
        try:
            process = self._popen(
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                env=_sanitized_subprocess_env(),
                text=True,
            )
        except (OSError, ValueError) as exc:
            raise RuntimeBridgeError("Docker command could not be started") from exc
        return SubprocessCommandHandle(process)


class CapturingSubprocessCommandHandle(SubprocessCommandHandle):
    """Dedicated diagnostic handle with a small, post-exit stdout channel."""

    def __init__(self, process: subprocess.Popen[str], *, output_limit_bytes: int) -> None:
        super().__init__(process, owns_process_group=True)
        self._captured_process = process
        self._output_limit_bytes = output_limit_bytes

    def safe_output(self) -> str:
        if self._captured_process.poll() is None or self._captured_process.stdout is None:
            raise RuntimeBridgeError("diagnostic output requested before process exit")
        try:
            output = self._captured_process.stdout.read(self._output_limit_bytes + 1)
        except (OSError, UnicodeError) as exc:
            raise RuntimeBridgeError("diagnostic output is unreadable") from exc
        if len(output.encode("utf-8")) > self._output_limit_bytes:
            raise RuntimeBridgeError("diagnostic output exceeded its fixed limit")
        return output


class CapturingSubprocessDockerCommandRunner:
    """One-shot, secret-free Docker runner for the fixed diagnostic script."""

    def __init__(
        self,
        *,
        output_limit_bytes: int = 16 * 1024,
        popen: PopenFactory = subprocess.Popen,
    ) -> None:
        if output_limit_bytes <= 0:
            raise RuntimeBridgeError("diagnostic output limit must be positive")
        self._output_limit_bytes = output_limit_bytes
        self._popen = popen
        self._handle: CapturingSubprocessCommandHandle | None = None

    def start(self, argv: tuple[str, ...]) -> CapturingSubprocessCommandHandle:
        _validate_argv(argv)
        if argv[0] != "docker" or self._handle is not None:
            raise RuntimeBridgeError("diagnostic runner accepts one Docker command")
        try:
            process = self._popen(
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                env=_sanitized_subprocess_env(),
                start_new_session=True,
                text=True,
                encoding="utf-8",
                errors="strict",
            )
        except (OSError, ValueError) as exc:
            raise RuntimeBridgeError("diagnostic Docker command could not be started") from exc
        self._handle = CapturingSubprocessCommandHandle(
            process,
            output_limit_bytes=self._output_limit_bytes,
        )
        return self._handle

    def safe_output(self) -> str:
        if self._handle is None:
            raise RuntimeBridgeError("diagnostic Docker command was not started")
        return self._handle.safe_output()


class SubprocessHostCommandRunner:
    """Run one exact host harness without a shell or ambient secrets."""

    def __init__(
        self,
        *,
        executable: Path,
        cwd: Path,
        environment: Mapping[str, str],
        popen: PopenFactory = subprocess.Popen,
    ) -> None:
        try:
            resolved_executable = executable.resolve(strict=True)
            resolved_cwd = cwd.resolve(strict=True)
        except OSError as exc:
            raise RuntimeBridgeError("host harness path is unavailable") from exc
        if not resolved_executable.is_file() or not os.access(resolved_executable, os.X_OK):
            raise RuntimeBridgeError("host harness executable is invalid")
        if not resolved_cwd.is_dir():
            raise RuntimeBridgeError("host harness working directory is invalid")
        child_environment = _sanitized_subprocess_env()
        for name, value in environment.items():
            if not isinstance(name, str) or not _ENV_NAME.fullmatch(name):
                raise RuntimeBridgeError("host harness environment name is invalid")
            if not isinstance(value, str) or "\x00" in value:
                raise RuntimeBridgeError("host harness environment value is invalid")
            child_environment[name] = value
        self._executable = resolved_executable
        self._cwd = resolved_cwd
        self._environment = child_environment
        self._popen = popen

    def start(self, argv: tuple[str, ...]) -> SubprocessCommandHandle:
        _validate_argv(argv)
        try:
            requested = Path(argv[0]).resolve(strict=True)
        except OSError as exc:
            raise RuntimeBridgeError("host harness executable is unavailable") from exc
        if requested != self._executable:
            raise RuntimeBridgeError("host runner accepts only its frozen harness executable")
        try:
            process = self._popen(
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                cwd=self._cwd,
                env=dict(self._environment),
                start_new_session=True,
                text=True,
            )
        except (OSError, ValueError) as exc:
            raise RuntimeBridgeError("host harness could not be started") from exc
        return SubprocessCommandHandle(process, owns_process_group=True)


@dataclass(frozen=True)
class CommandOutput:
    returncode: int
    stdout: str


class CommandExecutor(Protocol):
    def run(self, argv: tuple[str, ...], *, timeout_seconds: float) -> CommandOutput: ...


class SubprocessCommandExecutor:
    """Synchronous executor for short, read-only Docker counter commands."""

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise RuntimeBridgeError("command timeout must be positive")
        self._timeout_seconds = timeout_seconds

    def run(
        self,
        argv: tuple[str, ...],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandOutput:
        _validate_argv(argv)
        if argv[0] != "docker":
            raise RuntimeBridgeError("counter executor accepts only the Docker CLI")
        effective_timeout = self._timeout_seconds
        if timeout_seconds is not None:
            if timeout_seconds <= 0:
                raise RuntimeBridgeError("counter command deadline expired")
            effective_timeout = min(effective_timeout, timeout_seconds)
        try:
            result = subprocess.run(
                argv,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                env=_sanitized_subprocess_env(),
                text=True,
                encoding="utf-8",
                errors="strict",
                timeout=effective_timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
            raise RuntimeBridgeError("Docker counter command failed") from exc
        if result.returncode != 0:
            raise RuntimeBridgeError("Docker counter command failed")
        return CommandOutput(returncode=result.returncode, stdout=result.stdout)


class DockerCliCounter:
    """Fresh Docker and host storage facts for one exact eval task label."""

    def __init__(
        self,
        *,
        host_data_root: Path,
        executor: CommandExecutor | None = None,
        desktop_host_probe: "DockerDesktopHostProbe | None" = None,
        mountinfo_path: Path = Path("/proc/self/mountinfo"),
        statvfs: Callable[[os.PathLike[str]], os.statvfs_result] = os.statvfs,
        monotonic: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
        probe_timeout_seconds: float = 30.0,
    ) -> None:
        if not host_data_root.is_absolute() or probe_timeout_seconds <= 0:
            raise RuntimeBridgeError("Docker host data root must be absolute")
        self._host_data_root = host_data_root
        self._executor = executor or SubprocessCommandExecutor()
        self._desktop_host_probe = desktop_host_probe
        self._mountinfo_path = mountinfo_path
        self._statvfs = statvfs
        self._monotonic = monotonic
        self._sleeper = sleeper
        self._probe_timeout_seconds = probe_timeout_seconds

    def sample(
        self,
        *,
        identity: "DockerTaskIdentity",
        operation: "DockerOperation",
        compose_contract: "ComposeRunContract | None" = None,
        deadline: float | None = None,
    ) -> "DockerCounterReading":
        del operation
        identity.validate()
        if deadline is None:
            deadline = self._monotonic() + self._probe_timeout_seconds
        if compose_contract is not None:
            compose_contract.validate()
        probe_timings_ms: dict[str, int] = {}

        def probe(name: str, operation: Callable[[], object]) -> object:
            started = self._monotonic()
            try:
                result = operation()
            except Exception as exc:
                elapsed_ms = max(0, int((self._monotonic() - started) * 1000))
                probe_timings_ms[name] = probe_timings_ms.get(name, 0) + elapsed_ms
                message = str(exc) if isinstance(exc, RuntimeBridgeError) else "Docker probe failed"
                raise RuntimeBridgeError(
                    message,
                    failed_probe=name,
                    probe_timings_ms=tuple(sorted(probe_timings_ms.items())),
                ) from None
            elapsed_ms = max(0, int((self._monotonic() - started) * 1000))
            probe_timings_ms[name] = probe_timings_ms.get(name, 0) + elapsed_ms
            return result

        try:
            docker_df, total_bytes = probe(
                "docker_system_df",
                lambda: _parse_system_df(
                    self._run(
                        ("docker", "system", "df", "--format", "{{json .}}"),
                        deadline=deadline,
                    )
                ),
            )
            daemon_root, operating_system, security_options = probe(
                "docker_info",
                lambda: _parse_docker_info(
                    self._run(
                        (
                            "docker",
                            "info",
                            "--format",
                            "[{{json .DockerRootDir}},{{json .OperatingSystem}},{{json .SecurityOptions}}]",
                        ),
                        deadline=deadline,
                    )
                ),
            )
            desktop_reading: DockerDesktopHostReading | None = None
            if "docker desktop" in operating_system.casefold() and self._desktop_host_probe:
                desktop_reading = probe(
                    "docker_desktop_host",
                    lambda: self._desktop_host_probe.sample(
                        timeout_seconds=self._remaining(deadline)
                    ),
                )
                assert isinstance(desktop_reading, DockerDesktopHostReading)
                desktop_reading.validate()
                host_root = self._host_data_root.resolve(strict=True)
                if host_root != desktop_reading.host_volume_root.resolve(strict=True):
                    raise RuntimeBridgeError("Docker Desktop host volume does not match configuration")
            else:
                host_root = _validate_host_data_root(
                    self._host_data_root,
                    daemon_root=daemon_root,
                    operating_system=operating_system,
                    mountinfo_path=self._mountinfo_path,
                )
            filter_args = identity.exact_label_filter
            container_ids = probe(
                "docker_container_list",
                lambda: self._container_ids(identity, deadline=deadline),
            )
            assert isinstance(container_ids, tuple)
            image_ids = probe(
                "docker_image_list",
                lambda: _parse_id_lines(
                    self._run(
                        (
                            "docker",
                            "image",
                            "ls",
                            "--no-trunc",
                            *filter_args,
                            "--format",
                            "{{json .ID}}",
                        ),
                        deadline=deadline,
                    )
                ),
            )
            assert isinstance(image_ids, tuple)
            container_result = probe(
                "docker_container_inspect",
                lambda: self._container_facts(
                    identity,
                    container_ids,
                    deadline=deadline,
                ),
            )
            assert isinstance(container_result, tuple)
            container_ids, container_bytes, container_facts = container_result
            container_metrics: tuple[object, ...] = ()
            if compose_contract is not None and compose_contract.container.require_container_metrics:
                metric_result = probe(
                    "docker_container_metrics",
                    lambda: self._container_metrics_with_disappearance(
                        identity,
                        container_ids,
                        container_facts,
                        deadline=deadline,
                    ),
                )
                assert isinstance(metric_result, tuple)
                container_ids, container_facts, container_metrics = metric_result
                assert isinstance(container_metrics, tuple)
            image_bytes = probe(
                "docker_image_inspect",
                lambda: self._image_bytes(identity, image_ids, deadline=deadline),
            )
            assert isinstance(image_bytes, int)
            network_facts: tuple[object, ...] = ()
            volume_facts: tuple[object, ...] = ()
            if compose_contract is not None:
                network_facts = probe(
                    "docker_network_inspect",
                    lambda: self._compose_networks(
                        compose_contract.container.compose_project,
                        deadline=deadline,
                    ),
                )
                assert isinstance(network_facts, tuple)
                volume_facts = probe(
                    "docker_volume_inspect",
                    lambda: self._compose_volumes(
                        compose_contract.container.compose_project,
                        deadline=deadline,
                    ),
                )
                assert isinstance(volume_facts, tuple)
            if desktop_reading is not None:
                free_bytes = desktop_reading.free_bytes
            else:
                filesystem = probe(
                    "docker_host_filesystem",
                    lambda: self._statvfs(host_root),
                )
                free_bytes = filesystem.f_bavail * filesystem.f_frsize
            if isinstance(free_bytes, bool) or not isinstance(free_bytes, int) or free_bytes < 0:
                raise RuntimeBridgeError("Docker host filesystem counter is invalid")
        except RuntimeBridgeError as exc:
            if exc.probe_timings_ms:
                raise
            raise RuntimeBridgeError(
                str(exc),
                failed_probe=exc.failed_probe,
                probe_timings_ms=tuple(sorted(probe_timings_ms.items())),
            ) from exc
        except (OSError, TypeError, ValueError) as exc:
            raise RuntimeBridgeError(
                "Docker storage facts are unavailable",
                probe_timings_ms=tuple(sorted(probe_timings_ms.items())),
            ) from exc

        from .docker_supervisor import DockerCounterReading

        return DockerCounterReading(
            docker_system_df=docker_df,
            docker_total_bytes=total_bytes,
            task_bytes=container_bytes + image_bytes,
            data_root=str(host_root),
            data_root_filesystem_free_bytes=free_bytes,
            docker_desktop_vhdx_bytes=(
                desktop_reading.vhd_size_bytes
                if desktop_reading is not None
                else None
            ),
            task_container_ids=container_ids,
            task_image_ids=image_ids,
            task_containers=container_facts,
            task_container_metrics=container_metrics,
            task_networks=network_facts,
            task_volumes=volume_facts,
            daemon_security_options=security_options,
            probe_timings_ms=tuple(sorted(probe_timings_ms.items())),
        )

    def resolve_image_identity(
        self,
        image_reference: str,
        *,
        deadline: float | None = None,
    ) -> "DockerImageIdentity":
        """Resolve a frozen manifest digest to the daemon's actual image id."""

        if not _SHA256_IMAGE.fullmatch(image_reference):
            raise RuntimeBridgeError("Docker image reference must be digest pinned")
        if deadline is None:
            deadline = self._monotonic() + self._probe_timeout_seconds
        payload = _parse_json_array(
            self._run(("docker", "image", "inspect", image_reference), deadline=deadline)
        )
        return _validate_resolved_image_identity(payload, image_reference)

    def _remaining(self, deadline: float) -> float:
        remaining = deadline - self._monotonic()
        if remaining <= 0:
            raise RuntimeBridgeError("Docker counter absolute deadline expired")
        return remaining

    def _run(self, argv: tuple[str, ...], *, deadline: float) -> str:
        for attempt in range(_DOCKER_FACT_COMMAND_MAX_ATTEMPTS):
            try:
                output = self._executor.run(
                    argv,
                    timeout_seconds=self._remaining(deadline),
                )
            except Exception:
                output = None
            if (
                output is not None
                and output.returncode == 0
                and isinstance(output.stdout, str)
            ):
                return output.stdout
            if attempt + 1 < _DOCKER_FACT_COMMAND_MAX_ATTEMPTS:
                remaining = self._remaining(deadline)
                self._sleeper(
                    min(_DOCKER_FACT_COMMAND_RETRY_DELAY_SECONDS, remaining)
                )
        raise RuntimeBridgeError("Docker storage fact command failed") from None

    def _container_facts(
        self,
        identity: "DockerTaskIdentity",
        object_ids: tuple[str, ...],
        *,
        deadline: float,
    ) -> tuple[tuple[str, ...], int, tuple[object, ...]]:
        if not object_ids:
            return (), 0, ()
        try:
            payload = _parse_json_array(
                self._run(
                    ("docker", "container", "inspect", "--size", *object_ids),
                    deadline=deadline,
                )
            )
        except RuntimeBridgeError:
            # Harbor may remove its task container after ``ls`` but before the
            # bounded inspect.  Re-list the same exact label once; unchanged
            # state remains a hard failure, while a completed disappearance is
            # a valid zero-container observation.
            current_ids = self._container_ids(identity, deadline=deadline)
            if current_ids == object_ids:
                raise
            if not current_ids:
                return (), 0, ()
            object_ids = current_ids
            payload = _parse_json_array(
                self._run(
                    ("docker", "container", "inspect", "--size", *object_ids),
                    deadline=deadline,
                )
            )
        container_bytes, facts = _validate_inspected_containers(
            payload, expected_ids=object_ids, identity=identity
        )
        return object_ids, container_bytes, facts

    def _container_ids(
        self,
        identity: "DockerTaskIdentity",
        *,
        deadline: float,
    ) -> tuple[str, ...]:
        return _parse_id_lines(
            self._run(
                (
                    "docker",
                    "container",
                    "ls",
                    "--all",
                    "--no-trunc",
                    *identity.exact_label_filter,
                    "--format",
                    "{{json .ID}}",
                ),
                deadline=deadline,
            )
        )

    def _image_bytes(
        self,
        identity: "DockerTaskIdentity",
        object_ids: tuple[str, ...],
        *,
        deadline: float,
    ) -> int:
        if not object_ids:
            return 0
        payload = _parse_json_array(
            self._run(("docker", "image", "inspect", *object_ids), deadline=deadline)
        )
        return _validate_inspected_objects(
            payload,
            expected_ids=object_ids,
            identity=identity,
            kind="image",
        )

    def _container_metrics(
        self,
        container_facts: tuple[object, ...],
        *,
        deadline: float,
    ) -> tuple[object, ...]:
        from .docker_supervisor import DockerContainerMetricFact

        metrics: list[DockerContainerMetricFact] = []
        for fact in container_facts:
            container_id = getattr(fact, "container_id", None)
            user = getattr(fact, "user", None)
            if not isinstance(container_id, str) or not isinstance(user, str):
                raise RuntimeBridgeError("Docker container metric target is invalid")
            output = self._run(
                (
                    "docker", "container", "exec", "--user", user,
                    container_id, "/bin/sh", "-ceu", _CONTAINER_CGROUP_METRIC_SCRIPT,
                ),
                deadline=deadline,
            )
            values = _parse_exact_uint_lines(
                output,
                ("cpu_usage_microseconds", "peak_memory_bytes"),
            )
            metric = DockerContainerMetricFact(
                container_id=container_id,
                cpu_usage_microseconds=values["cpu_usage_microseconds"],
                peak_memory_bytes=values["peak_memory_bytes"],
            )
            metric.validate()
            metrics.append(metric)
        return tuple(metrics)

    def _container_metrics_with_disappearance(
        self,
        identity: "DockerTaskIdentity",
        container_ids: tuple[str, ...],
        container_facts: tuple[object, ...],
        *,
        deadline: float,
    ) -> tuple[tuple[str, ...], tuple[object, ...], tuple[object, ...]]:
        """Accept only a proven teardown race after a failed metric exec.

        Harbor may remove its single task container after the exact inspect but
        before the cgroup ``docker exec``.  A fresh exact-label re-list proving
        that the previously inspected container is now absent is a valid empty
        final observation; an unchanged or replacement identity remains a hard
        failure.  Durable result metrics still require an earlier successful
        sample in ``DockerSupervisor``.
        """

        if not container_ids:
            return (), (), ()
        try:
            metrics = self._container_metrics(container_facts, deadline=deadline)
        except RuntimeBridgeError:
            current_ids = self._container_ids(identity, deadline=deadline)
            if current_ids:
                raise
            return (), (), ()
        return container_ids, container_facts, metrics

    def _compose_networks(self, project: str, *, deadline: float) -> tuple[object, ...]:
        from .docker_supervisor import ComposeResourceFact

        object_ids = _parse_id_lines(
            self._run(
                (
                    "docker",
                    "network",
                    "ls",
                    "--no-trunc",
                    "--filter",
                    f"label=com.docker.compose.project={project}",
                    "--format",
                    "{{json .ID}}",
                ),
                deadline=deadline,
            )
        )
        if not object_ids:
            return ()
        payload = _parse_json_array(
            self._run(("docker", "network", "inspect", *object_ids), deadline=deadline)
        )
        return tuple(
            ComposeResourceFact("network", object_id, name)
            for object_id, name in _validate_compose_resources(
                payload,
                expected_ids=object_ids,
                project=project,
                kind="network",
            )
        )

    def _compose_volumes(self, project: str, *, deadline: float) -> tuple[object, ...]:
        from .docker_supervisor import ComposeResourceFact

        names = _parse_resource_name_lines(
            self._run(
                (
                    "docker",
                    "volume",
                    "ls",
                    "--filter",
                    f"label=com.docker.compose.project={project}",
                    "--format",
                    "{{json .Name}}",
                ),
                deadline=deadline,
            )
        )
        if not names:
            return ()
        payload = _parse_json_array(
            self._run(("docker", "volume", "inspect", *names), deadline=deadline)
        )
        return tuple(
            ComposeResourceFact("volume", name, name)
            for name, _ in _validate_compose_resources(
                payload,
                expected_ids=names,
                project=project,
                kind="volume",
            )
        )


@dataclass(frozen=True)
class DockerDesktopHostReading:
    """Non-sensitive facts about the Windows volume holding Docker's VHDX."""

    host_volume_root: Path
    free_bytes: int
    vhd_size_bytes: int

    def validate(self) -> None:
        if (
            not self.host_volume_root.is_absolute()
            or not self.host_volume_root.is_dir()
            or isinstance(self.free_bytes, bool)
            or not isinstance(self.free_bytes, int)
            or self.free_bytes < 0
            or isinstance(self.vhd_size_bytes, bool)
            or not isinstance(self.vhd_size_bytes, int)
            or self.vhd_size_bytes < 0
        ):
            raise RuntimeBridgeError("Docker Desktop host storage fact is invalid")


class DockerDesktopHostProbe(Protocol):
    def sample(self, *, timeout_seconds: float) -> DockerDesktopHostReading: ...


class PowerShellDockerDesktopHostProbe:
    """Read only the default Docker Desktop VHDX size and its host drive free space."""

    _SCRIPT = (
        '$c=@((Join-Path $env:LOCALAPPDATA "Docker\\wsl\\disk\\docker_data.vhdx"),'
        '(Join-Path $env:LOCALAPPDATA "Docker\\wsl\\data\\ext4.vhdx"));'
        '$f=@($c|Where-Object{Test-Path -LiteralPath $_});'
        'if($f.Count -ne 1){exit 3};'
        '$i=Get-Item -LiteralPath $f[0];$d=Get-PSDrive -Name $i.PSDrive.Name;'
        '@{drive=$i.PSDrive.Name;vhd_bytes=$i.Length;free_bytes=$d.Free}'
        '|ConvertTo-Json -Compress'
    )

    def __init__(
        self,
        *,
        executable: Path = Path(
            "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe"
        ),
        timeout_seconds: float = 15.0,
    ) -> None:
        if not executable.is_absolute() or timeout_seconds <= 0:
            raise RuntimeBridgeError("Docker Desktop host probe configuration is invalid")
        self._executable = executable
        self._timeout_seconds = timeout_seconds

    def sample(self, *, timeout_seconds: float | None = None) -> DockerDesktopHostReading:
        effective_timeout = self._timeout_seconds
        if timeout_seconds is not None:
            if timeout_seconds <= 0:
                raise RuntimeBridgeError("Docker Desktop host probe deadline expired")
            effective_timeout = min(effective_timeout, timeout_seconds)
        try:
            completed = subprocess.run(
                (
                    os.fspath(self._executable),
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    self._SCRIPT,
                ),
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                text=True,
                encoding="utf-8-sig",
                errors="strict",
                timeout=effective_timeout,
                check=False,
            )
        except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
            raise RuntimeBridgeError("Docker Desktop host storage probe failed") from exc
        if completed.returncode != 0:
            raise RuntimeBridgeError("Docker Desktop host storage probe failed")
        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeBridgeError("Docker Desktop host storage probe is invalid") from exc
        if not isinstance(payload, dict) or set(payload) != {"drive", "vhd_bytes", "free_bytes"}:
            raise RuntimeBridgeError("Docker Desktop host storage probe is invalid")
        drive = payload["drive"]
        if not isinstance(drive, str) or not re.fullmatch(r"[A-Za-z]", drive):
            raise RuntimeBridgeError("Docker Desktop host storage probe is invalid")
        reading = DockerDesktopHostReading(
            host_volume_root=Path(f"/mnt/{drive.casefold()}"),
            free_bytes=payload["free_bytes"],
            vhd_size_bytes=payload["vhd_bytes"],
        )
        reading.validate()
        return reading

def _validate_argv(argv: Sequence[str]) -> None:
    if not argv:
        raise RuntimeBridgeError("command argv is empty")
    for item in argv:
        if not isinstance(item, str) or not item or "\x00" in item:
            raise RuntimeBridgeError("command argv is invalid")


def _parse_system_df(stdout: str) -> tuple[Mapping[str, object], int]:
    rows: dict[str, Mapping[str, object]] = {}
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeBridgeError("Docker system df output is invalid") from exc
        required = {"Type", "TotalCount", "Active", "Size"}
        if not isinstance(raw, dict) or not required.issubset(raw):
            raise RuntimeBridgeError("Docker system df row is incomplete")
        row_type = raw["Type"]
        if row_type not in _DF_TYPES or row_type in rows:
            raise RuntimeBridgeError("Docker system df rows are ambiguous")
        total_count = _json_uint(raw["TotalCount"])
        active = _json_uint(raw["Active"])
        size_bytes = _parse_size(raw["Size"])
        if active > total_count:
            raise RuntimeBridgeError("Docker system df counts are invalid")
        rows[row_type] = {
            "total_count": total_count,
            "active": active,
            "size_bytes": size_bytes,
        }
    if tuple(sorted(rows)) != tuple(sorted(_DF_TYPES)):
        raise RuntimeBridgeError("Docker system df output is incomplete")
    return {"rows": rows}, sum(int(row["size_bytes"]) for row in rows.values())


def _json_uint(value: object) -> int:
    if isinstance(value, bool):
        raise RuntimeBridgeError("Docker numeric field is invalid")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        result = int(value)
    else:
        raise RuntimeBridgeError("Docker numeric field is invalid")
    if result < 0:
        raise RuntimeBridgeError("Docker numeric field is invalid")
    return result


def _parse_size(value: object) -> int:
    if not isinstance(value, str):
        raise RuntimeBridgeError("Docker size is invalid")
    match = _SIZE.fullmatch(value)
    if match is None:
        raise RuntimeBridgeError("Docker size is invalid")
    try:
        size = Decimal(match.group(1)) * _SIZE_FACTORS[match.group(2)]
    except InvalidOperation as exc:
        raise RuntimeBridgeError("Docker size is invalid") from exc
    if not size.is_finite() or size < 0:
        raise RuntimeBridgeError("Docker size is invalid")
    return int(size.to_integral_value(rounding=ROUND_CEILING))


def _parse_docker_info(stdout: str) -> tuple[str, str, tuple[str, ...]]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeBridgeError("Docker info output is invalid") from exc
    if (
        not isinstance(payload, list)
        or len(payload) != 3
        or any(not isinstance(value, str) or not value for value in payload[:2])
        or not isinstance(payload[2], list)
    ):
        raise RuntimeBridgeError("Docker info output is invalid")
    daemon_root, operating_system, raw_security_options = payload
    if not os.path.isabs(daemon_root) or "\x00" in daemon_root or "\x00" in operating_system:
        raise RuntimeBridgeError("Docker info output is invalid")
    if len(raw_security_options) != len(set(raw_security_options)) or any(
        not isinstance(value, str) or not value or "\x00" in value
        for value in raw_security_options
    ):
        raise RuntimeBridgeError("Docker info security options are invalid")
    return daemon_root, operating_system, tuple(sorted(raw_security_options))


def _parse_id_lines(stdout: str) -> tuple[str, ...]:
    result: list[str] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeBridgeError("Docker object list output is invalid") from exc
        if not isinstance(value, str):
            raise RuntimeBridgeError("Docker object id is invalid")
        match = _OBJECT_ID.fullmatch(value)
        if match is None or match.group(1) in result:
            raise RuntimeBridgeError("Docker object id is invalid")
        result.append(match.group(1))
    return tuple(result)


def _parse_resource_name_lines(stdout: str) -> tuple[str, ...]:
    result: list[str] = []
    for line in stdout.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeBridgeError("Docker resource list output is invalid") from exc
        if (
            not isinstance(value, str)
            or not _RESOURCE_NAME.fullmatch(value)
            or value in result
        ):
            raise RuntimeBridgeError("Docker resource name is invalid")
        result.append(value)
    return tuple(result)


def _parse_json_array(stdout: str) -> list[object]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeBridgeError("Docker inspect output is invalid") from exc
    if not isinstance(payload, list):
        raise RuntimeBridgeError("Docker inspect output is invalid")
    return payload


def _validate_inspected_objects(
    payload: list[object],
    *,
    expected_ids: tuple[str, ...],
    identity: "DockerTaskIdentity",
    kind: str,
) -> int:
    if len(payload) != len(expected_ids):
        raise RuntimeBridgeError("Docker inspect result count changed")
    sizes: dict[str, int] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise RuntimeBridgeError("Docker inspect object is invalid")
        raw_id = item.get("Id")
        if not isinstance(raw_id, str):
            raise RuntimeBridgeError("Docker inspect object id is invalid")
        match = _OBJECT_ID.fullmatch(raw_id)
        if match is None or match.group(1) in sizes:
            raise RuntimeBridgeError("Docker inspect object id is invalid")
        config = item.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        if not isinstance(labels, dict) or labels.get("dev.rondo.eval.task") != identity.task_id:
            raise RuntimeBridgeError("Docker task label did not match exactly")
        size_field = "SizeRw" if kind == "container" else "Size"
        size = item.get(size_field)
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise RuntimeBridgeError("Docker inspect size is invalid")
        sizes[match.group(1)] = size
    if set(sizes) != set(expected_ids):
        raise RuntimeBridgeError("Docker inspect object set changed")
    return sum(sizes.values())


def _validate_inspected_containers(
    payload: list[object],
    *,
    expected_ids: tuple[str, ...],
    identity: "DockerTaskIdentity",
) -> tuple[int, tuple[object, ...]]:
    from .docker_supervisor import DockerContainerFact, DockerMountFact

    if len(payload) != len(expected_ids):
        raise RuntimeBridgeError("Docker inspect result count changed")
    sizes: dict[str, int] = {}
    facts: dict[str, DockerContainerFact] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise RuntimeBridgeError("Docker inspect container is invalid")
        raw_id = item.get("Id")
        if not isinstance(raw_id, str):
            raise RuntimeBridgeError("Docker inspect object id is invalid")
        match = _OBJECT_ID.fullmatch(raw_id)
        if match is None or match.group(1) in facts:
            raise RuntimeBridgeError("Docker inspect object id is invalid")
        object_id = match.group(1)
        raw_image_id = item.get("Image")
        if not isinstance(raw_image_id, str) or _OBJECT_ID.fullmatch(raw_image_id) is None:
            raise RuntimeBridgeError("Docker container image id is invalid")
        image_id_match = _OBJECT_ID.fullmatch(raw_image_id)
        assert image_id_match is not None
        image_id = f"sha256:{image_id_match.group(1)}"
        config = item.get("Config")
        host = item.get("HostConfig")
        network_settings = item.get("NetworkSettings")
        mounts_payload = item.get("Mounts")
        if not all(isinstance(value, dict) for value in (config, host, network_settings)):
            raise RuntimeBridgeError("Docker container runtime facts are incomplete")
        if not isinstance(mounts_payload, list):
            raise RuntimeBridgeError("Docker container mount facts are invalid")
        labels = config.get("Labels")
        if not isinstance(labels, dict) or labels.get("dev.rondo.eval.task") != identity.task_id:
            raise RuntimeBridgeError("Docker task label did not match exactly")
        compose_project = labels.get("com.docker.compose.project")
        compose_service = labels.get("com.docker.compose.service")
        if not isinstance(compose_project, str) or not isinstance(compose_service, str):
            raise RuntimeBridgeError("Docker Compose container identity is unavailable")
        network_mode = _required_string(host, "NetworkMode")
        networks_payload = network_settings.get("Networks")
        if not isinstance(networks_payload, dict):
            raise RuntimeBridgeError("Docker container network facts are invalid")
        networks = tuple(sorted(networks_payload))
        if any(not _RESOURCE_NAME.fullmatch(value) for value in networks):
            raise RuntimeBridgeError("Docker container network facts are invalid")
        if network_mode == "none" and networks == ("none",):
            networks = ()
        mounts: list[DockerMountFact] = []
        for raw_mount in mounts_payload:
            if not isinstance(raw_mount, dict) or set(("Type", "Source", "Destination", "RW")) - set(raw_mount):
                raise RuntimeBridgeError("Docker container mount facts are incomplete")
            kind = raw_mount["Type"]
            source = raw_mount["Source"]
            destination = raw_mount["Destination"]
            read_write = raw_mount["RW"]
            if (
                not isinstance(kind, str)
                or not isinstance(source, str)
                or not isinstance(destination, str)
                or not isinstance(read_write, bool)
            ):
                raise RuntimeBridgeError("Docker container mount fact is invalid")
            mount = DockerMountFact(kind, source, destination, not read_write)
            try:
                mount.validate()
            except Exception as exc:
                raise RuntimeBridgeError("Docker container mount fact is invalid") from exc
            mounts.append(mount)
        mounts.extend(_tmpfs_mounts(host))
        size = item.get("SizeRw")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise RuntimeBridgeError("Docker inspect size is invalid")
        security_opt = _normalized_security_options(host)
        seccomp_profile_sha256 = _seccomp_profile_digest(security_opt)
        fact = DockerContainerFact(
            container_id=object_id,
            user=_required_string(config, "User"),
            privileged=_required_bool(host, "Privileged"),
            cap_add=_optional_string_list(host, "CapAdd"),
            cap_drop=_optional_string_list(host, "CapDrop"),
            security_opt=security_opt,
            memory_bytes=_required_nonnegative_int(host, "Memory"),
            memory_swap_bytes=_required_nonnegative_int(host, "MemorySwap"),
            pids_limit=_required_nonnegative_int(host, "PidsLimit"),
            read_only_rootfs=_required_bool(host, "ReadonlyRootfs"),
            cgroupns_mode=_required_string(host, "CgroupnsMode"),
            network_mode=network_mode,
            networks=networks,
            mounts=tuple(sorted(mounts)),
            compose_project=compose_project,
            compose_service=compose_service,
            image_reference=_required_string(config, "Image"),
            image_id=image_id,
            seccomp_profile_sha256=seccomp_profile_sha256,
        )
        try:
            fact.validate()
        except Exception as exc:
            raise RuntimeBridgeError("Docker container runtime fact is invalid") from exc
        sizes[object_id] = size
        facts[object_id] = fact
    if set(facts) != set(expected_ids):
        raise RuntimeBridgeError("Docker inspect object set changed")
    return sum(sizes.values()), tuple(facts[value] for value in expected_ids)


def _validate_resolved_image_identity(
    payload: list[object],
    image_reference: str,
) -> object:
    from .docker_supervisor import DockerImageIdentity

    if len(payload) != 1 or not isinstance(payload[0], dict):
        raise RuntimeBridgeError("Docker image identity is unavailable")
    raw_id = payload[0].get("Id")
    repo_digests = payload[0].get("RepoDigests")
    if (
        not isinstance(raw_id, str)
        or _OBJECT_ID.fullmatch(raw_id) is None
        or not isinstance(repo_digests, list)
        or any(not isinstance(value, str) for value in repo_digests)
        or image_reference not in repo_digests
    ):
        raise RuntimeBridgeError("Docker image identity differs from frozen digest")
    match = _OBJECT_ID.fullmatch(raw_id)
    assert match is not None
    identity = DockerImageIdentity(image_reference, f"sha256:{match.group(1)}")
    try:
        identity.validate()
    except Exception as exc:
        raise RuntimeBridgeError("Docker image identity is invalid") from exc
    return identity


def _parse_exact_uint_lines(output: str, expected: tuple[str, ...]) -> dict[str, int]:
    values: dict[str, int] = {}
    for line in output.splitlines():
        key, separator, value = line.partition("=")
        if not separator or key not in expected or key in values:
            raise RuntimeBridgeError("Docker container metric output is invalid")
        values[key] = _parse_uint(value)
    if set(values) != set(expected):
        raise RuntimeBridgeError("Docker container metric output is incomplete")
    return values


def _required_string(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value or "\x00" in value:
        raise RuntimeBridgeError("Docker container string fact is invalid")
    return value


def _required_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise RuntimeBridgeError("Docker container boolean fact is invalid")
    return value


def _required_nonnegative_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RuntimeBridgeError("Docker container numeric fact is invalid")
    return value


def _optional_string_list(payload: Mapping[str, object], key: str) -> tuple[str, ...]:
    value = payload.get(key)
    if value is None:
        return ()
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item or "\x00" in item for item in value
    ):
        raise RuntimeBridgeError("Docker container list fact is invalid")
    if len(value) != len(set(value)):
        raise RuntimeBridgeError("Docker container list fact is ambiguous")
    return tuple(sorted(value))


def _normalized_security_options(payload: Mapping[str, object]) -> tuple[str, ...]:
    values = _optional_string_list(payload, "SecurityOpt")
    normalized = tuple(
        "no-new-privileges:true"
        if value.casefold()
        in {"no-new-privileges", "no-new-privileges:true", "no-new-privileges=true"}
        else value
        for value in values
    )
    if len(normalized) != len(set(normalized)):
        raise RuntimeBridgeError("Docker security options are ambiguous")
    return tuple(sorted(normalized))


def _tmpfs_mounts(payload: Mapping[str, object]) -> tuple[object, ...]:
    from .docker_supervisor import DockerMountFact

    value = payload.get("Tmpfs")
    if value is None:
        return ()
    if not isinstance(value, dict):
        raise RuntimeBridgeError("Docker tmpfs facts are invalid")
    mounts: list[DockerMountFact] = []
    for destination, raw_options in value.items():
        if (
            not isinstance(destination, str)
            or not isinstance(raw_options, str)
            or not raw_options
        ):
            raise RuntimeBridgeError("Docker tmpfs fact is invalid")
        options = tuple(sorted(raw_options.split(",")))
        if len(options) != len(set(options)) or any(not option for option in options):
            raise RuntimeBridgeError("Docker tmpfs options are invalid")
        if "ro" in options and "rw" in options:
            raise RuntimeBridgeError("Docker tmpfs mode is ambiguous")
        mount = DockerMountFact(
            "tmpfs",
            "",
            destination,
            "ro" in options,
            options,
        )
        try:
            mount.validate()
        except Exception as exc:
            raise RuntimeBridgeError("Docker tmpfs fact is invalid") from exc
        mounts.append(mount)
    return tuple(sorted(mounts))


def _seccomp_profile_digest(security_opt: tuple[str, ...]) -> str | None:
    values = tuple(
        value for value in security_opt if value.casefold().startswith("seccomp=")
    )
    if not values:
        return None
    if len(values) != 1 or values[0].casefold() == "seccomp=unconfined":
        raise RuntimeBridgeError("Docker seccomp profile fact is unsafe or ambiguous")
    payload = values[0].partition("=")[2]
    # The Docker CLI reads a custom profile and sends its contents to the
    # daemon.  A path here would therefore be insufficient effective-state
    # evidence and is rejected rather than hashed as a self-reported name.
    if not payload or payload.startswith(("/", "./", "../")):
        raise RuntimeBridgeError("Docker seccomp profile content is unavailable")
    try:
        decoded = json.loads(payload, object_pairs_hook=_unique_json_object)
    except json.JSONDecodeError as exc:
        raise RuntimeBridgeError("Docker seccomp profile content is invalid") from exc
    if not isinstance(decoded, dict):
        raise RuntimeBridgeError("Docker seccomp profile content is invalid")
    canonical = json.dumps(
        decoded,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise RuntimeBridgeError("Docker seccomp profile content is ambiguous")
        result[key] = value
    return result


def _validate_compose_resources(
    payload: list[object],
    *,
    expected_ids: tuple[str, ...],
    project: str,
    kind: str,
) -> tuple[tuple[str, str], ...]:
    if len(payload) != len(expected_ids):
        raise RuntimeBridgeError("Docker Compose inspect result count changed")
    facts: dict[str, str] = {}
    for item in payload:
        if not isinstance(item, dict):
            raise RuntimeBridgeError("Docker Compose resource is invalid")
        labels = item.get("Labels")
        name = item.get("Name")
        if (
            not isinstance(labels, dict)
            or labels.get("com.docker.compose.project") != project
            or not isinstance(name, str)
            or not _RESOURCE_NAME.fullmatch(name)
        ):
            raise RuntimeBridgeError("Docker Compose resource identity differs")
        if kind == "network":
            raw_id = item.get("Id")
            if not isinstance(raw_id, str):
                raise RuntimeBridgeError("Docker Compose network id is invalid")
            match = _OBJECT_ID.fullmatch(raw_id)
            if match is None:
                raise RuntimeBridgeError("Docker Compose network id is invalid")
            object_id = match.group(1)
        elif kind == "volume":
            object_id = name
        else:
            raise RuntimeBridgeError("Docker Compose resource kind is invalid")
        if object_id in facts:
            raise RuntimeBridgeError("Docker Compose resource identity is ambiguous")
        facts[object_id] = name
    if set(facts) != set(expected_ids):
        raise RuntimeBridgeError("Docker Compose resource set changed")
    return tuple((value, facts[value]) for value in expected_ids)


def _validate_host_data_root(
    configured: Path,
    *,
    daemon_root: str,
    operating_system: str,
    mountinfo_path: Path,
) -> Path:
    try:
        host_root = configured.resolve(strict=True)
    except OSError as exc:
        raise RuntimeBridgeError("Docker host data root is unavailable") from exc
    if not host_root.is_dir():
        raise RuntimeBridgeError("Docker host data root is not a directory")
    if "docker desktop" not in operating_system.casefold():
        try:
            native_root = Path(daemon_root).resolve(strict=True)
        except OSError as exc:
            raise RuntimeBridgeError("native Docker data root is unavailable") from exc
        if host_root != native_root:
            raise RuntimeBridgeError("configured host data root does not match Docker info")
        return host_root

    try:
        mountinfo = mountinfo_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise RuntimeBridgeError("Docker Desktop mount facts are unavailable") from exc
    mount = _mount_for_path(host_root, mountinfo)
    if mount is None or not _has_docker_desktop_marker(mount):
        raise RuntimeBridgeError("configured host data root is not on a Docker Desktop data mount")
    return host_root


@dataclass(frozen=True)
class _MountFact:
    root: str
    mountpoint: Path
    source: str


def _mount_for_path(path: Path, mountinfo: str) -> _MountFact | None:
    matches: list[_MountFact] = []
    for line in mountinfo.splitlines():
        left, separator, right = line.partition(" - ")
        left_fields = left.split()
        right_fields = right.split()
        if separator != " - " or len(left_fields) < 5 or len(right_fields) < 2:
            raise RuntimeBridgeError("mountinfo is invalid")
        root = _unescape_mountinfo(left_fields[3])
        mountpoint = Path(_unescape_mountinfo(left_fields[4]))
        source = _unescape_mountinfo(right_fields[1])
        if not mountpoint.is_absolute():
            raise RuntimeBridgeError("mountinfo is invalid")
        if path == mountpoint or path.is_relative_to(mountpoint):
            matches.append(_MountFact(root=root, mountpoint=mountpoint, source=source))
    if not matches:
        return None
    return max(matches, key=lambda item: len(item.mountpoint.parts))


def _unescape_mountinfo(value: str) -> str:
    for escaped, plain in (("\\040", " "), ("\\011", "\t"), ("\\012", "\n"), ("\\134", "\\")):
        value = value.replace(escaped, plain)
    if "\\" in value or "\x00" in value:
        raise RuntimeBridgeError("mountinfo escape is invalid")
    return value


def _has_docker_desktop_marker(mount: _MountFact) -> bool:
    fields = (mount.root, str(mount.mountpoint), mount.source)
    for field in fields:
        for component in Path(field).parts:
            if component.casefold().startswith("docker-desktop"):
                return True
    return False
