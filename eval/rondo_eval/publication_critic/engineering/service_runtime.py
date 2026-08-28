"""Bounded process lifecycle for the two Plan 097 scorer fixtures.

This module composes the existing Rust service, typed probe, and Plan 068
worker.  It does not implement a scorer or publication state machine.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import threading
import time
from typing import Any


_MAX_JSON_BYTES = 1024 * 1024
_MAX_DIAGNOSTIC_BYTES = 64 * 1024
_CLOUD_PROXY_KEY_ENV = "RONDO_PLAN097_DEEPSEEK_PROXY_KEY"
_SYSTEM_ENV = (
    "PATH",
    "LANG",
    "LC_ALL",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "LD_LIBRARY_PATH",
    "CUDA_HOME",
    "CUDA_PATH",
    "CUDA_VISIBLE_DEVICES",
    "NVIDIA_VISIBLE_DEVICES",
    "NVIDIA_DRIVER_CAPABILITIES",
    "TMPDIR",
    "RONDO_WATCHDOG_WRAPPER_PID",
    "RONDO_WATCHDOG_WRAPPER_START_TICKS",
    "RONDO_WATCHDOG_HEARTBEAT_PATH",
    "RONDO_WATCHDOG_SCRIPT_PATH",
)


class ServiceRuntimeError(RuntimeError):
    """A stable body-free service orchestration failure."""


@dataclass(frozen=True)
class RuntimeBinaries:
    codex: Path
    real_service: Path
    cloud_service: Path
    probe: Path

    def validate(self) -> None:
        for path in (self.codex, self.real_service, self.cloud_service, self.probe):
            if path.is_symlink() or not path.is_file() or not os.access(path, os.X_OK):
                raise ServiceRuntimeError("runtime_binary_invalid")

    def identities(self) -> dict[str, str]:
        self.validate()
        return {
            "codex_sha256": _sha256_file(self.codex),
            "real_service_sha256": _sha256_file(self.real_service),
            "cloud_service_sha256": _sha256_file(self.cloud_service),
            "probe_sha256": _sha256_file(self.probe),
        }


@dataclass(frozen=True)
class LocalRuntime:
    python: Path
    snapshot: Path
    repo_root: Path
    descriptor: Path
    cpu_threads: int = 4

    def validate(self) -> None:
        try:
            python_target = self.python.resolve(strict=True)
        except OSError as exc:
            raise ServiceRuntimeError("local_runtime_invalid") from exc
        if (
            not self.python.is_file()
            or not os.access(self.python, os.X_OK)
            or not python_target.is_file()
            or not os.access(python_target, os.X_OK)
            or self.snapshot.is_symlink()
            or not self.snapshot.is_dir()
            or self.repo_root.is_symlink()
            or not self.repo_root.is_dir()
            or isinstance(self.cpu_threads, bool)
            or not 1 <= self.cpu_threads <= 32
        ):
            raise ServiceRuntimeError("local_runtime_invalid")
        _load_json(self.descriptor, "local_descriptor")


@dataclass(frozen=True)
class ServiceObservation:
    backend: str
    endpoint: str
    descriptor_sha256: str
    startup_elapsed_ms: int
    ready_elapsed_ms: int
    service_pid: int


class RunningScorerService:
    """One task-owned scorer service and its typed probe lifecycle."""

    def __init__(
        self,
        *,
        backend: str,
        process: subprocess.Popen[bytes],
        probe: Path,
        expected_argument: str,
        expected_descriptor_path: Path,
        endpoint: str,
        descriptor_sha256: str,
        startup_elapsed_ms: int,
        call_timeout_ms: int,
        startup_timeout_ms: int,
        environment: Mapping[str, str],
    ) -> None:
        self.backend = backend
        self.process = process
        self.probe = probe
        self.expected_argument = expected_argument
        self.expected_descriptor_path = expected_descriptor_path
        self.endpoint = endpoint
        self.descriptor_sha256 = descriptor_sha256
        self.startup_elapsed_ms = startup_elapsed_ms
        self.call_timeout_ms = call_timeout_ms
        self.startup_timeout_ms = startup_timeout_ms
        self.environment = dict(environment)
        self.ready_elapsed_ms = 0
        self._stderr = bytearray()
        self._stderr_thread = threading.Thread(
            target=self._drain_stderr,
            name=f"plan097-{backend}-service-stderr",
            daemon=True,
        )
        self._stderr_thread.start()
        self._closed = False

    def __enter__(self) -> "RunningScorerService":
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    @property
    def observation(self) -> ServiceObservation:
        return ServiceObservation(
            backend=self.backend,
            endpoint=self.endpoint,
            descriptor_sha256=self.descriptor_sha256,
            startup_elapsed_ms=self.startup_elapsed_ms,
            ready_elapsed_ms=self.ready_elapsed_ms,
            service_pid=self.process.pid,
        )

    @property
    def diagnostic_codes(self) -> tuple[str, ...]:
        text = bytes(self._stderr).decode("utf-8", "replace")
        allowed = []
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("publication_critic_") and len(line) <= 256:
                allowed.append(line)
        return tuple(allowed[-64:])

    def ready(self) -> dict[str, Any]:
        started = time.monotonic()
        result = self._probe("ready", timeout_ms=self.startup_timeout_ms + 10_000)
        self.ready_elapsed_ms = round((time.monotonic() - started) * 1000)
        return result

    def review(self, packet: Path) -> dict[str, Any]:
        _load_json(packet, "packet")
        return self._probe(
            "review",
            "--packet",
            str(packet),
            timeout_ms=self.call_timeout_ms + 10_000,
        )

    def cancel(self, packet: Path, *, cancel_after_ms: int) -> dict[str, Any]:
        if isinstance(cancel_after_ms, bool) or not 0 < cancel_after_ms <= 10_000:
            raise ServiceRuntimeError("cancel_delay_invalid")
        _load_json(packet, "packet")
        return self._probe(
            "cancel",
            "--packet",
            str(packet),
            "--cancel-after-ms",
            str(cancel_after_ms),
            timeout_ms=self.call_timeout_ms + 10_000,
        )

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self.process.poll() is None:
            try:
                self._probe("shutdown", timeout_ms=15_000)
            except ServiceRuntimeError:
                pass
        try:
            self.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            _terminate_process_group(self.process, signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _terminate_process_group(self.process, signal.SIGKILL)
                self.process.wait(timeout=5)
        self._stderr_thread.join(timeout=2)
        if self._stderr_thread.is_alive():
            raise ServiceRuntimeError("service_stderr_reader_stuck")

    def _probe(self, operation: str, *arguments: str, timeout_ms: int) -> dict[str, Any]:
        command = [
            str(self.probe),
            "--endpoint",
            self.endpoint,
            self.expected_argument,
            str(self.expected_descriptor_path),
            "--call-timeout-ms",
            str(self.call_timeout_ms),
            "--startup-timeout-ms",
            str(self.startup_timeout_ms),
            operation,
            *arguments,
        ]
        try:
            completed = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.environment,
                timeout=timeout_ms / 1000,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ServiceRuntimeError("probe_timeout") from exc
        if completed.returncode != 0 or len(completed.stdout) > _MAX_JSON_BYTES:
            raise ServiceRuntimeError("probe_failed")
        try:
            value = json.loads(completed.stdout)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise ServiceRuntimeError("probe_output_invalid") from exc
        if not isinstance(value, dict) or value.get("operation") != operation:
            raise ServiceRuntimeError("probe_output_invalid")
        return value

    def _drain_stderr(self) -> None:
        assert self.process.stderr is not None
        while True:
            chunk = self.process.stderr.read(4096)
            if not chunk:
                return
            remaining = _MAX_DIAGNOSTIC_BYTES - len(self._stderr)
            if remaining > 0:
                self._stderr.extend(chunk[:remaining])


def start_local_service(
    *,
    binaries: RuntimeBinaries,
    runtime: LocalRuntime,
    call_timeout_ms: int,
    startup_timeout_ms: int,
) -> RunningScorerService:
    binaries.validate()
    runtime.validate()
    descriptor = _load_json(runtime.descriptor, "local_descriptor")
    service_descriptor = _service_descriptor(descriptor)
    environment = _base_environment()
    environment["PYTHONPATH"] = str(runtime.repo_root / "eval")
    worker_arguments = (
        "-m",
        "rondo_eval.publication_critic.local_deployment.worker",
        "--snapshot",
        str(runtime.snapshot),
        "--descriptor",
        str(runtime.descriptor),
        "--device",
        "cuda",
        "--dtype",
        "bfloat16",
        "--cpu-threads",
        str(runtime.cpu_threads),
        "--repo-root",
        str(runtime.repo_root),
    )
    command = [
        str(binaries.real_service),
        "--descriptor",
        str(runtime.descriptor),
        "--worker-program",
        str(runtime.python),
        "--worker-startup-timeout-ms",
        str(startup_timeout_ms),
        "--worker-io-timeout-ms",
        str(call_timeout_ms),
        "--worker-shutdown-timeout-ms",
        "10000",
    ]
    command.extend(f"--worker-arg={argument}" for argument in worker_arguments)
    return _start_service(
        backend="local",
        command=command,
        environment=environment,
        probe=binaries.probe,
        expected_argument="--expected-descriptor",
        expected_descriptor_path=runtime.descriptor,
        expected_descriptor=service_descriptor,
        descriptor_sha256=_sha256_file(runtime.descriptor),
        call_timeout_ms=call_timeout_ms,
        startup_timeout_ms=startup_timeout_ms,
    )


def start_cloud_service(
    *,
    binaries: RuntimeBinaries,
    tracked_descriptor: Path,
    runtime_descriptor: Path,
    proxy_base_url: str,
    downstream_api_key: str,
    call_timeout_ms: int,
    startup_timeout_ms: int,
) -> RunningScorerService:
    binaries.validate()
    descriptor = _load_json(tracked_descriptor, "cloud_descriptor")
    provider = descriptor.get("provider")
    if not isinstance(provider, dict):
        raise ServiceRuntimeError("cloud_descriptor_invalid")
    runtime_value = json.loads(json.dumps(descriptor))
    runtime_value["provider"]["base_url"] = proxy_base_url
    runtime_value["provider"]["api_key_env"] = _CLOUD_PROXY_KEY_ENV
    _exclusive_json(runtime_descriptor, runtime_value)
    environment = _base_environment()
    environment[_CLOUD_PROXY_KEY_ENV] = downstream_api_key
    return _start_service(
        backend="cloud",
        command=[
            str(binaries.cloud_service),
            "--descriptor",
            str(runtime_descriptor),
        ],
        environment=environment,
        probe=binaries.probe,
        expected_argument="--expected-cloud-descriptor",
        expected_descriptor_path=runtime_descriptor,
        expected_descriptor=_service_descriptor(descriptor),
        descriptor_sha256=_sha256_file(tracked_descriptor),
        call_timeout_ms=call_timeout_ms,
        startup_timeout_ms=startup_timeout_ms,
    )


def write_packet(path: Path, packet: Mapping[str, Any]) -> None:
    _exclusive_json(path, dict(packet))


def _start_service(
    *,
    backend: str,
    command: Sequence[str],
    environment: Mapping[str, str],
    probe: Path,
    expected_argument: str,
    expected_descriptor_path: Path,
    expected_descriptor: Mapping[str, Any],
    descriptor_sha256: str,
    call_timeout_ms: int,
    startup_timeout_ms: int,
) -> RunningScorerService:
    if backend not in {"local", "cloud"}:
        raise ServiceRuntimeError("backend_invalid")
    started = time.monotonic()
    process = subprocess.Popen(
        list(command),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(environment),
        start_new_session=True,
    )
    assert process.stdout is not None
    try:
        ready, _, _ = select.select([process.stdout], [], [], startup_timeout_ms / 1000)
        if not ready:
            raise ServiceRuntimeError("service_announcement_timeout")
        line = process.stdout.readline(_MAX_JSON_BYTES + 1)
        if not line or len(line) > _MAX_JSON_BYTES:
            raise ServiceRuntimeError("service_announcement_invalid")
        announcement = json.loads(line)
        if not isinstance(announcement, dict):
            raise ServiceRuntimeError("service_announcement_invalid")
        if announcement.get("protocol") != "rondo_publication_critic_v1":
            raise ServiceRuntimeError("service_announcement_protocol_mismatch")
        if announcement.get("descriptor") != dict(expected_descriptor):
            raise ServiceRuntimeError("service_announcement_descriptor_mismatch")
        endpoint = announcement.get("endpoint")
        if not isinstance(endpoint, str) or not endpoint.startswith("127.0.0.1:"):
            raise ServiceRuntimeError("service_endpoint_invalid")
        return RunningScorerService(
            backend=backend,
            process=process,
            probe=probe,
            expected_argument=expected_argument,
            expected_descriptor_path=expected_descriptor_path,
            endpoint=endpoint,
            descriptor_sha256=descriptor_sha256,
            startup_elapsed_ms=round((time.monotonic() - started) * 1000),
            call_timeout_ms=call_timeout_ms,
            startup_timeout_ms=startup_timeout_ms,
            environment=environment,
        )
    except (OSError, ValueError, json.JSONDecodeError, ServiceRuntimeError):
        _terminate_process_group(process, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _terminate_process_group(process, signal.SIGKILL)
            process.wait(timeout=5)
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
        raise


def _service_descriptor(value: Mapping[str, Any]) -> dict[str, Any]:
    descriptor = value.get("service_descriptor")
    if not isinstance(descriptor, dict) or set(descriptor) != {"identity", "limits"}:
        raise ServiceRuntimeError("service_descriptor_invalid")
    return dict(descriptor)


def _base_environment() -> dict[str, str]:
    environment = {
        name: os.environ[name]
        for name in _SYSTEM_ENV
        if name in os.environ and os.environ[name]
    }
    environment.update(
        {
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
            "PYTHONDONTWRITEBYTECODE": "1",
        }
    )
    return environment


def _exclusive_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink() or not path.parent.is_dir() or path.is_symlink():
        raise ServiceRuntimeError("runtime_output_unsafe")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise ServiceRuntimeError("runtime_output_exists") from exc
    body = json.dumps(
        dict(value), ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2
    ).encode("utf-8") + b"\n"
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        raise


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ServiceRuntimeError(f"{label}_missing") from exc
    if (
        path.is_symlink()
        or not path.is_file()
        or metadata.st_size <= 0
        or metadata.st_size > _MAX_JSON_BYTES
    ):
        raise ServiceRuntimeError(f"{label}_unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ServiceRuntimeError(f"{label}_invalid") from exc
    if not isinstance(value, dict):
        raise ServiceRuntimeError(f"{label}_invalid")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _terminate_process_group(process: subprocess.Popen[bytes], sig: signal.Signals) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, sig)
    except ProcessLookupError:
        return


__all__ = [
    "LocalRuntime",
    "RunningScorerService",
    "RuntimeBinaries",
    "ServiceObservation",
    "ServiceRuntimeError",
    "start_cloud_service",
    "start_local_service",
    "write_packet",
]
