"""Observed container and dependency identity for Plan 079 cloud runs."""

from __future__ import annotations

from importlib import metadata
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
from typing import Any, Mapping

from ..identity import canonical_json_bytes, sha256_bytes, sha256_file
from .contract import BaseQualityError, require_sha256, require_text


RUNTIME_RECEIPT_SCHEMA = "rondo-publication-critic-plan079-runtime-receipt-v1"
PACKAGE_VERSIONS = {
    "huggingface-hub": "0.36.2",
    "psutil": "7.0.0",
    "safetensors": "0.5.3",
    "tokenizers": "0.21.4",
    "torch": "2.8.0+cu128",
    "transformers": "4.52.3",
}
_CUDA_VERSION = re.compile(r"CUDA Version:\s*([0-9]+\.[0-9]+)")


def _regular_sha256(path: Path, code: str) -> str:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise BaseQualityError(code) from exc
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise BaseQualityError(code)
    return sha256_file(path)


def validate_runtime_receipt(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {
        "schema",
        "image_id",
        "dependency_freeze_sha256",
        "environment_lock_sha256",
        "python_version",
        "packages",
        "torch_cuda_runtime_version",
        "cuda_host_version",
        "gpu_name",
        "gpu_capability",
        "driver_version",
    }:
        raise BaseQualityError("runtime_receipt_fields_invalid")
    if value.get("schema") != RUNTIME_RECEIPT_SCHEMA:
        raise BaseQualityError("runtime_receipt_schema_invalid")
    for name in ("dependency_freeze_sha256", "environment_lock_sha256"):
        require_sha256(value.get(name), f"runtime_receipt_{name}_invalid")
    for name in (
        "image_id",
        "python_version",
        "torch_cuda_runtime_version",
        "cuda_host_version",
        "gpu_name",
        "gpu_capability",
        "driver_version",
    ):
        require_text(value.get(name), f"runtime_receipt_{name}_invalid")
    if value.get("packages") != PACKAGE_VERSIONS:
        raise BaseQualityError("runtime_receipt_packages_invalid")
    return dict(value)


def observe_runtime_receipt(
    *,
    image_id: str,
    dependency_freeze: Path,
    environment_lock: Path,
) -> dict[str, Any]:
    """Observe the current cloud process without accepting claimed versions."""

    image_id = require_text(image_id, "runtime_image_id_invalid")
    freeze_sha = _regular_sha256(dependency_freeze, "runtime_dependency_freeze_invalid")
    lock_sha = _regular_sha256(environment_lock, "runtime_environment_lock_invalid")
    packages: dict[str, str] = {}
    try:
        for name in PACKAGE_VERSIONS:
            packages[name] = metadata.version(name)
        import torch
    except (ImportError, metadata.PackageNotFoundError) as exc:
        raise BaseQualityError("runtime_dependency_unavailable") from exc
    if packages != PACKAGE_VERSIONS or not torch.cuda.is_available():
        raise BaseQualityError("runtime_dependency_or_cuda_identity_mismatch")
    try:
        gpu = (
            subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,driver_version",
                    "--format=csv,noheader,nounits",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            .stdout.strip()
            .splitlines()
        )
        summary = subprocess.run(
            ["nvidia-smi"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
    except (OSError, subprocess.SubprocessError) as exc:
        raise BaseQualityError("runtime_nvidia_identity_unavailable") from exc
    if len(gpu) != 1 or "," not in gpu[0]:
        raise BaseQualityError("runtime_gpu_identity_invalid")
    gpu_name, driver_version = (item.strip() for item in gpu[0].rsplit(",", 1))
    host = _CUDA_VERSION.search(summary)
    if host is None:
        raise BaseQualityError("runtime_cuda_host_identity_invalid")
    capability = torch.cuda.get_device_capability(0)
    receipt = {
        "schema": RUNTIME_RECEIPT_SCHEMA,
        "image_id": image_id,
        "dependency_freeze_sha256": freeze_sha,
        "environment_lock_sha256": lock_sha,
        "python_version": platform.python_version(),
        "packages": packages,
        "torch_cuda_runtime_version": str(torch.version.cuda),
        "cuda_host_version": host.group(1),
        "gpu_name": gpu_name,
        "gpu_capability": f"{capability[0]}.{capability[1]}",
        "driver_version": driver_version,
    }
    return validate_runtime_receipt(receipt)


def verify_runtime_environment(
    receipt_value: Any,
    *,
    image_id: str,
    dependency_freeze: Path,
    environment_lock: Path,
) -> dict[str, Any]:
    expected = validate_runtime_receipt(receipt_value)
    observed = observe_runtime_receipt(
        image_id=image_id,
        dependency_freeze=dependency_freeze,
        environment_lock=environment_lock,
    )
    if canonical_json_bytes(expected) != canonical_json_bytes(observed):
        raise BaseQualityError("runtime_environment_drifted")
    return expected


def runtime_receipt_sha256(value: Any) -> str:
    return sha256_bytes(canonical_json_bytes(validate_runtime_receipt(value)))
