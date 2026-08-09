"""Production adapters for the eval runtime's injected process interfaces.

Nothing in this module starts a process at import time.  The watchdog proof is
also intentionally independent from Docker so the same lease can guard any
heavy local operation that is launched by ``with-build-lock.sh``.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_CEILING
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Mapping, Protocol, Sequence

if TYPE_CHECKING:
    from .docker_supervisor import (
        DockerCounterReading,
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
)
_DF_TYPES = ("Images", "Containers", "Local Volumes", "Build Cache")
_SIZE = re.compile(r"([0-9]+(?:[.][0-9]+)?)(B|kB|MB|GB|TB|PB|KiB|MiB|GiB|TiB|PiB)\Z")
_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*\Z")
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
    ) -> None:
        self._token = token
        self._proc_cgroup_path = proc_cgroup_path
        self._cgroup_fs_root = cgroup_fs_root
        self._relative_cgroup = relative_cgroup
        self._cgroup_directory = cgroup_directory
        self._pid = pid

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
            return True
        except (AttributeError, OSError, RuntimeBridgeError, TypeError):
            return False


def lease_from_watchdog(
    *,
    proc_cgroup_path: Path = Path("/proc/self/cgroup"),
    cgroup_fs_root: Path = Path("/sys/fs/cgroup"),
) -> WatchdogProof:
    """Mint a lease only when this process is inside a live RONDO scope.

    The injectable paths exist solely for hermetic tests.  The PID cannot be
    injected: membership is always proved for the calling process itself.
    """

    pid = os.getpid()
    try:
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
    for name in ("memory.stat", "memory.events"):
        if not _parse_keyed_uints(values[name]):
            raise RuntimeBridgeError("watchdog keyed counter is invalid")
    _parse_pressure(values["memory.pressure"])


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

    def __init__(self, process: subprocess.Popen[str]) -> None:
        self._process = process

    def wait(self, timeout_seconds: float) -> int | None:
        try:
            return self._process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            return None

    def terminate(self) -> None:
        self._process.terminate()

    def kill(self) -> None:
        self._process.kill()


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
                text=True,
            )
        except (OSError, ValueError) as exc:
            raise RuntimeBridgeError("host harness could not be started") from exc
        return SubprocessCommandHandle(process)


@dataclass(frozen=True)
class CommandOutput:
    returncode: int
    stdout: str


class CommandExecutor(Protocol):
    def run(self, argv: tuple[str, ...]) -> CommandOutput: ...


class SubprocessCommandExecutor:
    """Synchronous executor for short, read-only Docker counter commands."""

    def __init__(self, *, timeout_seconds: float = 30.0) -> None:
        if timeout_seconds <= 0:
            raise RuntimeBridgeError("command timeout must be positive")
        self._timeout_seconds = timeout_seconds

    def run(self, argv: tuple[str, ...]) -> CommandOutput:
        _validate_argv(argv)
        if argv[0] != "docker":
            raise RuntimeBridgeError("counter executor accepts only the Docker CLI")
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
                timeout=self._timeout_seconds,
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
    ) -> None:
        if not host_data_root.is_absolute():
            raise RuntimeBridgeError("Docker host data root must be absolute")
        self._host_data_root = host_data_root
        self._executor = executor or SubprocessCommandExecutor()
        self._desktop_host_probe = desktop_host_probe
        self._mountinfo_path = mountinfo_path
        self._statvfs = statvfs

    def sample(
        self,
        *,
        identity: "DockerTaskIdentity",
        operation: "DockerOperation",
    ) -> "DockerCounterReading":
        del operation
        identity.validate()
        try:
            df_output = self._run(("docker", "system", "df", "--format", "{{json .}}"))
            docker_df, total_bytes = _parse_system_df(df_output)
            info_output = self._run(
                (
                    "docker",
                    "info",
                    "--format",
                    "[{{json .DockerRootDir}},{{json .OperatingSystem}}]",
                )
            )
            daemon_root, operating_system = _parse_docker_info(info_output)
            desktop_reading: DockerDesktopHostReading | None = None
            if "docker desktop" in operating_system.casefold() and self._desktop_host_probe:
                desktop_reading = self._desktop_host_probe.sample()
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
            container_ids = _parse_id_lines(
                self._run(
                    (
                        "docker",
                        "container",
                        "ls",
                        "--all",
                        "--no-trunc",
                        *filter_args,
                        "--format",
                        "{{json .ID}}",
                    )
                )
            )
            image_ids = _parse_id_lines(
                self._run(
                    (
                        "docker",
                        "image",
                        "ls",
                        "--no-trunc",
                        *filter_args,
                        "--format",
                        "{{json .ID}}",
                    )
                )
            )
            container_bytes = self._container_bytes(identity, container_ids)
            image_bytes = self._image_bytes(identity, image_ids)
            if desktop_reading is not None:
                free_bytes = desktop_reading.free_bytes
            else:
                filesystem = self._statvfs(host_root)
                free_bytes = filesystem.f_bavail * filesystem.f_frsize
            if isinstance(free_bytes, bool) or not isinstance(free_bytes, int) or free_bytes < 0:
                raise RuntimeBridgeError("Docker host filesystem counter is invalid")
        except RuntimeBridgeError:
            raise
        except (OSError, TypeError, ValueError) as exc:
            raise RuntimeBridgeError("Docker storage facts are unavailable") from exc

        from .docker_supervisor import DockerCounterReading

        return DockerCounterReading(
            docker_system_df=docker_df,
            docker_total_bytes=total_bytes,
            task_bytes=container_bytes + image_bytes,
            data_root=str(host_root),
            data_root_filesystem_free_bytes=free_bytes,
            task_container_ids=container_ids,
            task_image_ids=image_ids,
        )

    def _run(self, argv: tuple[str, ...]) -> str:
        try:
            output = self._executor.run(argv)
        except Exception:
            raise RuntimeBridgeError("Docker storage fact command failed") from None
        if output.returncode != 0 or not isinstance(output.stdout, str):
            raise RuntimeBridgeError("Docker storage fact command failed")
        return output.stdout

    def _container_bytes(
        self,
        identity: "DockerTaskIdentity",
        object_ids: tuple[str, ...],
    ) -> int:
        if not object_ids:
            return 0
        payload = _parse_json_array(
            self._run(("docker", "container", "inspect", "--size", *object_ids))
        )
        return _validate_inspected_objects(
            payload,
            expected_ids=object_ids,
            identity=identity,
            kind="container",
        )

    def _image_bytes(
        self,
        identity: "DockerTaskIdentity",
        object_ids: tuple[str, ...],
    ) -> int:
        if not object_ids:
            return 0
        payload = _parse_json_array(
            self._run(("docker", "image", "inspect", *object_ids))
        )
        return _validate_inspected_objects(
            payload,
            expected_ids=object_ids,
            identity=identity,
            kind="image",
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
    def sample(self) -> DockerDesktopHostReading: ...


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

    def sample(self) -> DockerDesktopHostReading:
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
                timeout=self._timeout_seconds,
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


def _parse_docker_info(stdout: str) -> tuple[str, str]:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeBridgeError("Docker info output is invalid") from exc
    if (
        not isinstance(payload, list)
        or len(payload) != 2
        or any(not isinstance(value, str) or not value for value in payload)
    ):
        raise RuntimeBridgeError("Docker info output is invalid")
    daemon_root, operating_system = payload
    if not os.path.isabs(daemon_root) or "\x00" in daemon_root or "\x00" in operating_system:
        raise RuntimeBridgeError("Docker info output is invalid")
    return daemon_root, operating_system


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
