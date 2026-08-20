"""Load frozen Multi/Codex runtime manifests for M-5 paid Terminal-Bench slots."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..contracts import BinaryManifest, ContractError, Product, Side
from .load import M5ContractError, RuntimeIdentity

_MANIFEST_KEYS = {
    "path",
    "sha256",
    "code_mode_host_path",
    "code_mode_host_sha256",
    "bwrap_path",
    "bwrap_sha256",
    "source_commit",
    "source_dirty",
    "rust_toolchain",
    "build_command",
    "code_mode_host_build_command",
    "bwrap_asset_url",
    "bwrap_archive_sha256",
    "bwrap_source_tree_sha256",
    "workspace_lock_normalization",
}


def load_side_manifest(
    identity: RuntimeIdentity,
    side: Side,
    *,
    common_root: Path,
) -> BinaryManifest:
    """Read the on-disk freeze manifest and require it to match the runtime lock."""

    if side is Side.RONDO:
        relpath = identity.bundle_relpath
        expected_sha = identity.codex_sha256
        expected_host = identity.code_mode_host_sha256
        expected_bwrap = identity.bwrap_sha256
        expected_manifest = identity.manifest_sha256
        expected_commit = identity.source_commit
        expected_product = Product.RONDO_MULTI.value
    elif side is Side.CODEX:
        baseline = identity.baseline
        relpath = str(baseline["bundle_relpath"])
        expected_sha = str(baseline["codex_sha256"])
        expected_host = str(baseline["code_mode_host_sha256"])
        expected_bwrap = str(baseline["bwrap_sha256"])
        expected_manifest = str(baseline["manifest_sha256"])
        expected_commit = str(baseline["source_commit"])
        expected_product = None
    else:
        raise M5ContractError("unsupported M-5 side")
    bundle = (common_root / relpath).resolve()
    manifest_path = bundle / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise M5ContractError("runtime manifest is missing")
    raw = manifest_path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != expected_manifest:
        raise M5ContractError("runtime manifest digest differs from the lock")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise M5ContractError("runtime manifest is not JSON") from exc
    if not isinstance(value, dict) or not _MANIFEST_KEYS.issubset(value):
        raise M5ContractError("runtime manifest schema differs")
    command = value.get("build_command")
    host_command = value.get("code_mode_host_build_command")
    if not isinstance(command, list) or not isinstance(host_command, list):
        raise M5ContractError("runtime manifest build command is invalid")
    try:
        manifest = BinaryManifest(
            path=str(value["path"]),
            sha256=str(value["sha256"]),
            code_mode_host_path=str(value["code_mode_host_path"]),
            code_mode_host_sha256=str(value["code_mode_host_sha256"]),
            bwrap_path=str(value["bwrap_path"]),
            bwrap_sha256=str(value["bwrap_sha256"]),
            source_commit=str(value["source_commit"]),
            source_dirty=bool(value["source_dirty"]),
            rust_toolchain=str(value["rust_toolchain"]),
            build_command=tuple(command),
            code_mode_host_build_command=tuple(host_command),
            bwrap_asset_url=str(value["bwrap_asset_url"]),
            bwrap_archive_sha256=str(value["bwrap_archive_sha256"]),
            bwrap_source_tree_sha256=str(value["bwrap_source_tree_sha256"]),
            workspace_lock_normalization=value.get("workspace_lock_normalization"),
            product=value.get("product"),
        )
        manifest.validate()
    except (ContractError, TypeError, ValueError) as exc:
        raise M5ContractError("runtime manifest contract is invalid") from exc
    if (
        manifest.sha256 != expected_sha
        or manifest.code_mode_host_sha256 != expected_host
        or manifest.bwrap_sha256 != expected_bwrap
        or manifest.source_commit != expected_commit
        or manifest.source_dirty
        or Path(manifest.path) != bundle / "codex"
        or Path(manifest.code_mode_host_path) != bundle / "codex-code-mode-host"
        or Path(manifest.bwrap_path) != bundle / "codex-resources" / "bwrap"
    ):
        raise M5ContractError("runtime manifest identity differs from the lock")
    if side is Side.RONDO and manifest.product != expected_product:
        raise M5ContractError("Multi runtime manifest product differs")
    if side is Side.CODEX and manifest.product not in {None, "codex"}:
        raise M5ContractError("Codex runtime manifest product differs")
    return manifest
