"""Pinned llama.cpp launcher with a model-free, short-lived router probe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
from . import model_backed
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
LLAMA_CPP_CUDA_BINARY_SHA256 = "97a6b083ea34fea7e4e4440a0ddb734e1a2f6b775f4b31ef68ba5f998a9eeabd"
LLAMA_CPP_CUDA_CAPABILITY = "linux_cuda_built_model_unvalidated"
_CPU_RUNTIME_RELATIVE_PATH = "eval-data/tools/llama-b10333"
_CUDA_RUNTIME_RELATIVE_PATH = model_backed.CUDA_RUNTIME_RELATIVE_PATH
_CPU_RUNTIME_LOCK = "eval/locks/llama-cpp-b10333.json"
_CUDA_RUNTIME_LOCK = "eval/locks/llama-cpp-b10333-cuda-linux-x64.json"
GPU_MODEL_SERVING_CAPABILITY = model_backed.GPU_MODEL_SERVING_CAPABILITY
CHAT_TEMPLATE_REPO = "mistralai/Ministral-3-8B-Instruct-2512"
CHAT_TEMPLATE_REVISION = "5b26027e7b19eeb4b7352e1fed3926375dd2cb4d"
CHAT_TEMPLATE_SOURCE_FILE = "chat_template.jinja"
CHAT_TEMPLATE_RELATIVE_PATH = (
    "eval/templates/local-approval/"
    "ministral-3-8b-instruct-2512-chat-template.jinja"
)
CHAT_TEMPLATE_SIZE_BYTES = 11_912
CHAT_TEMPLATE_SHA256 = (
    "74eeb55fd3341286ec3fd44e902b7120721acc81cd394e96b431f85e93a1ea56"
)
_CHAT_TEMPLATE_LOCK_RELATIVE_PATH = Path(
    "eval/locks/ministral-3-8b-instruct-2512-chat-template.json"
)
_CHAT_TEMPLATE_ALLOWED_RELATIVE_ROOT = Path("eval/templates/local-approval")
_VERSION_TIMEOUT_SECONDS = 10
_DEVICE_TIMEOUT_SECONDS = 10
_ROUTER_TIMEOUT_SECONDS = 10.0
_WATCHDOG_INTERVAL_SECONDS = 5.0
_WATCHDOG_SHUTDOWN_SECONDS = 5.0


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Mapping[str, str],
        newurl: str,
    ) -> None:
        return None


_LOOPBACK_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),
    _NoRedirectHandler(),
)


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
    capability: str = "cpu_only_x64"
    model_backed_validation: str = "not_run"
    dependency_targets: tuple[str, ...] = ()
    elf_probe_path: str = ""
    elf_probe_sha256: str = ""
    elf_runpath: str = ""
    elf_needed: dict[str, tuple[str, ...]] | None = None
    identity_files: dict[str, str] | None = None
    identity_extra: dict[str, Any] | None = None

    @property
    def identity_sha256(self) -> str:
        value: dict[str, Any] = {
            "regular_files": self.regular_files,
            "relative_path": self.relative_path,
            "symlinks": self.symlinks,
            "dependency_probe_path": self.dependency_probe_path,
            "dependency_probe_sha256": self.dependency_probe_sha256,
            "host_dependencies": self.host_dependencies,
        }
        if self.identity_extra is not None:
            value.update(
                {
                    "capability": self.capability,
                    "model_backed_validation": self.model_backed_validation,
                    "dependency_targets": self.dependency_targets,
                    "elf_probe_path": self.elf_probe_path,
                    "elf_probe_sha256": self.elf_probe_sha256,
                    "elf_runpath": self.elf_runpath,
                    "elf_needed": self.elf_needed,
                    "identity_files": self.identity_files,
                    "identity_extra": self.identity_extra,
                }
            )
        canonical = json.dumps(
            value,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class ChatTemplateInspection:
    path: Path
    size_bytes: int
    sha256: str


def resolve_binary(config: RuntimeConfig, settings: LocalApprovalSettings) -> Path | None:
    configured = Path(settings.binary)
    allowed = {
        Path(_CPU_RUNTIME_RELATIVE_PATH) / "llama-server",
        Path(_CUDA_RUNTIME_RELATIVE_PATH) / "llama-server",
    }
    if configured.is_absolute() or configured not in allowed:
        return None
    candidate = resolve_config_path(config, settings.binary)
    current = config.paths.common_root.resolve(strict=True)
    try:
        for index, component in enumerate(configured.parts):
            current /= component
            mode = os.lstat(current).st_mode
            if stat.S_ISLNK(mode):
                return None
            if index < len(configured.parts) - 1 and not stat.S_ISDIR(mode):
                return None
        found = (
            candidate
            if stat.S_ISREG(mode) and os.access(candidate, os.X_OK)
            else None
        )
    except OSError:
        found = None
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
        is_cuda = (
            _runtime_relative_path_for_binary(config, binary)
            == _CUDA_RUNTIME_RELATIVE_PATH
        )
    except (OSError, ValueError):
        # The real closure verifier rejects unknown paths. This fallback keeps
        # isolated probe fixtures backend-neutral when that verifier is mocked.
        is_cuda = False
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
    commit_prefix = LLAMA_CPP_COMMIT[:7] if is_cuda else LLAMA_CPP_COMMIT[:8]
    commit_matches = LLAMA_CPP_COMMIT in version or commit_prefix in version
    # A source build from the shallow b10333 tag reports build number 1; its
    # exact binary, commit, source tree and configure identity are bound by the
    # CUDA lock. The upstream release bundle continues to require 10333 here.
    build_matches = is_cuda or re.search(r"(?<!\d)10333(?!\d)", version) is not None
    if completed.returncode != 0 or not build_matches or not commit_matches:
        return RuntimeInspection("runtime_pin_mismatch", binary, "llama-server does not match b10333")
    if is_cuda:
        try:
            devices = subprocess.run(
                [os.fspath(binary), "--list-devices"],
                check=False,
                capture_output=True,
                text=True,
                timeout=_DEVICE_TIMEOUT_SECONDS,
                env=_sanitized_environment(),
            )
        except (OSError, subprocess.SubprocessError):
            return RuntimeInspection(
                "runtime_device_unavailable",
                binary,
                "llama-server CUDA device probe failed",
            )
        device_output = f"{devices.stdout}\n{devices.stderr}"
        if (
            devices.returncode != 0
            or "CUDA0: NVIDIA GeForce RTX 4060 Laptop GPU" not in device_output
        ):
            return RuntimeInspection(
                "runtime_device_unavailable",
                binary,
                "the frozen CUDA runtime cannot enumerate the RTX 4060 Laptop GPU",
            )
    if not is_cuda:
        return RuntimeInspection(
            "runtime_ready",
            binary,
            "llama.cpp b10333 CPU x64 runtime is available; model/GPU serving is not validated",
            runtime_identity,
            "cpu_only_x64",
            model_backed.MODEL_BACKED_NOT_RUN,
        )
    capability, validation = _model_backed_capability(config, settings, runtime_identity)
    return RuntimeInspection(
        "runtime_ready",
        binary,
        (
            "llama.cpp b10333 Linux CUDA runtime serves the qualified 4k model contract"
            if capability == GPU_MODEL_SERVING_CAPABILITY
            else "llama.cpp b10333 Linux CUDA runtime is available; model-backed serving is not validated"
        ),
        runtime_identity,
        capability,
        validation,
    )


def _model_backed_capability(
    config: RuntimeConfig, settings: LocalApprovalSettings, runtime_identity: str
) -> tuple[str, str]:
    """Promote the CUDA runtime only from strict, matching model-backed evidence.

    Every failure keeps the intermediate capability, so a missing, malformed or
    stale evidence file can never let the formal launcher start a model.
    """

    try:
        evidence = model_backed.load_model_backed_evidence(config)
    except model_backed.EvidenceLockError:
        return LLAMA_CPP_CUDA_CAPABILITY, model_backed.MODEL_BACKED_EVIDENCE_INVALID
    if evidence is None:
        return LLAMA_CPP_CUDA_CAPABILITY, model_backed.MODEL_BACKED_NOT_RUN
    try:
        model_backed.require_qualification_contract(config, settings)
        identity = model_backed.build_identity(
            settings,
            runtime_identity_sha256=runtime_identity,
            serve_config_sha256=serve_config_sha256(config, settings),
        )
    except (ConfigError, OSError, ValueError):
        return LLAMA_CPP_CUDA_CAPABILITY, model_backed.MODEL_BACKED_IDENTITY_MISMATCH
    if not evidence.matches(identity):
        return LLAMA_CPP_CUDA_CAPABILITY, model_backed.MODEL_BACKED_IDENTITY_MISMATCH
    return GPU_MODEL_SERVING_CAPABILITY, model_backed.MODEL_BACKED_VALIDATED


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


def _runtime_relative_path_for_binary(config: RuntimeConfig, binary: Path) -> str:
    common_root = config.paths.common_root.resolve(strict=True)
    resolved = binary.resolve(strict=True)
    for relative_path in (_CPU_RUNTIME_RELATIVE_PATH, _CUDA_RUNTIME_RELATIVE_PATH):
        expected = (common_root / relative_path / "llama-server").resolve(strict=False)
        if resolved == expected:
            return relative_path
    raise ValueError("configured llama-server does not map to a frozen runtime")


def _load_runtime_lock(config: RuntimeConfig, binary: Path) -> RuntimeLock:
    relative_path = _runtime_relative_path_for_binary(config, binary)
    lock_relative_path = (
        _CUDA_RUNTIME_LOCK
        if relative_path == _CUDA_RUNTIME_RELATIVE_PATH
        else _CPU_RUNTIME_LOCK
    )
    path = config.paths.worktree_root / lock_relative_path
    if path.is_symlink() or not path.is_file():
        raise OSError("llama.cpp runtime lock is unavailable")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise OSError("llama.cpp runtime lock is invalid") from exc
    if relative_path == _CUDA_RUNTIME_RELATIVE_PATH:
        return _load_cuda_runtime_lock(value)
    return _load_cpu_runtime_lock(value)


def _load_cpu_runtime_lock(value: Any) -> RuntimeLock:
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
        relative_path != _CPU_RUNTIME_RELATIVE_PATH
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


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{label} digest is invalid")
    return value


def _load_cuda_runtime_lock(value: Any) -> RuntimeLock:
    expected_top_level = {
        "schema_version",
        "project",
        "release",
        "source",
        "toolkit",
        "toolchain",
        "build",
        "installed_runtime",
        "device_probe",
        "capability",
        "model_backed_structured_output",
    }
    if not isinstance(value, dict) or set(value) != expected_top_level:
        raise ValueError("llama.cpp CUDA runtime lock schema differs")
    source = value.get("source")
    toolkit = value.get("toolkit")
    toolchain = value.get("toolchain")
    build = value.get("build")
    installed = value.get("installed_runtime")
    device_probe = value.get("device_probe")
    if (
        value.get("schema_version") != 1
        or value.get("project") != "ggml-org/llama.cpp"
        or value.get("release") != "b10333"
        or value.get("capability") != LLAMA_CPP_CUDA_CAPABILITY
        or value.get("model_backed_structured_output") != "not_run"
        or not isinstance(source, dict)
        or set(source) != {"repo", "tag", "commit", "tree", "clean"}
        or source.get("repo") != "https://github.com/ggml-org/llama.cpp.git"
        or source.get("tag") != "b10333"
        or source.get("commit") != LLAMA_CPP_COMMIT
        or source.get("tree") != "9ae780f13650ac3d45e4e345f208163ad744dd6d"
        or source.get("clean") is not True
        or not isinstance(toolkit, dict)
        or not isinstance(toolchain, dict)
        or not isinstance(build, dict)
        or not isinstance(installed, dict)
        or not isinstance(device_probe, dict)
    ):
        raise ValueError("llama.cpp CUDA runtime lock identity differs")
    installer = toolkit.get("installer")
    nvcc = toolkit.get("nvcc")
    if (
        set(toolkit) != {"version", "local_path", "version_json_sha256", "installer", "nvcc"}
        or toolkit.get("version") != "12.6.2"
        or toolkit.get("local_path")
        != "/home/sjc/desktop/RONDO/eval-data/toolkits/cuda-12.6.2"
        or not isinstance(installer, dict)
        or set(installer) != {"url", "size_bytes", "md5", "sha256"}
        or installer.get("url")
        != "https://developer.download.nvidia.com/compute/cuda/12.6.2/local_installers/cuda_12.6.2_560.35.03_linux.run"
        or installer.get("size_bytes") != 4_446_677_374
        or installer.get("md5") != "dcba85e2d49d7e6d93d8626f708276a4"
        or installer.get("sha256")
        != "3729a89cb58f7ca6a46719cff110d6292aec7577585a8d71340f0dbac54fb237"
        or not isinstance(nvcc, dict)
        or set(nvcc) != {"path", "release", "build", "sha256"}
        or nvcc.get("path")
        != "/home/sjc/desktop/RONDO/eval-data/toolkits/cuda-12.6.2/bin/nvcc"
        or nvcc.get("release") != "12.6"
        or nvcc.get("build") != "12.6.77"
        or nvcc.get("sha256")
        != "4101d601fa1edc5538265ecaa57ecb61be56deb6f6c80fba6e6362fc1b6bae5b"
    ):
        raise ValueError("llama.cpp CUDA Toolkit identity differs")
    _require_sha256(toolkit.get("version_json_sha256"), "CUDA version.json")

    identity_files = toolchain.get("identity_files")
    expected_versions = {
        "cmake": "3.28.3",
        "gcc": "13.3.0",
        "g++": "13.3.0",
        "make": "4.3",
        "nvcc": "12.6.77",
        "glibc": "2.39-0ubuntu8.8",
        "binutils": "2.42",
    }
    expected_toolchain_sha256 = {
        "/home/sjc/desktop/RONDO/eval-data/toolkits/cuda-12.6.2/bin/nvcc":
        "4101d601fa1edc5538265ecaa57ecb61be56deb6f6c80fba6e6362fc1b6bae5b",
        "/home/sjc/desktop/RONDO/eval-data/toolkits/cuda-12.6.2/version.json":
        "81d2854ee182334d49a1f181d38a55feb1cbc3df7ba93d32ff9d647c511a1b59",
    }
    expected_identity_files = {
        "/usr/bin/cmake":
        "1c5227af4edd22d8d689def545e18ee458260c0fd579eba2187967f38817e638",
        "/usr/bin/ldd":
        "4f1d37e25f27535e3f02a5b7da63e1ce18d4982445db2c25fc8f985a3d395cc3",
        "/usr/bin/make":
        "d78b8f1d099fbcfb6f2f49ab87223b9b68fb3956642f92d6ec6de812e8afa965",
        "/usr/bin/x86_64-linux-gnu-g++-13":
        "1353e9bdd29a7295c7226bf6c63abccce056d8cac31f112e5cdbecc3f28c2769",
        "/usr/bin/x86_64-linux-gnu-gcc-13":
        "1b99826121ae6682a634e5efe09bd3e3df58ce58e0b28f849114ab5b89139c26",
        "/usr/bin/x86_64-linux-gnu-objdump":
        "325c4205a4c658a9d1e1ebc469ae55975a2b897a3d3c1e79d9b158612d37f745",
        "/usr/bin/x86_64-linux-gnu-readelf":
        "64c58e15274bbbb5153f31078e455e9e77ee5f51489e709bba5bb788ce9df2b0",
    }
    if set(toolchain) != {"versions", "identity_files"} or not isinstance(
        identity_files, dict
    ):
        raise ValueError("llama.cpp CUDA toolchain lock is invalid")
    _validate_host_dependencies(identity_files)
    if (
        toolchain.get("versions") != expected_versions
        or identity_files
        != {**expected_toolchain_sha256, **expected_identity_files}
        or expected_toolchain_sha256[nvcc["path"]] != nvcc["sha256"]
        or expected_toolchain_sha256[
            "/home/sjc/desktop/RONDO/eval-data/toolkits/cuda-12.6.2/version.json"
        ] != toolkit["version_json_sha256"]
    ):
        raise ValueError("llama.cpp CUDA toolchain versions are invalid")

    required_build = {
        "source_path",
        "build_path",
        "runtime_path",
        "generator",
        "architecture",
        "configure_argv",
        "build_argv",
        "cmake_cache_sha256",
        "build_lock",
        "artifact_staging",
        "cub_3dot2",
        "permissive_linker_flag",
    }
    if (
        set(build) != required_build
        or build.get("source_path")
        != "/home/sjc/desktop/RONDO/eval-data/sources/llama.cpp-b10333-08659901"
        or build.get("build_path")
        != "/home/sjc/desktop/RONDO/eval-data/build/llama.cpp-b10333-cuda-linux-x64"
        or build.get("runtime_path")
        != "/home/sjc/desktop/RONDO/eval-data/tools/llama-b10333-cuda-linux-x64"
        or build.get("generator") != "Unix Makefiles"
        or build.get("architecture") != "89-real"
        or build.get("cub_3dot2") is not False
        or build.get("permissive_linker_flag") is not False
        or not isinstance(build.get("configure_argv"), list)
        or not build["configure_argv"]
        or not isinstance(build.get("build_argv"), list)
        or not build["build_argv"]
        or not isinstance(build.get("build_lock"), dict)
        or build.get("artifact_staging")
        != {
            "source": "/home/sjc/desktop/RONDO/eval-data/build/llama.cpp-b10333-cuda-linux-x64/bin",
            "destination": "/home/sjc/desktop/RONDO/eval-data/tools/llama-b10333-cuda-linux-x64",
            "method": "copy exact bin closure, preserve symlinks, set runtime files 0755",
        }
    ):
        raise ValueError("llama.cpp CUDA build lock is invalid")
    _require_sha256(build.get("cmake_cache_sha256"), "CMake cache")

    required_installed = {
        "relative_path",
        "regular_files",
        "symlinks",
        "dependency_targets",
        "dependency_probe",
        "elf_probe",
        "elf_runpath",
        "elf_needed",
        "external_dependencies",
    }
    if set(installed) != required_installed:
        raise ValueError("llama.cpp CUDA runtime manifest schema differs")
    relative_path = installed.get("relative_path")
    regular_files = installed.get("regular_files")
    symlinks = installed.get("symlinks")
    dependency_targets = installed.get("dependency_targets")
    dependency_probe = installed.get("dependency_probe")
    elf_probe = installed.get("elf_probe")
    elf_needed = installed.get("elf_needed")
    external_dependencies = installed.get("external_dependencies")
    expected_runpath = (
        "/home/sjc/desktop/RONDO/eval-data/toolkits/cuda-12.6.2/lib64:$ORIGIN"
    )
    if (
        relative_path != _CUDA_RUNTIME_RELATIVE_PATH
        or not isinstance(regular_files, dict)
        or regular_files.get("llama-server") != LLAMA_CPP_CUDA_BINARY_SHA256
        or not isinstance(symlinks, dict)
        or not isinstance(dependency_targets, list)
        or set(dependency_targets) != set(regular_files)
        or not isinstance(dependency_probe, dict)
        or set(dependency_probe) != {"canonical_path", "sha256"}
        or dependency_probe.get("canonical_path") != "/usr/bin/ldd"
        or not isinstance(elf_probe, dict)
        or set(elf_probe) != {"canonical_path", "sha256"}
        or elf_probe.get("canonical_path") != "/usr/bin/x86_64-linux-gnu-readelf"
        or installed.get("elf_runpath") != expected_runpath
        or not isinstance(elf_needed, dict)
        or set(elf_needed) != set(dependency_targets)
        or not isinstance(external_dependencies, dict)
        or not external_dependencies
    ):
        raise ValueError("llama.cpp CUDA runtime manifest is invalid")
    _validate_runtime_entries(regular_files, symlinks)
    _validate_host_dependencies(external_dependencies)
    _require_sha256(dependency_probe.get("sha256"), "dependency probe")
    _require_sha256(elf_probe.get("sha256"), "ELF probe")
    normalized_needed: dict[str, tuple[str, ...]] = {}
    for target, needed in elf_needed.items():
        if not isinstance(needed, list) or any(
            not isinstance(item, str) or not item for item in needed
        ):
            raise ValueError("llama.cpp CUDA DT_NEEDED manifest is invalid")
        normalized_needed[target] = tuple(sorted(needed))

    required_device_probe = {
        "command",
        "environment",
        "exit_code",
        "device",
        "compute_capability",
        "memory_mib",
        "windows_driver",
        "wsl_libcuda",
        "model_loaded",
    }
    wsl_libcuda = device_probe.get("wsl_libcuda")
    if (
        set(device_probe) != required_device_probe
        or device_probe.get("command")
        != [
            "/home/sjc/desktop/RONDO/eval-data/tools/llama-b10333-cuda-linux-x64/llama-server",
            "--list-devices",
        ]
        or device_probe.get("environment") != "LD_LIBRARY_PATH unset"
        or device_probe.get("exit_code") != 0
        or device_probe.get("device") != "NVIDIA GeForce RTX 4060 Laptop GPU"
        or device_probe.get("compute_capability") != "8.9"
        or device_probe.get("memory_mib") != 8187
        or device_probe.get("windows_driver") != "595.79"
        or device_probe.get("model_loaded") is not False
        or wsl_libcuda
        != {
            "canonical_path": "/usr/lib/wsl/lib/libcuda.so.1",
            "size_bytes": 183_752,
            "sha256": "57e0db4fcada1712297e0c9ab0d7d4beff59c663468876f77a262eda98a6e0b8",
        }
    ):
        raise ValueError("llama.cpp CUDA device probe identity differs")

    return RuntimeLock(
        relative_path,
        dict(regular_files),
        dict(symlinks),
        dependency_probe["canonical_path"],
        dependency_probe["sha256"],
        dict(external_dependencies),
        LLAMA_CPP_CUDA_CAPABILITY,
        "not_run",
        tuple(dependency_targets),
        elf_probe["canonical_path"],
        elf_probe["sha256"],
        expected_runpath,
        normalized_needed,
        dict(identity_files),
        {
            "source": source,
            "toolkit": toolkit,
            "toolchain_versions": toolchain["versions"],
            "build": build,
            "device_probe": device_probe,
        },
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
    runtime_lock = _load_runtime_lock(config, binary)
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
    _verify_identity_files(runtime_lock)
    _verify_elf_metadata(runtime_lock, runtime_root)
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


def _verify_identity_files(runtime_lock: RuntimeLock) -> None:
    identity_files = runtime_lock.identity_files
    if identity_files is None:
        return
    for path, digest in identity_files.items():
        identity_file = Path(path)
        if not identity_file.is_file():
            raise ValueError("llama.cpp toolchain identity file is unavailable")
        resolved = identity_file.resolve(strict=True)
        _reject_unsafe_mode(os.lstat(resolved).st_mode, path)
        if _binary_sha256(resolved) != digest:
            raise ValueError("llama.cpp toolchain identity differs")


def _verify_elf_metadata(runtime_lock: RuntimeLock, runtime_root: Path) -> None:
    expected_needed = runtime_lock.elf_needed
    if expected_needed is None:
        return
    probe = Path(runtime_lock.elf_probe_path)
    if probe.is_symlink() or not probe.is_file():
        raise ValueError("llama.cpp ELF probe is unavailable")
    _reject_unsafe_mode(os.lstat(probe).st_mode, "llama.cpp ELF probe")
    if _binary_sha256(probe) != runtime_lock.elf_probe_sha256:
        raise ValueError("llama.cpp ELF probe identity differs")
    for name in runtime_lock.dependency_targets:
        try:
            completed = subprocess.run(
                [os.fspath(probe), "-d", os.fspath(runtime_root / name)],
                check=False,
                capture_output=True,
                text=True,
                timeout=_VERSION_TIMEOUT_SECONDS,
                env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ValueError("llama.cpp ELF probe failed") from exc
        if completed.returncode != 0:
            raise ValueError("llama.cpp ELF probe failed")
        needed = tuple(
            sorted(re.findall(r"Shared library: \[([^]]+)\]", completed.stdout))
        )
        runpaths = re.findall(r"Library runpath: \[([^]]+)\]", completed.stdout)
        rpaths = re.findall(r"Library rpath: \[([^]]+)\]", completed.stdout)
        if (
            needed != expected_needed[name]
            or runpaths != [runtime_lock.elf_runpath]
            or rpaths
        ):
            raise ValueError("llama.cpp ELF metadata differs")
    if _binary_sha256(probe) != runtime_lock.elf_probe_sha256:
        raise ValueError("llama.cpp ELF probe changed during inspection")


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

    if runtime_lock.dependency_targets:
        candidates = [runtime_root / name for name in runtime_lock.dependency_targets]
    else:
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


def chat_template(
    config: RuntimeConfig, settings: LocalApprovalSettings
) -> ChatTemplateInspection:
    """Validate the only frozen tracked template without GGUF fallback."""

    lock_path = config.paths.worktree_root / _CHAT_TEMPLATE_LOCK_RELATIVE_PATH
    if lock_path.is_symlink() or not lock_path.is_file():
        raise ConfigError("frozen chat template lock is unavailable")
    try:
        value = json.loads(lock_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ConfigError("frozen chat template lock is invalid") from exc
    expected_lock = {
        "schema_version": 1,
        "repo": CHAT_TEMPLATE_REPO,
        "revision": CHAT_TEMPLATE_REVISION,
        "source_file": CHAT_TEMPLATE_SOURCE_FILE,
        "installed": {
            "relative_path": CHAT_TEMPLATE_RELATIVE_PATH,
            "size_bytes": CHAT_TEMPLATE_SIZE_BYTES,
            "sha256": CHAT_TEMPLATE_SHA256,
        },
    }
    if value != expected_lock:
        raise ConfigError("frozen chat template lock identity differs")
    if (
        settings.chat_template_file != CHAT_TEMPLATE_RELATIVE_PATH
        or settings.chat_template_sha256 != CHAT_TEMPLATE_SHA256
    ):
        raise ConfigError("configured chat template differs from the frozen lock")

    root = config.paths.worktree_root.resolve(strict=True)
    allowed_root = root / _CHAT_TEMPLATE_ALLOWED_RELATIVE_ROOT
    current = root
    try:
        for component in _CHAT_TEMPLATE_ALLOWED_RELATIVE_ROOT.parts:
            current /= component
            mode = os.lstat(current).st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise ConfigError("frozen chat template has an unsafe ancestor")
        candidate = root / CHAT_TEMPLATE_RELATIVE_PATH
        before = os.lstat(candidate)
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(allowed_root.resolve(strict=True))
    except ConfigError:
        raise
    except (OSError, ValueError) as exc:
        raise ConfigError("frozen chat template path is unavailable or escapes its root") from exc
    if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
        raise ConfigError("frozen chat template must be a regular non-symlink file")
    if before.st_mode & (stat.S_ISUID | stat.S_ISGID | stat.S_IWGRP | stat.S_IWOTH):
        raise ConfigError("frozen chat template has an unsafe mode")
    if before.st_size != CHAT_TEMPLATE_SIZE_BYTES:
        raise ConfigError("frozen chat template size differs")
    try:
        digest = _binary_sha256(candidate)
        after = os.lstat(candidate)
    except OSError as exc:
        raise ConfigError("frozen chat template cannot be inspected") from exc
    if (
        digest != CHAT_TEMPLATE_SHA256
        or (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    ):
        raise ConfigError("frozen chat template digest or identity differs")
    return ChatTemplateInspection(resolved, before.st_size, digest)


def _serve_arguments(
    settings: LocalApprovalSettings,
    model: Path,
    template: ChatTemplateInspection,
) -> list[str]:
    gpu_layers = (
        settings.gpu_layers
        if isinstance(settings.gpu_layers, str)
        else str(settings.gpu_layers)
    )
    arguments = [
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
        "--no-mmproj",
        "--gpu-layers",
        gpu_layers,
        "--split-mode",
        "none",
        "--main-gpu",
        "0",
        "--fit",
        settings.fit,
        "--ctx-size",
        str(settings.context_size),
        "--batch-size",
        str(settings.batch_size),
        "--ubatch-size",
        str(settings.ubatch_size),
        "--parallel",
        str(settings.parallel),
        "--flash-attn",
        settings.flash_attention,
        "--cache-type-k",
        settings.cache_type_k,
        "--cache-type-v",
        settings.cache_type_v,
        # b10333 requires --jinja before a non-built-in template file.
        "--jinja",
        "--chat-template-file",
        os.fspath(template.path),
    ]
    if settings.metrics:
        arguments.append("--metrics")
    if settings.slots:
        arguments.append("--slots")
    return arguments


def _serve_config_sha256(
    settings: LocalApprovalSettings,
    arguments: Sequence[str],
    template: ChatTemplateInspection,
) -> str:
    canonical = {
        "schema_version": 1,
        "runtime": "llama_cpp",
        "api": "responses",
        "format": "gguf",
        "quantization": settings.quantization,
        "configured_binary": settings.binary,
        "tools": False,
        "web_ui": False,
        "command_arguments": list(arguments),
        "chat_template_sha256": template.sha256,
    }
    raw = json.dumps(
        canonical, separators=(",", ":"), sort_keys=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def serve_config_sha256(
    config: RuntimeConfig, settings: LocalApprovalSettings
) -> str:
    """Bind current model-serving configuration without hashing the large GGUF."""

    if not settings.model_path:
        raise ModelMissingError("local model path is empty")
    configured_model = resolve_config_path(config, settings.model_path)
    if configured_model.is_symlink() or not configured_model.is_file():
        raise ModelMissingError("configured local model is missing")
    template = chat_template(config, settings)
    arguments = _serve_arguments(
        settings, configured_model.resolve(strict=True), template
    )
    return _serve_config_sha256(settings, arguments, template)


def build_serve_command(
    config: RuntimeConfig,
    settings: LocalApprovalSettings,
    binary: Path,
) -> list[str]:
    """Build the formal b10333 command; never falls back to router mode."""

    model = model_path(config, settings)
    template = chat_template(config, settings)
    return [os.fspath(binary), *_serve_arguments(settings, model, template)]


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
            "model-backed GPU serving remains unvalidated for the selected runtime"
        )
    template = chat_template(config, settings)
    arguments = _serve_arguments(settings, model, template)
    command = [os.fspath(runtime.binary), *arguments]
    serving_config = _serve_config_sha256(settings, arguments, template)
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
            serve_config_sha256=serving_config,
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
        # The exact expectation follows the configured backend: the source build
        # and the upstream release bundle report different build numbers.
        if (
            not isinstance(props, dict)
            or props.get("role") != "router"
            or props.get("build_info") != model_backed.service_build_info(settings)
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
    with _LOOPBACK_OPENER.open(request, timeout=timeout) as response:
        if response.status != 200 or response.geturl() != url:
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
