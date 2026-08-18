"""Offline readiness probe for Multi M-5 paid runs. Never prints secret values."""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path
from typing import Any

from ..config import RepoPaths
from .load import (
    M5ContractError,
    load_nondegradation_contract,
    load_runtime_identity,
    load_workflow_contract,
)

_REQUIRED_ENV_NAMES = ("OPENAI_API_KEY",)


def readiness_report(*, common_root: Path | None = None) -> dict[str, Any]:
    paths = RepoPaths.discover(Path.cwd()) if common_root is None else None
    root = common_root or paths.common_root
    missing: list[str] = []
    checks: dict[str, Any] = {}

    try:
        workflow = load_workflow_contract()
        checks["workflow_lock"] = {"ok": True, "lock_id": workflow.lock_id}
    except M5ContractError as exc:
        checks["workflow_lock"] = {"ok": False, "error": str(exc)}
        missing.append("workflow_lock")
        workflow = None

    try:
        nondeg = load_nondegradation_contract()
        checks["nondegradation_lock"] = {
            "ok": True,
            "lock_id": nondeg.lock_id,
            "docker_images_pinned": len(nondeg.docker_images) == 10,
            "hard_cap_usd": nondeg.hard_cap_usd,
        }
        if len(nondeg.docker_images) != 10:
            missing.append("docker_images_pinned")
    except M5ContractError as exc:
        checks["nondegradation_lock"] = {"ok": False, "error": str(exc)}
        missing.append("nondegradation_lock")
        nondeg = None

    try:
        runtime = load_runtime_identity(require_frozen=True, common_root=root)
        checks["multi_bundle"] = {
            "ok": True,
            "relpath": runtime.bundle_relpath,
            "status": runtime.status,
        }
    except M5ContractError as exc:
        checks["multi_bundle"] = {"ok": False, "error": str(exc)}
        missing.append("multi_bundle")
        runtime = None

    if runtime is not None:
        baseline_ok, baseline_error = _verify_codex_baseline(root, runtime.baseline)
        checks["codex_bundle"] = (
            {"ok": True, "relpath": runtime.baseline["bundle_relpath"]}
            if baseline_ok
            else {"ok": False, "error": baseline_error}
        )
        if not baseline_ok:
            missing.append("codex_bundle")

    env_check = _probe_env_local(root / ".env.local")
    checks["env_local"] = env_check
    for key, ok in env_check.items():
        if key == "ok":
            continue
        if ok is False:
            missing.append(f"env_local.{key}")

    if nondeg is not None:
        checks["docker_images_present"] = "not_checked"
        checks["docker_note"] = (
            "Ten digests are pinned in the lock. Presence on the host is not "
            "checked: Docker is not authorized in this round."
        )

    return {
        "ready": not missing,
        "missing": missing,
        "checks": checks,
    }


def _verify_codex_baseline(common_root: Path, baseline: dict[str, Any]) -> tuple[bool, str]:
    relpath = baseline.get("bundle_relpath")
    if not isinstance(relpath, str):
        return False, "Codex baseline path is missing"
    bundle = (common_root / relpath).resolve()
    expected = (common_root / "eval-data" / "bin" / "codex").resolve()
    if not bundle.is_relative_to(expected):
        return False, "Codex baseline is outside eval-data/bin/codex"
    files = {
        bundle / "codex": baseline.get("codex_sha256"),
        bundle / "codex-code-mode-host": baseline.get("code_mode_host_sha256"),
        bundle / "codex-resources" / "bwrap": baseline.get("bwrap_sha256"),
        bundle / "manifest.json": baseline.get("manifest_sha256"),
    }
    for path, digest in files.items():
        if not isinstance(digest, str):
            return False, f"{path.name} digest is missing"
        if path.is_symlink() or not path.is_file():
            return False, f"{path.name} is missing"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            return False, f"{path.name} digest differs"
    return True, ""


def _probe_env_local(path: Path) -> dict[str, Any]:
    """Existence, type, mode, and whether required names are non-empty. No values."""

    result = {
        "exists": path.exists(),
        "regular_file": False,
        "mode_0600": False,
        "required_names_present": False,
        "ok": False,
    }
    if not path.exists():
        return result
    try:
        metadata = path.lstat()
    except OSError:
        return result
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        return result
    result["regular_file"] = True
    result["mode_0600"] = stat.S_IMODE(metadata.st_mode) == 0o600
    present = _required_names_nonempty(path)
    result["required_names_present"] = present
    result["ok"] = result["regular_file"] and result["mode_0600"] and present
    return result


def _required_names_nonempty(path: Path) -> bool:
    try:
        text = path.read_text("utf-8")
    except (OSError, UnicodeError):
        return False
    found: dict[str, bool] = {name: False for name in _REQUIRED_ENV_NAMES}
    for line in text.splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name in found:
            found[name] = bool(value) and "$(" not in value and "${" not in value and "`" not in value
    return all(found.values())
