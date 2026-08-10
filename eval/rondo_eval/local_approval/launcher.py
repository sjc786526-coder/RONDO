"""Pinned llama.cpp launcher with a model-free, short-lived router probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import stat
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .. import runtime_bridge
from ..config import ConfigError, RepoPaths, RuntimeConfig, load_local_model_secret, load_runtime_config
from ..exit_codes import CONFIG_ERROR, INFRA_ERROR, MODEL_MISSING, SUCCESS
from .client import LocalApprovalSettings, resolve_config_path, settings_from_config
from .identity import (
    LauncherIdentity,
    clear_launcher_identity,
    publish_launcher_identity,
)


LLAMA_CPP_BUILD = 10333
LLAMA_CPP_COMMIT = "08659901c43b51de735740f1cf61bb82fbe0c4e4"
LLAMA_CPP_ASSET_SHA256 = "936ce04d98abe2a977e9dd2ff92659bb96947e136acee8f2bc3e21d8eaebbf23"
LLAMA_CPP_BINARY_SHA256 = "1d374fdb717832ec01d4829eff9feb46dfc83b7ccbb9d867c15315dbd8aa4bbe"
GPU_MODEL_SERVING_CAPABILITY = "gpu_model_serving_validated"
_VERSION_TIMEOUT_SECONDS = 10
_ROUTER_TIMEOUT_SECONDS = 10.0
_WATCHDOG_INTERVAL_SECONDS = 5.0
_WATCHDOG_SHUTDOWN_SECONDS = 5.0


class LauncherError(RuntimeError):
    exit_code = INFRA_ERROR


class ModelMissingError(LauncherError):
    exit_code = MODEL_MISSING


@dataclass(frozen=True)
class RuntimeInspection:
    status: str
    binary: Path | None
    detail: str
    identity_sha256: str | None = None
    capability: str = "not_checked"
    model_backed_validation: str = "not_run"

    @property
    def ok(self) -> bool:
        return self.status == "runtime_ready"


@dataclass(frozen=True)
class RouterProbe:
    status: str
    detail: str

    @property
    def ok(self) -> bool:
        return self.status == "router_ready"


@dataclass(frozen=True)
class RuntimeLock:
    relative_path: str
    regular_files: dict[str, str]
    symlinks: dict[str, str]
    dependency_probe_path: str = "/usr/bin/ldd"
    dependency_probe_sha256: str = ""
    host_dependencies: dict[str, str] | None = None

    @property
    def identity_sha256(self) -> str:
        canonical = json.dumps(
            {
                "regular_files": self.regular_files,
                "relative_path": self.relative_path,
                "symlinks": self.symlinks,
                "dependency_probe_path": self.dependency_probe_path,
                "dependency_probe_sha256": self.dependency_probe_sha256,
                "host_dependencies": self.host_dependencies,
            },
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


def resolve_binary(config: RuntimeConfig, settings: LocalApprovalSettings) -> Path | None:
    configured = Path(settings.binary)
    if configured.is_absolute() or configured.parent != Path("."):
        candidate = resolve_config_path(config, settings.binary)
        found = candidate if candidate.is_file() and os.access(candidate, os.X_OK) else None
    else:
        path_value = shutil.which(settings.binary)
        found = Path(path_value).resolve() if path_value else None
    if found is None:
        return None
    try:
        resolved = found.resolve(strict=True)
        resolved.relative_to(config.paths.common_root.resolve(strict=True))
    except (OSError, ValueError):
        return None
    # Execute the already-inspected canonical target, never the configurable
    # symlink spelling that could be retargeted between inspection and Popen.
    return resolved


def inspect_runtime(config: RuntimeConfig, settings: LocalApprovalSettings) -> RuntimeInspection:
    binary = resolve_binary(config, settings)
    if binary is None:
        return RuntimeInspection("runtime_missing", None, "pinned llama-server binary is unavailable")
    try:
        runtime_identity = _verify_runtime_closure(config, binary)
    except (OSError, ValueError):
        return RuntimeInspection(
            "runtime_pin_mismatch",
            binary,
            "llama.cpp runtime directory closure does not match b10333",
        )
    try:
        completed = subprocess.run(
            [os.fspath(binary), "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=_VERSION_TIMEOUT_SECONDS,
            env=_sanitized_environment(),
        )
    except (OSError, subprocess.SubprocessError):
        return RuntimeInspection("runtime_invalid", binary, "llama-server version probe failed")
    version = f"{completed.stdout}\n{completed.stderr}"
    commit_matches = LLAMA_CPP_COMMIT in version or LLAMA_CPP_COMMIT[:8] in version
    build_matches = re.search(r"(?<!\d)10333(?!\d)", version) is not None
    if completed.returncode != 0 or not build_matches or not commit_matches:
        return RuntimeInspection("runtime_pin_mismatch", binary, "llama-server does not match b10333")
    return RuntimeInspection(
        "runtime_ready",
        binary,
        "llama.cpp b10333 CPU x64 runtime is available; model/GPU serving is not validated",
        runtime_identity,
        "cpu_only_x64",
        "not_run",
    )


def _binary_sha256(path: Path) -> str:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        after = os.fstat(descriptor)
    finally:
        os.close(descriptor)
    if (
        not stat.S_ISREG(before.st_mode)
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise OSError("llama-server changed while being hashed")
    return digest.hexdigest()


def _load_runtime_lock(config: RuntimeConfig) -> RuntimeLock:
    path = config.paths.worktree_root / "eval/locks/llama-cpp-b10333.json"
    if path.is_symlink() or not path.is_file():
        raise OSError("llama.cpp runtime lock is unavailable")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OSError("llama.cpp runtime lock is invalid") from exc
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "project",
        "release",
        "source_commit",
        "asset",
        "installed_runtime",
        "capability",
        "model_backed_structured_output",
    }:
        raise ValueError("llama.cpp runtime lock schema differs")
    asset = value.get("asset")
    installed = value.get("installed_runtime")
    if (
        value.get("schema_version") != 2
        or value.get("project") != "ggml-org/llama.cpp"
        or value.get("release") != "b10333"
        or value.get("source_commit") != LLAMA_CPP_COMMIT
        or not isinstance(asset, dict)
        or asset.get("sha256") != LLAMA_CPP_ASSET_SHA256
        or not isinstance(installed, dict)
        or set(installed)
        != {
            "relative_path",
            "regular_files",
            "symlinks",
            "dependency_probe",
            "host_dependencies",
        }
    ):
        raise ValueError("llama.cpp runtime lock identity differs")
    relative_path = installed.get("relative_path")
    regular_files = installed.get("regular_files")
    symlinks = installed.get("symlinks")
    dependency_probe = installed.get("dependency_probe")
    host_dependencies = installed.get("host_dependencies")
    if (
        relative_path != "eval-data/tools/llama-b10333"
        or not isinstance(regular_files, dict)
        or not isinstance(symlinks, dict)
        or not isinstance(dependency_probe, dict)
        or set(dependency_probe) != {"canonical_path", "sha256"}
        or dependency_probe.get("canonical_path") != "/usr/bin/ldd"
        or not isinstance(dependency_probe.get("sha256"), str)
        or not isinstance(host_dependencies, dict)
        or not host_dependencies
        or regular_files.get("llama-server") != LLAMA_CPP_BINARY_SHA256
    ):
        raise ValueError("llama.cpp runtime manifest is invalid")
    _validate_runtime_entries(regular_files, symlinks)
    _validate_host_dependencies(host_dependencies)
    if re.fullmatch(r"[0-9a-f]{64}", dependency_probe["sha256"]) is None:
        raise ValueError("llama.cpp dependency probe digest is invalid")
    return RuntimeLock(
        relative_path,
        dict(regular_files),
        dict(symlinks),
        dependency_probe["canonical_path"],
        dependency_probe["sha256"],
        dict(host_dependencies),
    )


def _validate_runtime_entries(
    regular_files: Mapping[str, Any], symlinks: Mapping[str, Any]
) -> None:
    if not regular_files or set(regular_files) & set(symlinks):
        raise ValueError("llama.cpp runtime entries are invalid")
    for name, digest in regular_files.items():
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or name in {"", ".", ".."}
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise ValueError("llama.cpp regular-file entry is invalid")
    for name, target in symlinks.items():
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or name in {"", ".", ".."}
            or not isinstance(target, str)
            or Path(target).name != target
            or target not in set(regular_files) | set(symlinks)
        ):
            raise ValueError("llama.cpp symlink entry is invalid")
        seen = {name}
        while target in symlinks:
            if target in seen:
                raise ValueError("llama.cpp symlink entries contain a cycle")
            seen.add(target)
            target = symlinks[target]
        if target not in regular_files:
            raise ValueError("llama.cpp symlink target is not a regular file")


def _validate_host_dependencies(host_dependencies: Mapping[str, Any]) -> None:
    for path, digest in host_dependencies.items():
        if (
            not isinstance(path, str)
            or not Path(path).is_absolute()
            or Path(path).resolve(strict=False) != Path(path)
            or not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise ValueError("llama.cpp host dependency entry is invalid")


def _verify_runtime_closure(config: RuntimeConfig, binary: Path) -> str:
    runtime_lock = _load_runtime_lock(config)
    configured_root = config.paths.common_root / runtime_lock.relative_path
    root_before = os.lstat(configured_root)
    if not stat.S_ISDIR(root_before.st_mode) or stat.S_ISLNK(root_before.st_mode):
        raise ValueError("llama.cpp runtime root is not a real directory")
    _reject_unsafe_mode(root_before.st_mode, "llama.cpp runtime root")
    runtime_root = configured_root.resolve(strict=True)
    if binary.resolve(strict=True) != runtime_root / "llama-server":
        raise ValueError("configured llama-server does not belong to the frozen runtime")
    actual_regular, actual_symlinks = _scan_runtime_root(runtime_root)
    expected_entries = (set(runtime_lock.regular_files), set(runtime_lock.symlinks))
    if (actual_regular, actual_symlinks) != expected_entries:
        raise ValueError("llama.cpp runtime directory entries differ")
    for name, expected in runtime_lock.regular_files.items():
        if _binary_sha256(runtime_root / name) != expected:
            raise ValueError("llama.cpp runtime file digest differs")
    for name, expected in runtime_lock.symlinks.items():
        if os.readlink(runtime_root / name) != expected:
            raise ValueError("llama.cpp runtime symlink differs")
    _verify_host_dependency_closure(runtime_lock, runtime_root)
    if _scan_runtime_root(runtime_root) != expected_entries:
        raise ValueError("llama.cpp runtime changed during inspection")
    root_after = os.lstat(configured_root)
    if (
        root_before.st_dev,
        root_before.st_ino,
        root_before.st_mode,
        root_before.st_mtime_ns,
    ) != (
        root_after.st_dev,
        root_after.st_ino,
        root_after.st_mode,
        root_after.st_mtime_ns,
    ):
        raise ValueError("llama.cpp runtime root changed during inspection")
    return runtime_lock.identity_sha256


def _scan_runtime_root(runtime_root: Path) -> tuple[set[str], set[str]]:
    actual_regular: set[str] = set()
    actual_symlinks: set[str] = set()
    with os.scandir(runtime_root) as entries:
        for entry in entries:
            if entry.is_symlink():
                actual_symlinks.add(entry.name)
            elif entry.is_file(follow_symlinks=False):
                _reject_unsafe_mode(entry.stat(follow_symlinks=False).st_mode, entry.name)
                actual_regular.add(entry.name)
            else:
                raise ValueError("llama.cpp runtime contains an unsupported entry")
    return actual_regular, actual_symlinks


def _reject_unsafe_mode(mode: int, label: str) -> None:
    forbidden = stat.S_ISUID | stat.S_ISGID | stat.S_IWGRP | stat.S_IWOTH
    if mode & forbidden:
        raise ValueError(f"{label} has an unsafe mode")


def _verify_host_dependency_closure(
    runtime_lock: RuntimeLock, runtime_root: Path
) -> None:
    expected = runtime_lock.host_dependencies
    if not isinstance(expected, dict) or not expected:
        raise ValueError("llama.cpp host dependency lock is missing")
    probe = Path(runtime_lock.dependency_probe_path)
    if probe.is_symlink() or not probe.is_file():
        raise ValueError("llama.cpp dependency probe is unavailable")
    _reject_unsafe_mode(os.lstat(probe).st_mode, "llama.cpp dependency probe")
    if _binary_sha256(probe) != runtime_lock.dependency_probe_sha256:
        raise ValueError("llama.cpp dependency probe digest differs")

    candidates = [runtime_root / "llama-server"] + [
        runtime_root / name
        for name in sorted(runtime_lock.regular_files)
        if name.startswith("libggml-cpu-") and name.endswith(".so")
    ]
    observed: set[str] = set()
    for candidate in candidates:
        try:
            completed = subprocess.run(
                [os.fspath(probe), os.fspath(candidate)],
                check=False,
                capture_output=True,
                text=True,
                timeout=_VERSION_TIMEOUT_SECONDS,
                env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("llama.cpp dependency probe failed") from exc
        if completed.returncode != 0:
            raise ValueError("llama.cpp dependency probe failed")
        for raw_line in completed.stdout.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("linux-vdso.so.1 "):
                continue
            if "=>" in line:
                resolved_text = line.split("=>", 1)[1].strip().split(" ", 1)[0]
                if resolved_text == "not":
                    raise ValueError("llama.cpp dependency is unavailable")
            else:
                resolved_text = line.split(" ", 1)[0]
            if not resolved_text.startswith("/"):
                raise ValueError("llama.cpp dependency probe output is invalid")
            resolved = Path(resolved_text).resolve(strict=True)
            try:
                resolved.relative_to(runtime_root)
            except ValueError:
                observed.add(os.fspath(resolved))
    if observed != set(expected):
        raise ValueError("llama.cpp host dependency paths differ")
    if _binary_sha256(probe) != runtime_lock.dependency_probe_sha256:
        raise ValueError("llama.cpp dependency probe changed during inspection")
    for path, digest in expected.items():
        dependency = Path(path)
        _reject_unsafe_mode(os.lstat(dependency).st_mode, path)
        if _binary_sha256(dependency) != digest:
            raise ValueError("llama.cpp host dependency digest differs")


def model_path(config: RuntimeConfig, settings: LocalApprovalSettings) -> Path:
    if not settings.model_path:
        raise ModelMissingError("local model path is empty")
    path = resolve_config_path(config, settings.model_path)
    if path.is_symlink() or not path.is_file():
        raise ModelMissingError("configured local model is missing")
    if path.suffix.lower() != ".gguf":
        raise ConfigError("configured local model must be a GGUF file")
    try:
        with path.open("rb") as stream:
            magic = stream.read(4)
        digest = _binary_sha256(path)
    except OSError as exc:
        raise ConfigError("configured local model cannot be inspected") from exc
    if magic != b"GGUF":
        raise ConfigError("configured local model does not have a GGUF header")
    if digest != settings.model_sha256:
        raise ConfigError("configured local model digest differs")
    return path.resolve(strict=True)


def build_serve_command(
    config: RuntimeConfig,
    settings: LocalApprovalSettings,
    binary: Path,
) -> list[str]:
    """Build the formal serve command; never falls back to router mode.

    These b10333 model-serving flags are intentionally generated from the
    frozen TOML contract but remain pending verification with the installed
    binary and a real model.  In particular, ``gpu_layers = "auto"`` is a
    RONDO policy mapped to 99 layers, not an upstream llama.cpp ``auto`` value.
    The model-free doctor path never executes this command.
    """

    model = model_path(config, settings)
    command = [
        os.fspath(binary),
        "--offline",
        "--no-models-autoload",
        "--no-ui",
        "--host",
        settings.host,
        "--port",
        str(settings.port),
        "--model",
        os.fspath(model),
        "--alias",
        settings.model_id,
        "--parallel",
        str(settings.parallel),
        "--flash-attn",
        settings.flash_attention,
        "--n-gpu-layers",
        "99" if settings.gpu_layers == "auto" else str(settings.gpu_layers),
    ]
    if settings.context_size > 0:
        command.extend(["--ctx-size", str(settings.context_size)])
    if settings.metrics:
        command.append("--metrics")
    if settings.slots:
        command.append("--slots")
    return command


def serve_environment(config: RuntimeConfig) -> dict[str, str]:
    """Map an optional repository secret only to llama.cpp's environment API."""

    environment = _sanitized_environment()
    secret = load_local_model_secret(config)
    if secret is not None:
        environment["LLAMA_API_KEY"] = secret[1]
    return environment


def run_server(
    config: RuntimeConfig,
    *,
    watchdog_factory: Callable[[], runtime_bridge.WatchdogProof] | None = None,
    popen: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
    identity_publisher: Callable[..., LauncherIdentity] = publish_launcher_identity,
    identity_clearer: Callable[[RuntimeConfig, LauncherIdentity], None] = clear_launcher_identity,
    watchdog_interval_seconds: float = _WATCHDOG_INTERVAL_SECONDS,
) -> int:
    settings = settings_from_config(config)
    # The model check deliberately precedes runtime probing so an empty formal
    # configuration reports the stable model-missing exit without server work.
    model = model_path(config, settings)
    if watchdog_interval_seconds <= 0:
        raise ConfigError("watchdog interval must be positive")
    try:
        watchdog = (watchdog_factory or runtime_bridge.lease_from_watchdog)()
        watchdog.lease.validate()
    except (AttributeError, TypeError, runtime_bridge.RuntimeBridgeError) as exc:
        raise LauncherError("shared watchdog lease is unavailable") from exc
    if not _watchdog_held(watchdog):
        raise LauncherError("shared watchdog lease is unavailable")

    runtime = inspect_runtime(config, settings)
    if not runtime.ok or runtime.binary is None or runtime.identity_sha256 is None:
        raise LauncherError(runtime.detail)
    if runtime.capability != GPU_MODEL_SERVING_CAPABILITY:
        raise LauncherError(
            "the pinned runtime is CPU-only; GPU/model serving remains unvalidated"
        )
    command = build_serve_command(config, settings, runtime.binary)
    environment = serve_environment(config)
    if not _watchdog_held(watchdog):
        raise LauncherError("shared watchdog lease was lost before server start")
    try:
        process = popen(command, env=environment)
    except (OSError, ValueError) as exc:
        raise LauncherError("llama-server could not be started") from exc
    try:
        identity = identity_publisher(
            config,
            pid=process.pid,
            command=command,
            runtime_sha256=runtime.identity_sha256,
            model_sha256=settings.model_sha256,
            model_path=model,
            model_id=settings.model_id,
            base_url=settings.base_url,
            host=settings.host,
            port=settings.port,
        )
    except (AttributeError, OSError, ConfigError) as exc:
        _stop_server_process(process)
        raise LauncherError("local approval launcher identity could not be published") from exc
    try:
        while True:
            try:
                return process.wait(timeout=watchdog_interval_seconds)
            except subprocess.TimeoutExpired:
                if not _watchdog_held(watchdog):
                    _stop_server_process(process)
                    raise LauncherError("shared watchdog lease was lost during server execution")
    except KeyboardInterrupt:
        _stop_server_process(process)
        return 130
    finally:
        identity_clearer(config, identity)


def _watchdog_held(watchdog: runtime_bridge.WatchdogProof) -> bool:
    try:
        return watchdog.guard.is_held(watchdog.lease) is True
    except Exception:
        return False


def _stop_server_process(process: subprocess.Popen[Any]) -> None:
    """Stop only the process created by this launcher, escalating if needed."""

    try:
        process.terminate()
    except OSError:
        pass
    try:
        process.wait(timeout=_WATCHDOG_SHUTDOWN_SECONDS)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.kill()
    except OSError:
        pass
    try:
        process.wait()
    except OSError:
        pass


def probe_router_runtime(
    config: RuntimeConfig,
    settings: LocalApprovalSettings,
    runtime: RuntimeInspection,
) -> RouterProbe:
    """Start b10333 briefly without `-m`/`-hf` and verify router identity."""

    if not runtime.ok or runtime.binary is None:
        return RouterProbe("runtime_unavailable", runtime.detail)
    port = _unused_loopback_port()
    command = [
        os.fspath(runtime.binary),
        "--offline",
        "--no-models-autoload",
        "--no-ui",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    try:
        process = subprocess.Popen(
            command,
            env=_sanitized_environment(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return RouterProbe("router_start_failed", "model-free router could not be started")
    try:
        deadline = time.monotonic() + _ROUTER_TIMEOUT_SECONDS
        health: Any = None
        while time.monotonic() < deadline:
            if process.poll() is not None:
                return RouterProbe("router_exited", "model-free router exited before becoming healthy")
            try:
                health = _get_json(f"http://127.0.0.1:{port}/health", timeout=0.5)
                break
            except (urllib.error.URLError, TimeoutError, OSError, ValueError):
                time.sleep(0.05)
        if not isinstance(health, dict) or health.get("status") != "ok":
            return RouterProbe("router_health_invalid", "model-free router health check failed")
        try:
            props = _get_json(f"http://127.0.0.1:{port}/props", timeout=1.0)
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            return RouterProbe("router_props_unavailable", "model-free router props are unavailable")
        build_info = props.get("build_info") if isinstance(props, dict) else None
        if (
            not isinstance(props, dict)
            or props.get("role") != "router"
            or not isinstance(build_info, str)
            or str(LLAMA_CPP_BUILD) not in build_info
            or LLAMA_CPP_COMMIT[:8] not in build_info
        ):
            return RouterProbe("router_schema_invalid", "model-free router props do not match b10333")
        return RouterProbe("router_ready", "model-free b10333 router probe passed")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def _get_json(url: str, *, timeout: float) -> Any:
    request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError("non-200 response")
        raw = response.read(_MAX_PROBE_BYTES + 1)
    if len(raw) > _MAX_PROBE_BYTES:
        raise ValueError("response too large")
    return json.loads(raw)


_MAX_PROBE_BYTES = 65_536


def _unused_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _sanitized_environment() -> dict[str, str]:
    allowed = {
        "CUDA_VISIBLE_DEVICES",
        "HIP_VISIBLE_DEVICES",
        "LANG",
        "LC_ALL",
        "PATH",
        "TMPDIR",
    }
    return {key: value for key, value in os.environ.items() if key in allowed}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start the pinned local approval server")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        config = load_runtime_config(RepoPaths.discover(args.repo))
        status = run_server(config)
        if status != 0:
            print(json.dumps({"status": "server_exited", "exit_code": status}, sort_keys=True))
            return INFRA_ERROR
        return SUCCESS
    except ModelMissingError:
        print(
            json.dumps(
                {"status": "model_missing_gpu_runtime_unvalidated"},
                sort_keys=True,
            )
        )
        return MODEL_MISSING
    except ConfigError:
        print(json.dumps({"status": "configuration_error"}, sort_keys=True))
        return CONFIG_ERROR
    except LauncherError:
        print(json.dumps({"status": "runtime_error"}, sort_keys=True))
        return INFRA_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
