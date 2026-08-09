"""Pinned llama.cpp launcher with a model-free, short-lived router probe."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from .. import runtime_bridge
from ..config import ConfigError, RepoPaths, RuntimeConfig, load_local_model_secret, load_runtime_config
from ..exit_codes import CONFIG_ERROR, INFRA_ERROR, MODEL_MISSING, SUCCESS
from .client import LocalApprovalSettings, resolve_config_path, settings_from_config


LLAMA_CPP_BUILD = 10333
LLAMA_CPP_COMMIT = "08659901c43b51de735740f1cf61bb82fbe0c4e4"
LLAMA_CPP_ASSET_SHA256 = "936ce04d98abe2a977e9dd2ff92659bb96947e136acee8f2bc3e21d8eaebbf23"
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
        found.resolve().relative_to(config.paths.common_root.resolve())
    except ValueError:
        return None
    return found


def inspect_runtime(config: RuntimeConfig, settings: LocalApprovalSettings) -> RuntimeInspection:
    binary = resolve_binary(config, settings)
    if binary is None:
        return RuntimeInspection("runtime_missing", None, "pinned llama-server binary is unavailable")
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
    return RuntimeInspection("runtime_ready", binary, "llama.cpp b10333 is available")


def model_path(config: RuntimeConfig, settings: LocalApprovalSettings) -> Path:
    if not settings.model_path:
        raise ModelMissingError("local model path is empty")
    path = resolve_config_path(config, settings.model_path)
    if path.is_symlink() or not path.is_file():
        raise ModelMissingError("configured local model is missing")
    if path.suffix.lower() != ".gguf":
        raise ConfigError("configured local model must be a GGUF file")
    return path


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
    watchdog_interval_seconds: float = _WATCHDOG_INTERVAL_SECONDS,
) -> int:
    settings = settings_from_config(config)
    # The model check deliberately precedes runtime probing: an empty formal
    # configuration must report the stable only-waiting-for-model state.
    model_path(config, settings)
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
    if not runtime.ok or runtime.binary is None:
        raise LauncherError(runtime.detail)
    command = build_serve_command(config, settings, runtime.binary)
    environment = serve_environment(config)
    if not _watchdog_held(watchdog):
        raise LauncherError("shared watchdog lease was lost before server start")
    try:
        process = popen(command, env=environment)
    except (OSError, ValueError) as exc:
        raise LauncherError("llama-server could not be started") from exc
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
        "LD_LIBRARY_PATH",
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
        print(json.dumps({"status": "infrastructure_ready_model_missing"}, sort_keys=True))
        return MODEL_MISSING
    except ConfigError:
        print(json.dumps({"status": "configuration_error"}, sort_keys=True))
        return CONFIG_ERROR
    except LauncherError:
        print(json.dumps({"status": "runtime_error"}, sort_keys=True))
        return INFRA_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
