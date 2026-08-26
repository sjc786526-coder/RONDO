"""Small runtime-environment and bootstrap-ready receipts for Plan 082."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
from typing import Any

from .contract import (
    FullModelTrainingError,
    canonical_json_bytes,
    pretty_json_bytes,
    regular_file,
    safe_directory,
    sha256_bytes,
    write_exclusive,
)


ENVIRONMENT_SCHEMA = "rondo-publication-critic-plan082-environment-v1"
BOOTSTRAP_READY_SCHEMA = "rondo-publication-critic-plan082-bootstrap-ready-v1"
IMAGE_IDENTITY_ENV = "RONDO_PLAN082_IMAGE_IDENTITY"
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CUDA_VERSION = re.compile(r"CUDA Version:\s*([0-9]+(?:\.[0-9]+)*)")


def observe_environment(
    *,
    torch_module: Any | None = None,
    image_identity: str | None = None,
    distributions: Sequence[str] | None = None,
    driver_version: str | None = None,
    nvidia_smi_cuda_version: str | None = None,
) -> dict[str, Any]:
    """Observe the small set of environment facts that freezes execution."""

    torch = torch_module
    if torch is None:
        try:
            torch = importlib.import_module("torch")
        except ImportError as exc:
            raise FullModelTrainingError("plan082_environment_torch_missing") from exc
    image = (
        image_identity if image_identity is not None else os.getenv(IMAGE_IDENTITY_ENV)
    )
    if (
        not isinstance(image, str)
        or not image
        or len(image) > 512
        or any(ord(character) < 0x20 for character in image)
    ):
        raise FullModelTrainingError("plan082_environment_image_identity_missing")
    freeze = (
        sorted(set(distributions))
        if distributions is not None
        else _installed_distribution_freeze()
    )
    if not freeze or any(
        not isinstance(item, str) or not item or "\n" in item or "\r" in item
        for item in freeze
    ):
        raise FullModelTrainingError("plan082_environment_distributions_invalid")
    if driver_version is None or nvidia_smi_cuda_version is None:
        observed_driver, observed_host_cuda = _observe_nvidia_smi()
        driver_version = driver_version or observed_driver
        nvidia_smi_cuda_version = nvidia_smi_cuda_version or observed_host_cuda
    try:
        gpu_count = int(torch.cuda.device_count())
        gpu_names = [
            str(torch.cuda.get_device_name(index)) for index in range(gpu_count)
        ]
        gpu_capabilities = [
            ".".join(str(part) for part in torch.cuda.get_device_capability(index))
            for index in range(gpu_count)
        ]
    except Exception as exc:
        raise FullModelTrainingError(
            "plan082_environment_gpu_observation_failed"
        ) from exc
    core = {
        "schema": ENVIRONMENT_SCHEMA,
        "container_image": image,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable_name": Path(sys.executable).name,
        "driver_version": driver_version,
        "torch_cuda_runtime": str(getattr(torch.version, "cuda", "")),
        "nvidia_smi_cuda_version": nvidia_smi_cuda_version,
        "gpu_count": gpu_count,
        "gpu_names": gpu_names,
        "gpu_compute_capabilities": gpu_capabilities,
        "installed_distributions": freeze,
        "installed_distributions_sha256": sha256_bytes(
            ("\n".join(freeze) + "\n").encode("utf-8")
        ),
    }
    return validate_environment_receipt(
        {
            **core,
            "content_sha256": sha256_bytes(canonical_json_bytes(core)),
        }
    )


def validate_environment_receipt(value: Any) -> dict[str, Any]:
    required = {
        "schema",
        "container_image",
        "python_version",
        "python_implementation",
        "python_executable_name",
        "driver_version",
        "torch_cuda_runtime",
        "nvidia_smi_cuda_version",
        "gpu_count",
        "gpu_names",
        "gpu_compute_capabilities",
        "installed_distributions",
        "installed_distributions_sha256",
        "content_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise FullModelTrainingError("plan082_environment_receipt_invalid")
    core = {key: item for key, item in value.items() if key != "content_sha256"}
    distributions = value.get("installed_distributions")
    gpu_count = value.get("gpu_count")
    if (
        value.get("schema") != ENVIRONMENT_SCHEMA
        or any(
            not isinstance(value.get(key), str) or not value[key]
            for key in (
                "container_image",
                "python_version",
                "python_implementation",
                "python_executable_name",
                "driver_version",
                "torch_cuda_runtime",
                "nvidia_smi_cuda_version",
            )
        )
        or not isinstance(gpu_count, int)
        or isinstance(gpu_count, bool)
        or gpu_count != 1
        or not isinstance(value.get("gpu_names"), list)
        or len(value["gpu_names"]) != gpu_count
        or any(not isinstance(item, str) or not item for item in value["gpu_names"])
        or not isinstance(value.get("gpu_compute_capabilities"), list)
        or len(value["gpu_compute_capabilities"]) != gpu_count
        or any(
            not isinstance(item, str) or not item
            for item in value["gpu_compute_capabilities"]
        )
        or not isinstance(distributions, list)
        or not distributions
        or distributions != sorted(set(distributions))
        or any(not isinstance(item, str) or not item for item in distributions)
        or value.get("installed_distributions_sha256")
        != sha256_bytes(("\n".join(distributions) + "\n").encode("utf-8"))
        or _SHA256.fullmatch(str(value.get("content_sha256"))) is None
        or value.get("content_sha256") != sha256_bytes(canonical_json_bytes(core))
    ):
        raise FullModelTrainingError("plan082_environment_receipt_invalid")
    return json.loads(json.dumps(value))


def publish_environment_receipt(destination: Path) -> dict[str, Any]:
    value = observe_environment()
    _publish_identical(Path(destination), pretty_json_bytes(value))
    return value


def publish_bootstrap_ready_receipt(
    destination: Path,
    *,
    source_receipt: Path,
    data_receipt: Path,
    snapshot_receipt: Path,
    environment_receipt: Path,
    source_root: Path,
    data_root: Path,
    model_root: Path,
) -> dict[str, Any]:
    receipts: dict[str, dict[str, Any]] = {}
    for role, path in (
        ("source", source_receipt),
        ("data", data_receipt),
        ("snapshot", snapshot_receipt),
        ("environment", environment_receipt),
    ):
        source = regular_file(Path(path), maximum_bytes=16 * 1024 * 1024)
        raw = source.read_bytes()
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            raise FullModelTrainingError(
                "plan082_bootstrap_input_receipt_invalid"
            ) from None
        if not isinstance(parsed, Mapping):
            raise FullModelTrainingError("plan082_bootstrap_input_receipt_invalid")
        if role == "environment":
            validate_environment_receipt(parsed)
        receipts[role] = {
            "path": str(source.resolve()),
            "bytes": len(raw),
            "sha256": sha256_bytes(raw),
        }
    roots = {
        "source_root": str(safe_directory(Path(source_root)).resolve()),
        "data_root": str(safe_directory(Path(data_root)).resolve()),
        "model_root": str(safe_directory(Path(model_root)).resolve()),
    }
    core = {
        "schema": BOOTSTRAP_READY_SCHEMA,
        "status": "ready",
        **roots,
        "receipts": receipts,
    }
    value = {
        **core,
        "content_sha256": sha256_bytes(canonical_json_bytes(core)),
    }
    _publish_identical(Path(destination), pretty_json_bytes(value))
    return value


def _installed_distribution_freeze() -> list[str]:
    rows: set[str] = set()
    try:
        for distribution in importlib.metadata.distributions():
            name = distribution.metadata.get("Name")
            version = distribution.version
            if isinstance(name, str) and name and isinstance(version, str) and version:
                canonical = re.sub(r"[-_.]+", "-", name).lower()
                rows.add(f"{canonical}=={version}")
    except Exception as exc:
        raise FullModelTrainingError(
            "plan082_environment_distributions_failed"
        ) from exc
    return sorted(rows)


def _observe_nvidia_smi() -> tuple[str, str]:
    try:
        driver = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=driver_version",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout
        summary = subprocess.run(
            ["nvidia-smi"],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise FullModelTrainingError("plan082_environment_nvidia_smi_failed") from exc
    versions = {line.strip() for line in driver.splitlines() if line.strip()}
    match = _CUDA_VERSION.search(summary)
    if len(versions) != 1 or match is None:
        raise FullModelTrainingError("plan082_environment_nvidia_smi_invalid")
    return versions.pop(), match.group(1)


def _publish_identical(destination: Path, raw: bytes) -> None:
    target = Path(destination)
    try:
        info = os.lstat(target)
    except FileNotFoundError:
        write_exclusive(target, raw)
        return
    except OSError as exc:
        raise FullModelTrainingError("plan082_receipt_inspection_failed") from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
    ):
        raise FullModelTrainingError("plan082_receipt_existing_invalid")
    if target.read_bytes() != raw:
        raise FullModelTrainingError("plan082_receipt_existing_mismatch")
