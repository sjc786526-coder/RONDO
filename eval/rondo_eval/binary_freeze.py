"""Fail-closed freezing of the two P1 Codex CLI bundles.

The heavy Cargo build is deliberately external to this module.  Every command
in this module still requires a live lease minted by ``with-build-lock.sh`` so
source inspection, publication, verification, and cleanup cannot overlap a
Docker or Cargo operation from another RONDO worktree.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import filecmp
import hashlib
import importlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import NoReturn, Protocol
from urllib.parse import urlsplit

from .contracts import BinaryManifest, ContractError, Side
from .runtime_bridge import WatchdogProof, lease_from_watchdog


BASELINE_COMMIT = "be6e8eac029b183056b7e4402879f15d2c85f61b"
BASELINE_TAG = "rust-v0.147.0"
BASELINE_LOCK_SHA256 = "eeab4e9d3466da54037032251e2f13ad1ed11eae18bb8ee7dd2c89dbb86f645d"
NORMALIZED_LOCK_SHA256 = "bc4fe450de929afe82928734f860ca83e5f9dc5f9f1211b0974ea47b57af77ca"
LOCK_NORMALIZATION = "135 workspace packages: 0.0.0 -> 0.147.0"
RUST_TOOLCHAIN = "1.95.0"
RUST_HOST = "x86_64-unknown-linux-gnu"
RUST_TARGET = "x86_64-unknown-linux-musl"
EVAL_ROOT = Path(__file__).resolve().parents[1]
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_ENV_NAME = re.compile(r"[A-Z_][A-Z0-9_]*\Z")
_SUMMARY_NAME = re.compile(r"[a-z_][a-z0-9_]*\Z")
_ORIGINAL_VERSION_LINE = b'version = "0.0.0"\n'
_NORMALIZED_VERSION_LINE = b'version = "0.147.0"\n'
_MANIFEST_KEYS = {
    "path",
    "sha256",
    "code_mode_host_path",
    "code_mode_host_sha256",
    "source_commit",
    "source_dirty",
    "rust_toolchain",
    "build_command",
    "code_mode_host_build_command",
    "workspace_lock_normalization",
}
_LEGACY_MANIFEST_KEYS = _MANIFEST_KEYS - {
    "code_mode_host_path",
    "code_mode_host_sha256",
    "code_mode_host_build_command",
}


class BinaryFreezeError(RuntimeError):
    """A redacted, fail-closed binary provenance or filesystem error."""


class LeaseFactory(Protocol):
    def __call__(self) -> WatchdogProof: ...


class ExecFunction(Protocol):
    def __call__(self, executable: str, argv: list[str]) -> NoReturn: ...


class V8ExecFunction(Protocol):
    def __call__(
        self, executable: str, argv: list[str], environment: Mapping[str, str]
    ) -> NoReturn: ...


@dataclass(frozen=True)
class FreezeRequest:
    side: Side
    common_root: Path
    source_root: Path
    source_commit: str
    target_dir: Path
    artifact_dir: Path
    gate_root: Path
    baseline_reference_root: Path | None = None


@dataclass(frozen=True)
class CompanionFreezeRequest:
    side: Side
    common_root: Path
    source_root: Path
    source_commit: str
    target_dir: Path
    legacy_artifact_dir: Path
    bundle_dir: Path
    gate_root: Path
    baseline_reference_root: Path | None = None


@dataclass(frozen=True)
class FreezeResult:
    side: str
    manifest_path: str
    binary_path: str
    binary_sha256: str
    source_commit: str
    code_mode_host_path: str | None = None
    code_mode_host_sha256: str | None = None


@dataclass(frozen=True)
class _LegacyBinaryManifest:
    path: str
    sha256: str
    source_commit: str
    source_dirty: bool
    rust_toolchain: str
    build_command: tuple[str, ...]
    workspace_lock_normalization: str | None = None


@dataclass(frozen=True)
class BaselineExportResult:
    scratch_path: str
    source_commit: str
    original_lock_sha256: str
    normalized_lock_sha256: str
    workspace_lock_normalization: str


def export_baseline(
    *,
    common_root: Path,
    baseline_reference_root: Path,
    source_commit: str,
    scratch_dir: Path,
    lease_factory: LeaseFactory = lease_from_watchdog,
) -> BaselineExportResult:
    """Atomically export and mechanically normalize the frozen Codex source."""

    proof = _proof(lease_factory)
    root = _regular_directory(common_root)
    reference = _regular_directory(baseline_reference_root)
    if source_commit != BASELINE_COMMIT:
        raise BinaryFreezeError("baseline export requires the frozen source commit")
    _validate_baseline_reference(reference)
    expected = root / "eval-data" / "sources" / f"codex-rust-v0.147.0-{source_commit}"
    destination = _exact_absent_path(scratch_dir, expected, "baseline scratch")
    parent = destination.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _reject_symlink_chain(parent)
    staging = Path(tempfile.mkdtemp(prefix=f".{destination.name}.staging-", dir=parent))
    try:
        tracked = _tracked_modes(reference)
        original_lock = _regular_file(reference / "codex-rs" / "Cargo.lock").read_bytes()
        normalized_lock = _expected_normalized_lock(original_lock)
        for index, (relative, mode) in enumerate(tracked.items()):
            if index % 128 == 0:
                _held(proof)
            source = reference / relative
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if relative == "codex-rs/Cargo.lock":
                _write_exclusive(target, normalized_lock, mode=0o644)
            elif mode == 0o120000:
                os.symlink(os.readlink(source), target)
            else:
                _copy_regular(source, target, mode=0o755 if mode == 0o100755 else 0o644)
        _validate_baseline_scratch(staging, reference)
        _fsync_tree_directories(staging)
        if destination.exists() or destination.is_symlink():
            raise BinaryFreezeError("baseline scratch appeared before atomic publication")
        _rename_noreplace(staging, destination)
        _fsync_directory(parent)
    except Exception:
        if staging.exists() and staging.is_dir() and not staging.is_symlink():
            _remove_private_tree(staging)
        raise
    _held(proof)
    _validate_baseline_scratch(destination, reference)
    return BaselineExportResult(
        scratch_path=str(destination),
        source_commit=source_commit,
        original_lock_sha256=BASELINE_LOCK_SHA256,
        normalized_lock_sha256=NORMALIZED_LOCK_SHA256,
        workspace_lock_normalization=LOCK_NORMALIZATION,
    )


def exec_v8_build(
    *,
    side: Side,
    source_root: Path,
    source_commit: str,
    baseline_reference_root: Path | None = None,
    lease_factory: LeaseFactory = lease_from_watchdog,
    exec_function: V8ExecFunction = os.execvpe,
    environ: Mapping[str, str] | None = None,
) -> NoReturn:
    """Resolve the official musl V8 pair and exec the fixed two-bin Cargo build."""

    proof = _proof(lease_factory)
    source = _regular_directory(source_root)
    _validate_commit(source_commit)
    if side is Side.RONDO:
        if baseline_reference_root is not None:
            raise BinaryFreezeError("RONDO V8 build cannot declare a baseline reference")
        _validate_rondo_source(source, source_commit)
        scripts = source / "mydev" / "scripts"
        workspace = source / "mydev" / "codex-rs"
    elif side is Side.CODEX:
        if source_commit != BASELINE_COMMIT or baseline_reference_root is None:
            raise BinaryFreezeError("Codex V8 build requires the frozen baseline identity")
        reference = _regular_directory(baseline_reference_root)
        _validate_baseline_reference(reference)
        _validate_baseline_scratch(source, reference)
        scripts = source / "scripts"
        workspace = source / "codex-rs"
    else:
        raise BinaryFreezeError("binary side is invalid")
    _validate_workspace_manifests(workspace)

    child_environment = dict(os.environ if environ is None else environ)
    forbidden = {"V8_FROM_SOURCE", "RUSTY_V8_ARCHIVE", "RUSTY_V8_SRC_BINDING_PATH"}
    if forbidden & child_environment.keys():
        raise BinaryFreezeError("ambient V8 source or artifact overrides are forbidden")
    target_specs, fetch_artifacts, resolved_version = _load_source_v8_resolver(scripts)
    spec = target_specs.get(RUST_TARGET)
    if spec is None or getattr(spec, "target", None) != RUST_TARGET:
        raise BinaryFreezeError("frozen source lacks the exact musl V8 target resolver")
    try:
        version = resolved_version()
        artifacts = fetch_artifacts(spec, version=version)
        archive = _regular_file(Path(artifacts.archive))
        binding = _regular_file(Path(artifacts.binding))
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError) as exc:
        raise BinaryFreezeError("official musl V8 artifact resolution failed") from exc
    archive_sha = _sha256_file(archive)
    binding_sha = _sha256_file(binding)
    print(f"[rondo-eval-v8] target={RUST_TARGET}", file=sys.stderr)
    print(f"[rondo-eval-v8] archive_sha256={archive_sha}", file=sys.stderr)
    print(f"[rondo-eval-v8] binding_sha256={binding_sha}", file=sys.stderr, flush=True)

    command = [
        "cargo",
        "build",
        "--locked",
        "--release",
        "--target",
        RUST_TARGET,
        "--manifest-path",
        str(workspace / "Cargo.toml"),
        "-p",
        "codex-cli",
        "--bin",
        "codex",
        "-p",
        "codex-code-mode-host",
        "--bin",
        "codex-code-mode-host",
    ]
    child_environment["RUSTY_V8_ARCHIVE"] = str(archive)
    child_environment["RUSTY_V8_SRC_BINDING_PATH"] = str(binding)
    _held(proof)
    exec_function("cargo", command, child_environment)
    raise BinaryFreezeError("V8 Cargo exec unexpectedly returned")


def prepare(
    request: FreezeRequest,
    build_command: Sequence[str],
    *,
    lease_factory: LeaseFactory = lease_from_watchdog,
    toolchain_probe: Callable[[], str] | None = None,
) -> FreezeResult:
    """Validate one completed release build and atomically freeze its binary."""

    proof = _proof(lease_factory)
    paths = _validate_request(request, artifact_must_exist=False)
    toolchain = (toolchain_probe or _probe_toolchain)()
    _validate_toolchain(toolchain)
    command = _validate_build_command(request, paths, build_command)
    _validate_source(request, paths)
    source_binary = _regular_file(
        paths.target_dir / RUST_TARGET / "release" / "codex",
        executable=True,
    )
    _validate_static_musl_binary(source_binary)
    _held(proof)

    digest = _sha256_file(source_binary)
    normalization = LOCK_NORMALIZATION if request.side is Side.CODEX else None
    manifest = _LegacyBinaryManifest(
        path=str(paths.artifact_dir / "codex"),
        sha256=digest,
        source_commit=request.source_commit,
        source_dirty=False,
        rust_toolchain=toolchain,
        build_command=command,
        workspace_lock_normalization=normalization,
    )
    _validate_legacy_manifest_contract(manifest)
    _publish_legacy(paths.artifact_dir, source_binary, manifest)
    _held(proof)
    return _result(request.side, paths.artifact_dir, manifest)


def verify(
    request: FreezeRequest,
    *,
    lease_factory: LeaseFactory = lease_from_watchdog,
    toolchain_probe: Callable[[], str] | None = None,
) -> FreezeResult:
    """Revalidate source provenance, build command, manifest, and frozen bytes."""

    proof = _proof(lease_factory)
    paths = _validate_request(request, artifact_must_exist=True)
    toolchain = (toolchain_probe or _probe_toolchain)()
    _validate_toolchain(toolchain)
    manifest = _read_legacy_manifest(paths.artifact_dir / "manifest.json")
    _validate_build_command(request, paths, manifest.build_command)
    _validate_source(request, paths)
    if manifest.source_commit != request.source_commit or manifest.source_dirty:
        raise BinaryFreezeError("manifest source identity differs from the clean source")
    expected_normalization = LOCK_NORMALIZATION if request.side is Side.CODEX else None
    if manifest.workspace_lock_normalization != expected_normalization:
        raise BinaryFreezeError("manifest lock normalization differs from the side contract")
    if manifest.rust_toolchain != toolchain:
        raise BinaryFreezeError("manifest Rust toolchain differs from the live frozen toolchain")
    binary = _regular_file(paths.artifact_dir / "codex", executable=True, exact_mode=0o555)
    _validate_static_musl_binary(binary)
    if Path(manifest.path) != binary or manifest.sha256 != _sha256_file(binary):
        raise BinaryFreezeError("frozen binary differs from its manifest")
    release = _regular_file(
        paths.target_dir / RUST_TARGET / "release" / "codex",
        executable=True,
    )
    _validate_static_musl_binary(release)
    if _sha256_file(release) != manifest.sha256:
        raise BinaryFreezeError("release binary differs from the frozen binary")
    if {entry.name for entry in os.scandir(paths.artifact_dir)} != {"codex", "manifest.json"}:
        raise BinaryFreezeError("artifact directory contains unowned entries")
    _held(proof)
    return _result(request.side, paths.artifact_dir, manifest)


def prepare_companion(
    request: CompanionFreezeRequest,
    code_mode_host_build_command: Sequence[str],
    *,
    lease_factory: LeaseFactory = lease_from_watchdog,
    toolchain_probe: Callable[[], str] | None = None,
) -> FreezeResult:
    """Migrate a verified legacy CLI artifact into an atomic two-binary bundle."""

    proof = _proof(lease_factory)
    paths = _validate_companion_request(request, bundle_must_exist=False)
    toolchain = (toolchain_probe or _probe_toolchain)()
    _validate_toolchain(toolchain)
    command = _validate_build_command(
        _freeze_request_from_companion(request),
        paths.freeze,
        code_mode_host_build_command,
        companion=True,
    )
    _validate_source(_freeze_request_from_companion(request), paths.freeze)
    legacy = _validate_legacy_artifact(request, paths, toolchain)
    rebuilt_cli = _regular_file(
        paths.freeze.target_dir / RUST_TARGET / "release" / "codex",
        executable=True,
    )
    source_host = _regular_file(
        paths.freeze.target_dir / RUST_TARGET / "release" / "codex-code-mode-host",
        executable=True,
    )
    _validate_static_musl_binary(rebuilt_cli)
    _validate_static_musl_binary(source_host)
    _held(proof)

    host_digest = _sha256_file(source_host)
    manifest = BinaryManifest(
        path=str(paths.bundle_dir / "codex"),
        sha256=legacy.sha256,
        code_mode_host_path=str(paths.bundle_dir / "codex-code-mode-host"),
        code_mode_host_sha256=host_digest,
        source_commit=request.source_commit,
        source_dirty=False,
        rust_toolchain=toolchain,
        build_command=legacy.build_command,
        code_mode_host_build_command=command,
        workspace_lock_normalization=legacy.workspace_lock_normalization,
    )
    try:
        manifest.validate()
    except ContractError as exc:
        raise BinaryFreezeError("binary bundle manifest contract is invalid") from exc
    _publish_bundle(
        paths.bundle_dir,
        _regular_file(paths.legacy_artifact_dir / "codex", executable=True, exact_mode=0o555),
        source_host,
        manifest,
        proof,
    )
    _held(proof)
    return _result(request.side, paths.bundle_dir, manifest)


def verify_companion(
    request: CompanionFreezeRequest,
    *,
    lease_factory: LeaseFactory = lease_from_watchdog,
    toolchain_probe: Callable[[], str] | None = None,
) -> FreezeResult:
    """Revalidate source, legacy input, host release, and the frozen bundle."""

    proof = _proof(lease_factory)
    paths = _validate_companion_request(request, bundle_must_exist=True)
    toolchain = (toolchain_probe or _probe_toolchain)()
    _validate_toolchain(toolchain)
    freeze_request = _freeze_request_from_companion(request)
    _validate_source(freeze_request, paths.freeze)
    legacy = _validate_legacy_artifact(request, paths, toolchain)
    manifest = _read_manifest(paths.bundle_dir / "manifest.json")
    _validate_build_command(freeze_request, paths.freeze, manifest.build_command)
    _validate_build_command(
        freeze_request,
        paths.freeze,
        manifest.code_mode_host_build_command,
        companion=True,
    )
    expected_normalization = LOCK_NORMALIZATION if request.side is Side.CODEX else None
    if (
        manifest.source_commit != request.source_commit
        or manifest.source_dirty
        or manifest.rust_toolchain != toolchain
        or manifest.workspace_lock_normalization != expected_normalization
        or manifest.sha256 != legacy.sha256
        or manifest.build_command != legacy.build_command
    ):
        raise BinaryFreezeError("binary bundle provenance differs from its verified inputs")
    binary = _regular_file(paths.bundle_dir / "codex", executable=True, exact_mode=0o555)
    host = _regular_file(
        paths.bundle_dir / "codex-code-mode-host", executable=True, exact_mode=0o555
    )
    release_host = _regular_file(
        paths.freeze.target_dir / RUST_TARGET / "release" / "codex-code-mode-host",
        executable=True,
    )
    rebuilt_cli = _regular_file(
        paths.freeze.target_dir / RUST_TARGET / "release" / "codex",
        executable=True,
    )
    for candidate in (binary, host, rebuilt_cli, release_host):
        _validate_static_musl_binary(candidate)
    if (
        Path(manifest.path) != binary
        or Path(manifest.code_mode_host_path) != host
        or _sha256_file(binary) != manifest.sha256
        or _sha256_file(host) != manifest.code_mode_host_sha256
        or _sha256_file(release_host) != manifest.code_mode_host_sha256
    ):
        raise BinaryFreezeError("binary bundle bytes differ from its manifest or host release")
    if {entry.name for entry in os.scandir(paths.bundle_dir)} != {
        "codex",
        "codex-code-mode-host",
        "manifest.json",
    }:
        raise BinaryFreezeError("binary bundle contains unowned entries")
    _held(proof)
    return _result(request.side, paths.bundle_dir, manifest)


def cleanup(
    *,
    side: Side,
    common_root: Path,
    source_commit: str,
    target_dir: Path,
    scratch_dir: Path | None = None,
    lease_factory: LeaseFactory = lease_from_watchdog,
    exec_function: ExecFunction = os.execv,
    rm_executable: Path = Path("/usr/bin/rm"),
) -> NoReturn:
    """Exec ``rm`` for only the exact side/commit target and optional baseline scratch."""

    proof = _proof(lease_factory)
    root = _regular_directory(common_root)
    _validate_commit(source_commit)
    if side is Side.CODEX and source_commit != BASELINE_COMMIT:
        raise BinaryFreezeError("Codex cleanup requires the frozen baseline commit")
    expected_target = _expected_target(root, side, source_commit)
    target = _exact_existing_directory(target_dir, expected_target, "Cargo target")
    paths = [target]
    if side is Side.RONDO:
        if scratch_dir is not None:
            raise BinaryFreezeError("RONDO cleanup cannot include a baseline scratch")
    else:
        if scratch_dir is None:
            raise BinaryFreezeError("Codex cleanup requires its exact baseline scratch")
        expected_scratch = root / "eval-data" / "sources" / f"codex-rust-v0.147.0-{source_commit}"
        paths.append(_exact_existing_directory(scratch_dir, expected_scratch, "baseline scratch"))
    executable = _regular_file(rm_executable, executable=True)
    _held(proof)
    exec_function(str(executable), [str(executable), "-rf", "--", *(str(path) for path in paths)])
    raise BinaryFreezeError("cleanup exec unexpectedly returned")


@dataclass(frozen=True)
class _ResolvedPaths:
    common_root: Path
    source_root: Path
    target_dir: Path
    artifact_dir: Path
    gate_root: Path
    baseline_reference_root: Path | None


@dataclass(frozen=True)
class _ResolvedCompanionPaths:
    freeze: _ResolvedPaths
    legacy_artifact_dir: Path
    bundle_dir: Path


def _freeze_request_from_companion(request: CompanionFreezeRequest) -> FreezeRequest:
    return FreezeRequest(
        side=request.side,
        common_root=request.common_root,
        source_root=request.source_root,
        source_commit=request.source_commit,
        target_dir=request.target_dir,
        artifact_dir=request.bundle_dir,
        gate_root=request.gate_root,
        baseline_reference_root=request.baseline_reference_root,
    )


def _validate_companion_request(
    request: CompanionFreezeRequest, *, bundle_must_exist: bool
) -> _ResolvedCompanionPaths:
    if not isinstance(request.side, Side):
        raise BinaryFreezeError("binary side is invalid")
    _validate_commit(request.source_commit)
    root = _regular_directory(request.common_root)
    source = _regular_directory(request.source_root)
    gate = _regular_directory(request.gate_root)
    target = _exact_existing_directory(
        request.target_dir,
        _expected_target(root, request.side, request.source_commit),
        "Cargo target",
    )
    legacy = _exact_existing_directory(
        request.legacy_artifact_dir,
        _expected_artifact(root, request.side, request.source_commit),
        "legacy artifact",
    )
    expected_bundle = _expected_bundle(root, request.side, request.source_commit)
    bundle = (
        _exact_existing_directory(request.bundle_dir, expected_bundle, "binary bundle")
        if bundle_must_exist
        else _exact_absent_path(request.bundle_dir, expected_bundle, "binary bundle")
    )
    reference = None
    if request.side is Side.CODEX:
        if request.source_commit != BASELINE_COMMIT or request.baseline_reference_root is None:
            raise BinaryFreezeError("Codex bundle requires the frozen baseline identity")
        reference = _regular_directory(request.baseline_reference_root)
    elif request.baseline_reference_root is not None:
        raise BinaryFreezeError("RONDO bundle cannot declare a baseline reference")
    freeze = _ResolvedPaths(root, source, target, bundle, gate, reference)
    return _ResolvedCompanionPaths(freeze, legacy, bundle)


def _validate_request(request: FreezeRequest, *, artifact_must_exist: bool) -> _ResolvedPaths:
    if not isinstance(request.side, Side):
        raise BinaryFreezeError("binary side is invalid")
    _validate_commit(request.source_commit)
    root = _regular_directory(request.common_root)
    source = _regular_directory(request.source_root)
    gate = _regular_directory(request.gate_root)
    target = _exact_existing_directory(
        request.target_dir,
        _expected_target(root, request.side, request.source_commit),
        "Cargo target",
    )
    expected_artifact = _expected_artifact(root, request.side, request.source_commit)
    if artifact_must_exist:
        artifact = _exact_existing_directory(request.artifact_dir, expected_artifact, "artifact")
    else:
        artifact = _exact_absent_path(request.artifact_dir, expected_artifact, "artifact")
    reference = None
    if request.side is Side.CODEX:
        if request.source_commit != BASELINE_COMMIT or request.baseline_reference_root is None:
            raise BinaryFreezeError("Codex side requires the frozen baseline identity")
        reference = _regular_directory(request.baseline_reference_root)
    elif request.baseline_reference_root is not None:
        raise BinaryFreezeError("RONDO side cannot declare a baseline reference")
    return _ResolvedPaths(root, source, target, artifact, gate, reference)


def _validate_source(request: FreezeRequest, paths: _ResolvedPaths) -> None:
    if request.side is Side.RONDO:
        _validate_rondo_source(paths.source_root, request.source_commit)
        workspace = paths.source_root / "mydev" / "codex-rs"
    else:
        assert paths.baseline_reference_root is not None
        _validate_baseline_reference(paths.baseline_reference_root)
        _validate_baseline_scratch(paths.source_root, paths.baseline_reference_root)
        workspace = paths.source_root / "codex-rs"
    _validate_workspace_manifests(workspace)


def _validate_legacy_artifact(
    request: CompanionFreezeRequest,
    paths: _ResolvedCompanionPaths,
    toolchain: str,
) -> _LegacyBinaryManifest:
    manifest = _read_legacy_manifest(paths.legacy_artifact_dir / "manifest.json")
    freeze_request = _freeze_request_from_companion(request)
    _validate_build_command(freeze_request, paths.freeze, manifest.build_command)
    expected_normalization = LOCK_NORMALIZATION if request.side is Side.CODEX else None
    binary = _regular_file(
        paths.legacy_artifact_dir / "codex", executable=True, exact_mode=0o555
    )
    _validate_static_musl_binary(binary)
    if (
        manifest.source_commit != request.source_commit
        or manifest.source_dirty
        or manifest.rust_toolchain != toolchain
        or manifest.workspace_lock_normalization != expected_normalization
        or Path(manifest.path) != binary
        or manifest.sha256 != _sha256_file(binary)
    ):
        raise BinaryFreezeError("legacy CLI artifact provenance differs")
    if {entry.name for entry in os.scandir(paths.legacy_artifact_dir)} != {
        "codex",
        "manifest.json",
    }:
        raise BinaryFreezeError("legacy CLI artifact contains unowned entries")
    return manifest


def _validate_rondo_source(source: Path, commit: str) -> None:
    if _git(source, "rev-parse", "--show-toplevel") != str(source):
        raise BinaryFreezeError("RONDO source is not a worktree root")
    if _git(source, "rev-parse", "HEAD") != commit:
        raise BinaryFreezeError("RONDO source commit differs from the requested commit")
    symbolic = _git_result(source, "symbolic-ref", "-q", "HEAD")
    if symbolic.returncode == 0:
        raise BinaryFreezeError("RONDO measurement source must be detached")
    if symbolic.returncode != 1:
        raise BinaryFreezeError("RONDO detached state is unavailable")
    if _git(source, "status", "--porcelain=v1", "--untracked-files=all"):
        raise BinaryFreezeError("RONDO measurement source is dirty")
    lock = _regular_file(source / "mydev" / "codex-rs" / "Cargo.lock")
    if _sha256_file(lock) != NORMALIZED_LOCK_SHA256:
        raise BinaryFreezeError("RONDO Cargo lock differs from the frozen 0.147.0 lock")


def _validate_baseline_reference(reference: Path) -> None:
    if _git(reference, "rev-parse", "--show-toplevel") != str(reference):
        raise BinaryFreezeError("baseline reference is not its repository root")
    if _git(reference, "rev-parse", "HEAD") != BASELINE_COMMIT:
        raise BinaryFreezeError("baseline reference commit differs")
    if _git(reference, "rev-parse", f"{BASELINE_TAG}^{{commit}}") != BASELINE_COMMIT:
        raise BinaryFreezeError("baseline tag does not peel to the frozen commit")
    if _git_result(reference, "symbolic-ref", "-q", "HEAD").returncode != 1:
        raise BinaryFreezeError("baseline reference must be detached")
    if _git(reference, "status", "--porcelain=v1", "--untracked-files=all"):
        raise BinaryFreezeError("baseline reference is dirty")
    original = _regular_file(reference / "codex-rs" / "Cargo.lock").read_bytes()
    _expected_normalized_lock(original)


def _validate_baseline_scratch(scratch: Path, reference: Path) -> None:
    if (scratch / ".git").exists() or (scratch / ".git").is_symlink():
        raise BinaryFreezeError("baseline scratch must be an exported source tree")
    tracked = _tracked_modes(reference)
    actual = _tree_entries(scratch)
    if set(actual) != set(tracked):
        raise BinaryFreezeError("baseline scratch file tree differs from the frozen commit")
    lock_relative = "codex-rs/Cargo.lock"
    original = _regular_file(reference / lock_relative).read_bytes()
    normalized = _expected_normalized_lock(original)
    for relative, mode in tracked.items():
        source_path = reference / relative
        scratch_path = scratch / relative
        _validate_mode(scratch_path, mode)
        if relative == lock_relative:
            if scratch_path.read_bytes() != normalized:
                raise BinaryFreezeError("baseline scratch lock is not the exact mechanical normalization")
        elif mode == 0o120000:
            if os.readlink(scratch_path) != os.readlink(source_path):
                raise BinaryFreezeError("baseline scratch symlink differs from the frozen commit")
        elif not filecmp.cmp(source_path, scratch_path, shallow=False):
            raise BinaryFreezeError("baseline scratch changed outside Cargo.lock")


def _expected_normalized_lock(original: bytes) -> bytes:
    if hashlib.sha256(original).hexdigest() != BASELINE_LOCK_SHA256:
        raise BinaryFreezeError("official baseline Cargo lock checksum differs")
    try:
        document = tomllib.loads(original.decode("utf-8"))
    except (UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise BinaryFreezeError("official baseline Cargo lock is invalid") from exc
    workspace = [
        package
        for package in document.get("package", [])
        if package.get("version") == "0.0.0"
    ]
    if len(workspace) != 135 or any("source" in package for package in workspace):
        raise BinaryFreezeError("official baseline lock does not contain exactly 135 workspace entries")
    if original.splitlines(keepends=True).count(_ORIGINAL_VERSION_LINE) != 135:
        raise BinaryFreezeError("official baseline lock replacement sites differ")
    normalized = original.replace(_ORIGINAL_VERSION_LINE, _NORMALIZED_VERSION_LINE)
    if (
        _ORIGINAL_VERSION_LINE in normalized
        or normalized.splitlines(keepends=True).count(_NORMALIZED_VERSION_LINE) != 135
        or hashlib.sha256(normalized).hexdigest() != NORMALIZED_LOCK_SHA256
    ):
        raise BinaryFreezeError("baseline Cargo lock normalization checksum differs")
    return normalized


def _validate_workspace_manifests(workspace: Path) -> None:
    toolchain = tomllib.loads(_regular_file(workspace / "rust-toolchain.toml").read_text("utf-8"))
    if toolchain.get("toolchain", {}).get("channel") != RUST_TOOLCHAIN:
        raise BinaryFreezeError("source Rust toolchain is not frozen at 1.95.0")
    root = tomllib.loads(_regular_file(workspace / "Cargo.toml").read_text("utf-8"))
    cli = tomllib.loads(_regular_file(workspace / "cli" / "Cargo.toml").read_text("utf-8"))
    host = tomllib.loads(
        _regular_file(workspace / "code-mode-host" / "Cargo.toml").read_text("utf-8")
    )
    bins = {(item.get("name"), item.get("path")) for item in cli.get("bin", [])}
    host_bins = {(item.get("name"), item.get("path")) for item in host.get("bin", [])}
    if root.get("workspace", {}).get("package", {}).get("version") != "0.147.0":
        raise BinaryFreezeError("workspace version is not 0.147.0")
    if cli.get("package", {}).get("name") != "codex-cli" or ("codex", "src/main.rs") not in bins:
        raise BinaryFreezeError("codex-cli package/bin contract differs")
    if host.get("package", {}).get("name") != "codex-code-mode-host" or (
        "codex-code-mode-host",
        "src/main.rs",
    ) not in host_bins:
        raise BinaryFreezeError("codex-code-mode-host package/bin contract differs")


def _load_source_v8_resolver(
    scripts_root: Path,
) -> tuple[Mapping[str, object], Callable[..., object], Callable[[], str]]:
    scripts = _regular_directory(scripts_root)
    package = _regular_directory(scripts / "codex_package")
    targets_file = _regular_file(package / "targets.py")
    v8_file = _regular_file(package / "v8.py")
    if "codex_package" in sys.modules or any(
        name.startswith("codex_package.") for name in sys.modules
    ):
        raise BinaryFreezeError("ambient codex_package modules are forbidden")
    previous_dont_write_bytecode = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(scripts))
    try:
        importlib.invalidate_caches()
        targets_module = importlib.import_module("codex_package.targets")
        v8_module = importlib.import_module("codex_package.v8")
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        raise BinaryFreezeError("frozen source V8 resolver import failed") from exc
    finally:
        try:
            sys.path.remove(str(scripts))
        except ValueError:
            pass
        sys.dont_write_bytecode = previous_dont_write_bytecode
    if (
        Path(getattr(targets_module, "__file__", "")).resolve() != targets_file
        or Path(getattr(v8_module, "__file__", "")).resolve() != v8_file
    ):
        raise BinaryFreezeError("V8 resolver was not imported from the frozen source")
    target_specs = getattr(targets_module, "TARGET_SPECS", None)
    fetch_artifacts = getattr(v8_module, "fetch_codex_v8_artifacts", None)
    resolved_version = getattr(v8_module, "resolved_v8_crate_version", None)
    if (
        not isinstance(target_specs, dict)
        or not callable(fetch_artifacts)
        or not callable(resolved_version)
    ):
        raise BinaryFreezeError("frozen source V8 resolver API differs")
    return target_specs, fetch_artifacts, resolved_version


def _validate_build_command(
    request: FreezeRequest,
    paths: _ResolvedPaths,
    command: Sequence[str],
    *,
    companion: bool = False,
) -> tuple[str, ...]:
    if isinstance(command, (str, bytes)):
        raise BinaryFreezeError("build command must be an argv array")
    argv = tuple(command)
    if not argv or any(not isinstance(item, str) or not item or "\x00" in item for item in argv):
        raise BinaryFreezeError("build command argv is invalid")
    watchdog = paths.gate_root / "mydev" / "scripts" / "with-build-lock.sh"
    _regular_file(watchdog, executable=True)
    try:
        watchdog_index = argv.index(str(watchdog), 3)
    except ValueError as exc:
        raise BinaryFreezeError("build command lacks the exact watchdog entry") from exc
    if argv[:3] != (f"cwd={paths.gate_root}", "env", "-i"):
        raise BinaryFreezeError("build command must begin with an empty environment")
    environment = _validate_build_environment(
        argv[3:watchdog_index], require_eval_pythonpath=companion
    )
    if environment["RONDO_PROJECT_ROOT"] != str(paths.common_root):
        raise BinaryFreezeError("build command project root differs")
    if environment["CARGO_TARGET_DIR"] != str(paths.target_dir):
        raise BinaryFreezeError("build command Cargo target differs")
    metrics_path = Path(environment["RONDO_BUILD_METRICS_DIR"])
    expected_metrics_root = paths.common_root / "eval-data" / "build-metrics"
    if not _lexically_below(metrics_path, expected_metrics_root):
        raise BinaryFreezeError("watchdog metrics directory is outside eval-data/build-metrics")
    _validate_watchdog_summary(metrics_path)
    if companion:
        gate_arguments = (
            "python3",
            "-m",
            "rondo_eval.binary_freeze",
            "v8-build",
            "--side",
            request.side.value,
            "--source-root",
            str(paths.source_root),
            "--source-commit",
            request.source_commit,
        )
        if request.side is Side.CODEX:
            assert paths.baseline_reference_root is not None
            gate_arguments += (
                "--baseline-reference-root",
                str(paths.baseline_reference_root),
            )
        expected_suffix = (
            str(watchdog),
            "rustup",
            "run",
            RUST_TOOLCHAIN,
            *gate_arguments,
        )
    else:
        manifest = (
            paths.source_root / "mydev" / "codex-rs" / "Cargo.toml"
            if request.side is Side.RONDO
            else paths.source_root / "codex-rs" / "Cargo.toml"
        )
        v8_gate = paths.gate_root / "mydev" / "scripts" / "with_codex_v8_artifacts.py"
        # The historical seven-key artifact used this tracked GNU-host gate.
        _regular_file(v8_gate)
        expected_suffix = (
            str(watchdog),
            "rustup",
            "run",
            RUST_TOOLCHAIN,
            "python3",
            str(v8_gate),
            "--",
            "cargo",
            "build",
            "--locked",
            "--release",
            "--target",
            RUST_TARGET,
            "--manifest-path",
            str(manifest),
            "-p",
            "codex-cli",
            "--bin",
            "codex",
        )
    if argv[watchdog_index:] != expected_suffix:
        raise BinaryFreezeError("build command differs from the supervised V8-gated release contract")
    return argv


def _validate_build_environment(
    items: Sequence[str], *, require_eval_pythonpath: bool = False
) -> dict[str, str]:
    environment: dict[str, str] = {}
    for item in items:
        name, separator, value = item.partition("=")
        if (
            separator != "="
            or not _ENV_NAME.fullmatch(name)
            or name in environment
            or "\x00" in value
            or "\n" in value
        ):
            raise BinaryFreezeError("build environment assignment is invalid")
        environment[name] = value
    required = {
        "HOME",
        "PATH",
        "LC_ALL",
        "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS",
        "RONDO_PROJECT_ROOT",
        "CARGO_TARGET_DIR",
        "RONDO_BUILD_METRICS_DIR",
    }
    if require_eval_pythonpath:
        required.add("PYTHONPATH")
    allowed = required | {"HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY"}
    if set(environment) - allowed or not required.issubset(environment):
        raise BinaryFreezeError("build environment differs from the non-secret allowlist")
    if require_eval_pythonpath and environment["PYTHONPATH"] != str(EVAL_ROOT):
        raise BinaryFreezeError("build command Python path differs from the eval-owned V8 gate")
    if environment["HOME"] != os.environ.get("HOME") or environment["PATH"] != os.environ.get("PATH"):
        raise BinaryFreezeError("build command may not repurpose HOME or PATH")
    if environment["LC_ALL"] not in {"C", "C.UTF-8"}:
        raise BinaryFreezeError("build locale must be deterministic")
    runtime = environment["XDG_RUNTIME_DIR"]
    if not runtime.startswith("/run/user/") or environment["DBUS_SESSION_BUS_ADDRESS"] != f"unix:path={runtime}/bus":
        raise BinaryFreezeError("build user-bus environment is invalid")
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        value = environment.get(name)
        if value is not None:
            parsed = urlsplit(value)
            if (
                parsed.scheme not in {"http", "https", "socks5", "socks5h"}
                or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.port is None
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise BinaryFreezeError("build proxy must be a credential-free loopback endpoint")
    if "@" in environment.get("NO_PROXY", ""):
        raise BinaryFreezeError("build NO_PROXY value is invalid")
    return environment


def _validate_watchdog_summary(metrics_root: Path) -> None:
    root = _regular_directory(metrics_root)
    summaries: list[Path] = []
    for run in os.scandir(root):
        if run.is_symlink() or not run.is_dir(follow_symlinks=False):
            raise BinaryFreezeError("build watchdog metrics contain an unsupported entry")
        summary = Path(run.path) / "summary.env"
        if summary.exists() or summary.is_symlink():
            summaries.append(_regular_file(summary))
    if len(summaries) != 1:
        raise BinaryFreezeError("build watchdog proof must contain exactly one summary")
    values: dict[str, str] = {}
    try:
        lines = summaries[0].read_text("ascii").splitlines()
    except (OSError, UnicodeError) as exc:
        raise BinaryFreezeError("build watchdog summary is unreadable") from exc
    for line in lines:
        name, separator, value = line.partition("=")
        if separator != "=" or not _SUMMARY_NAME.fullmatch(name) or name in values:
            raise BinaryFreezeError("build watchdog summary is malformed")
        values[name] = value
    expected = {
        "wrapper_status": "complete",
        "run_rc": "0",
        "final_rc": "0",
        "stop_reason": "none",
        "cleanup_reason": "none",
        "command_name": "rustup",
    }
    if any(values.get(name) != value for name, value in expected.items()):
        raise BinaryFreezeError("build watchdog summary did not retain a successful build")
    for name in ("target_after_bytes", "target_peak_sampled_bytes"):
        value = values.get(name, "")
        if not value.isascii() or not value.isdigit() or int(value) <= 0:
            raise BinaryFreezeError("build watchdog target evidence is invalid")


def _probe_toolchain() -> str:
    rustc = _run_version(("rustup", "run", RUST_TOOLCHAIN, "rustc", "--version", "--verbose"))
    cargo = _run_version(("rustup", "run", RUST_TOOLCHAIN, "cargo", "--version", "--verbose"))
    target_libdir = _run_version(
        (
            "rustup",
            "run",
            RUST_TOOLCHAIN,
            "rustc",
            "--print",
            "target-libdir",
            "--target",
            RUST_TARGET,
        )
    )
    if not Path(target_libdir).is_dir():
        raise BinaryFreezeError("frozen Rust musl target is unavailable")
    return (
        f"rustc:\n{rustc}\ncargo:\n{cargo}\n"
        f"target: {RUST_TARGET}\ntarget-libdir: {target_libdir}"
    )


def _run_version(argv: tuple[str, ...]) -> str:
    environment = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"}
    if "HOME" in os.environ:
        environment["HOME"] = os.environ["HOME"]
    try:
        result = subprocess.run(
            argv,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="strict",
            env=environment,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
        raise BinaryFreezeError("Rust toolchain probe failed") from exc
    if result.returncode != 0 or not result.stdout.strip():
        raise BinaryFreezeError("Rust toolchain probe failed")
    return result.stdout.strip()


def _validate_toolchain(value: str) -> None:
    if not isinstance(value, str):
        raise BinaryFreezeError("Rust toolchain evidence is invalid")
    if "\nrelease: 1.95.0\n" not in f"\n{value}\n" or f"\nhost: {RUST_HOST}\n" not in f"\n{value}\n":
        raise BinaryFreezeError("rustc identity differs from the frozen toolchain")
    if not any(line.startswith("cargo 1.95.0 ") for line in value.splitlines()):
        raise BinaryFreezeError("Cargo identity differs from the frozen toolchain")
    if f"target: {RUST_TARGET}" not in value.splitlines():
        raise BinaryFreezeError("Rust build target differs from the portable musl freeze")


def _validate_static_musl_binary(path: Path) -> None:
    """Require a static x86-64 ELF with no host dynamic-loader dependency."""

    readelf = _regular_file(Path("/usr/bin/x86_64-linux-gnu-readelf"), executable=True)
    try:
        result = subprocess.run(
            (
                str(readelf),
                "--file-header",
                "--program-headers",
                "--dynamic",
                "--wide",
                str(path),
            ),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="strict",
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
        raise BinaryFreezeError("portable binary ELF probe failed") from exc
    output = result.stdout
    if (
        result.returncode != 0
        or "ELF64" not in output
        or "Advanced Micro Devices X86-64" not in output
        or " INTERP " in output
        or "(NEEDED)" in output
    ):
        raise BinaryFreezeError("binary is not a static x86_64 musl artifact")


def _publish_legacy(
    artifact: Path, source_binary: Path, manifest: _LegacyBinaryManifest
) -> None:
    parent = artifact.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _reject_symlink_chain(parent)
    staging = Path(tempfile.mkdtemp(prefix=f".{artifact.name}.staging-", dir=parent))
    try:
        _copy_regular(source_binary, staging / "codex", mode=0o555)
        payload = json.dumps(asdict(manifest), sort_keys=True, separators=(",", ":")).encode() + b"\n"
        _write_exclusive(staging / "manifest.json", payload, mode=0o600)
        _fsync_directory(staging)
        if artifact.exists() or artifact.is_symlink():
            raise BinaryFreezeError("artifact path appeared before atomic publication")
        _rename_noreplace(staging, artifact)
        _fsync_directory(parent)
    except Exception:
        if staging.exists() and staging.is_dir() and not staging.is_symlink():
            _remove_private_tree(staging)
        raise
    published = _read_legacy_manifest(artifact / "manifest.json")
    binary = _regular_file(artifact / "codex", executable=True, exact_mode=0o555)
    if published != manifest or _sha256_file(binary) != manifest.sha256:
        raise BinaryFreezeError("atomic publication differs from its manifest")


def _publish_bundle(
    artifact: Path,
    source_binary: Path,
    source_host: Path,
    manifest: BinaryManifest,
    proof: WatchdogProof,
) -> None:
    parent = artifact.parent
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    _reject_symlink_chain(parent)
    staging = Path(tempfile.mkdtemp(prefix=f".{artifact.name}.staging-", dir=parent))
    try:
        _copy_regular(source_binary, staging / "codex", mode=0o555)
        _copy_regular(source_host, staging / "codex-code-mode-host", mode=0o555)
        payload = json.dumps(asdict(manifest), sort_keys=True, separators=(",", ":")).encode() + b"\n"
        _write_exclusive(staging / "manifest.json", payload, mode=0o600)
        if (
            _sha256_file(staging / "codex") != manifest.sha256
            or _sha256_file(staging / "codex-code-mode-host")
            != manifest.code_mode_host_sha256
        ):
            raise BinaryFreezeError("staged bundle bytes differ from their verified inputs")
        _fsync_directory(staging)
        _held(proof)
        if artifact.exists() or artifact.is_symlink():
            raise BinaryFreezeError("binary bundle appeared before atomic publication")
        _rename_noreplace(staging, artifact)
        _fsync_directory(parent)
    except Exception:
        if staging.exists() and staging.is_dir() and not staging.is_symlink():
            _remove_private_tree(staging)
        raise
    published = _read_manifest(artifact / "manifest.json")
    binary = _regular_file(artifact / "codex", executable=True, exact_mode=0o555)
    host = _regular_file(
        artifact / "codex-code-mode-host", executable=True, exact_mode=0o555
    )
    if (
        published != manifest
        or _sha256_file(binary) != manifest.sha256
        or _sha256_file(host) != manifest.code_mode_host_sha256
    ):
        raise BinaryFreezeError("atomic bundle publication differs from its manifest")


def _copy_regular(source: Path, destination: Path, *, mode: int) -> None:
    source_fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        info = os.fstat(source_fd)
        if not stat.S_ISREG(info.st_mode):
            raise BinaryFreezeError("release binary is not a regular file")
        destination_fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        try:
            while chunk := os.read(source_fd, 1024 * 1024):
                _write_all(destination_fd, chunk)
            os.fchmod(destination_fd, mode)
            os.fsync(destination_fd)
        finally:
            os.close(destination_fd)
    finally:
        os.close(source_fd)


def _write_exclusive(path: Path, payload: bytes, *, mode: int) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        _write_all(descriptor, payload)
        os.fchmod(descriptor, mode)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _read_manifest(path: Path) -> BinaryManifest:
    manifest_path = _regular_file(path, exact_mode=0o600)
    try:
        value = json.loads(manifest_path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BinaryFreezeError("binary manifest is unreadable") from exc
    if not isinstance(value, dict) or set(value) != _MANIFEST_KEYS:
        raise BinaryFreezeError("binary manifest schema differs")
    command = value.get("build_command")
    host_command = value.get("code_mode_host_build_command")
    if not isinstance(command, list) or not isinstance(host_command, list):
        raise BinaryFreezeError("binary bundle manifest build command is invalid")
    try:
        manifest = BinaryManifest(
            path=value["path"],
            sha256=value["sha256"],
            code_mode_host_path=value["code_mode_host_path"],
            code_mode_host_sha256=value["code_mode_host_sha256"],
            source_commit=value["source_commit"],
            source_dirty=value["source_dirty"],
            rust_toolchain=value["rust_toolchain"],
            build_command=tuple(command),
            code_mode_host_build_command=tuple(host_command),
            workspace_lock_normalization=value["workspace_lock_normalization"],
        )
        manifest.validate()
    except (ContractError, TypeError) as exc:
        raise BinaryFreezeError("binary manifest contract is invalid") from exc
    return manifest


def _read_legacy_manifest(path: Path) -> _LegacyBinaryManifest:
    manifest_path = _regular_file(path, exact_mode=0o600)
    try:
        value = json.loads(manifest_path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise BinaryFreezeError("legacy binary manifest is unreadable") from exc
    if not isinstance(value, dict) or set(value) != _LEGACY_MANIFEST_KEYS:
        raise BinaryFreezeError("legacy binary manifest schema differs")
    command = value.get("build_command")
    if not isinstance(command, list):
        raise BinaryFreezeError("legacy binary manifest build command is invalid")
    try:
        manifest = _LegacyBinaryManifest(
            path=value["path"],
            sha256=value["sha256"],
            source_commit=value["source_commit"],
            source_dirty=value["source_dirty"],
            rust_toolchain=value["rust_toolchain"],
            build_command=tuple(command),
            workspace_lock_normalization=value["workspace_lock_normalization"],
        )
        _validate_legacy_manifest_contract(manifest)
    except (TypeError, ValueError) as exc:
        raise BinaryFreezeError("legacy binary manifest contract is invalid") from exc
    return manifest


def _validate_legacy_manifest_contract(manifest: _LegacyBinaryManifest) -> None:
    if not isinstance(manifest.path, str) or not manifest.path:
        raise BinaryFreezeError("legacy binary path is required")
    if not isinstance(manifest.sha256, str) or not _SHA256.fullmatch(manifest.sha256):
        raise BinaryFreezeError("legacy binary sha256 is invalid")
    _validate_commit(manifest.source_commit)
    if not isinstance(manifest.source_dirty, bool):
        raise BinaryFreezeError("legacy binary source_dirty must be boolean")
    if (
        not isinstance(manifest.rust_toolchain, str)
        or not manifest.rust_toolchain
        or not isinstance(manifest.build_command, tuple)
        or not manifest.build_command
        or any(not isinstance(item, str) or not item for item in manifest.build_command)
    ):
        raise BinaryFreezeError("legacy binary toolchain and build command are required")
    if manifest.workspace_lock_normalization is not None and (
        not isinstance(manifest.workspace_lock_normalization, str)
        or not manifest.workspace_lock_normalization
    ):
        raise BinaryFreezeError("legacy lock normalization is invalid")


def _tracked_modes(reference: Path) -> dict[str, int]:
    result = _git_bytes(reference, "ls-files", "--stage", "-z")
    modes: dict[str, int] = {}
    for record in result.split(b"\0"):
        if not record:
            continue
        metadata, separator, raw_path = record.partition(b"\t")
        fields = metadata.split()
        if not separator or len(fields) != 3:
            raise BinaryFreezeError("baseline tracked-file metadata is invalid")
        try:
            relative = raw_path.decode("utf-8")
            mode = int(fields[0], 8)
        except (UnicodeError, ValueError) as exc:
            raise BinaryFreezeError("baseline tracked-file metadata is invalid") from exc
        relative_path = Path(relative)
        if (
            relative_path.is_absolute()
            or ".." in relative_path.parts
            or not relative_path.parts
            or mode not in {0o100644, 0o100755, 0o120000}
            or relative in modes
        ):
            raise BinaryFreezeError("baseline contains an unsupported tracked entry")
        modes[relative] = mode
    if not modes:
        raise BinaryFreezeError("baseline tracked-file list is empty")
    return modes


def _tree_entries(root: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    stack = [root]
    while stack:
        directory = stack.pop()
        for entry in os.scandir(directory):
            path = Path(entry.path)
            relative = str(path.relative_to(root))
            if entry.is_symlink() or entry.is_file(follow_symlinks=False):
                result[relative] = path
            elif entry.is_dir(follow_symlinks=False):
                stack.append(path)
            else:
                raise BinaryFreezeError("baseline scratch contains an unsupported filesystem entry")
    return result


def _validate_mode(path: Path, tracked_mode: int) -> None:
    info = path.lstat()
    if tracked_mode == 0o120000:
        valid = stat.S_ISLNK(info.st_mode)
    else:
        valid = stat.S_ISREG(info.st_mode) and bool(info.st_mode & 0o111) == (tracked_mode == 0o100755)
    if not valid:
        raise BinaryFreezeError("baseline scratch file mode differs from the frozen commit")


def _git(directory: Path, *args: str) -> str:
    result = _git_result(directory, *args)
    if result.returncode != 0:
        raise BinaryFreezeError("Git source identity check failed")
    return result.stdout.strip()


def _git_bytes(directory: Path, *args: str) -> bytes:
    try:
        result = subprocess.run(
            ("git", "-C", str(directory), *args),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"},
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        raise BinaryFreezeError("Git source identity check failed") from exc
    if result.returncode != 0:
        raise BinaryFreezeError("Git source identity check failed")
    return result.stdout


def _git_result(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ("git", "-C", str(directory), *args),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="strict",
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"},
            timeout=60,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
        raise BinaryFreezeError("Git source identity check failed") from exc


def _expected_target(root: Path, side: Side, commit: str) -> Path:
    name = (
        f"rondo-{commit}-{RUST_TARGET}"
        if side is Side.RONDO
        else f"codex-rust-v0.147.0-{commit}-{RUST_TARGET}"
    )
    return root / "eval-data" / "build" / name


def _expected_artifact(root: Path, side: Side, commit: str) -> Path:
    if side is Side.RONDO:
        return root / "eval-data" / "bin" / "rondo" / f"{commit}-{RUST_TARGET}"
    return (
        root
        / "eval-data"
        / "bin"
        / "codex"
        / f"rust-v0.147.0-{commit}-{RUST_TARGET}"
    )


def _expected_bundle(root: Path, side: Side, commit: str) -> Path:
    artifact = _expected_artifact(root, side, commit)
    return artifact.with_name(f"{artifact.name}-code-mode-bundle")


def _exact_existing_directory(value: Path, expected: Path, label: str) -> Path:
    if value != expected or not value.is_absolute():
        raise BinaryFreezeError(f"{label} path differs from the frozen layout")
    return _regular_directory(value)


def _exact_absent_path(value: Path, expected: Path, label: str) -> Path:
    if value != expected or not value.is_absolute():
        raise BinaryFreezeError(f"{label} path differs from the frozen layout")
    if value.exists() or value.is_symlink():
        raise BinaryFreezeError(f"{label} path already exists")
    _reject_symlink_chain(value.parent)
    return value


def _regular_directory(path: Path) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise BinaryFreezeError("required directory is unavailable") from exc
    if resolved != path or path.is_symlink() or not path.is_dir():
        raise BinaryFreezeError("required directory is not an exact regular directory")
    return resolved


def _regular_file(
    path: Path,
    *,
    executable: bool = False,
    exact_mode: int | None = None,
) -> Path:
    try:
        info = path.lstat()
    except OSError as exc:
        raise BinaryFreezeError("required file is unavailable") from exc
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise BinaryFreezeError("required file is not regular")
    if executable and not os.access(path, os.X_OK):
        raise BinaryFreezeError("required executable is not executable")
    if exact_mode is not None and stat.S_IMODE(info.st_mode) != exact_mode:
        raise BinaryFreezeError("frozen file mode differs")
    return path


def _reject_symlink_chain(path: Path) -> None:
    current = path
    while not current.exists():
        current = current.parent
    if current.is_symlink() or current.resolve(strict=True) != current:
        raise BinaryFreezeError("output path contains a symlinked parent")


def _lexically_below(path: Path, root: Path) -> bool:
    return path.is_absolute() and path != root and path.is_relative_to(root)


def _validate_commit(value: str) -> None:
    if not isinstance(value, str) or not _COMMIT.fullmatch(value):
        raise BinaryFreezeError("source commit must be 40 lowercase hexadecimal characters")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    value = digest.hexdigest()
    if not _SHA256.fullmatch(value):
        raise BinaryFreezeError("SHA-256 calculation failed")
    return value


def _proof(factory: LeaseFactory) -> WatchdogProof:
    try:
        proof = factory()
        proof.lease.validate()
    except Exception as exc:
        raise BinaryFreezeError("live RONDO watchdog proof is required") from exc
    _held(proof)
    return proof


def _held(proof: WatchdogProof) -> None:
    if proof.guard.is_held(proof.lease) is not True:
        raise BinaryFreezeError("RONDO watchdog lease is no longer held")


def _result(
    side: Side,
    artifact: Path,
    manifest: BinaryManifest | _LegacyBinaryManifest,
) -> FreezeResult:
    return FreezeResult(
        side=side.value,
        manifest_path=str(artifact / "manifest.json"),
        binary_path=manifest.path,
        binary_sha256=manifest.sha256,
        source_commit=manifest.source_commit,
        code_mode_host_path=(
            manifest.code_mode_host_path if isinstance(manifest, BinaryManifest) else None
        ),
        code_mode_host_sha256=(
            manifest.code_mode_host_sha256 if isinstance(manifest, BinaryManifest) else None
        ),
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _rename_noreplace(source: Path, destination: Path) -> None:
    try:
        renameat2 = ctypes.CDLL(None, use_errno=True).renameat2
    except (AttributeError, OSError) as exc:
        raise BinaryFreezeError("atomic no-replace publication is unavailable") from exc
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    result = renameat2(
        -100,
        os.fsencode(source),
        -100,
        os.fsencode(destination),
        1,
    )
    if result == 0:
        return
    error = ctypes.get_errno()
    if error == errno.EEXIST:
        raise BinaryFreezeError("publication target already exists")
    raise BinaryFreezeError("atomic no-replace publication failed")


def _fsync_tree_directories(root: Path) -> None:
    directories = [Path(directory) for directory, _, _ in os.walk(root, topdown=False)]
    for directory in directories:
        _fsync_directory(directory)


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise BinaryFreezeError("filesystem write made no progress")
        view = view[written:]


def _remove_private_tree(root: Path) -> None:
    for entry in os.scandir(root):
        path = Path(entry.path)
        if entry.is_dir(follow_symlinks=False):
            _remove_private_tree(path)
        else:
            path.unlink()
    root.rmdir()


def _parse_side(value: str) -> Side:
    try:
        return Side(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("side must be codex or rondo") from exc


def _request_from_args(args: argparse.Namespace) -> FreezeRequest:
    return FreezeRequest(
        side=args.side,
        common_root=args.common_root,
        source_root=args.source_root,
        source_commit=args.source_commit,
        target_dir=args.target_dir,
        artifact_dir=args.artifact_dir,
        gate_root=args.gate_root,
        baseline_reference_root=args.baseline_reference_root,
    )


def _companion_request_from_args(args: argparse.Namespace) -> CompanionFreezeRequest:
    return CompanionFreezeRequest(
        side=args.side,
        common_root=args.common_root,
        source_root=args.source_root,
        source_commit=args.source_commit,
        target_dir=args.target_dir,
        legacy_artifact_dir=args.legacy_artifact_dir,
        bundle_dir=args.bundle_dir,
        gate_root=args.gate_root,
        baseline_reference_root=args.baseline_reference_root,
    )


def _add_source_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--side", type=_parse_side, required=True)
    command.add_argument("--common-root", type=Path, required=True)
    command.add_argument("--source-root", type=Path, required=True)
    command.add_argument("--source-commit", required=True)
    command.add_argument("--target-dir", type=Path, required=True)
    command.add_argument("--gate-root", type=Path, required=True)
    command.add_argument("--baseline-reference-root", type=Path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rondo-binary-freeze")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    export_parser = subparsers.add_parser("export-baseline")
    export_parser.add_argument("--common-root", type=Path, required=True)
    export_parser.add_argument("--baseline-reference-root", type=Path, required=True)
    export_parser.add_argument("--source-commit", required=True)
    export_parser.add_argument("--scratch-dir", type=Path, required=True)
    v8_parser = subparsers.add_parser("v8-build")
    v8_parser.add_argument("--side", type=_parse_side, required=True)
    v8_parser.add_argument("--source-root", type=Path, required=True)
    v8_parser.add_argument("--source-commit", required=True)
    v8_parser.add_argument("--baseline-reference-root", type=Path)
    for operation in ("prepare", "verify"):
        command = subparsers.add_parser(operation)
        _add_source_arguments(command)
        command.add_argument("--artifact-dir", type=Path, required=True)
        if operation == "prepare":
            command.add_argument("--build-command-json", required=True)
    for operation in ("prepare-companion", "verify-companion"):
        command = subparsers.add_parser(operation)
        _add_source_arguments(command)
        command.add_argument("--legacy-artifact-dir", type=Path, required=True)
        command.add_argument("--bundle-dir", type=Path, required=True)
        if operation == "prepare-companion":
            command.add_argument("--code-mode-host-build-command-json", required=True)
    cleanup_parser = subparsers.add_parser("cleanup")
    cleanup_parser.add_argument("--side", type=_parse_side, required=True)
    cleanup_parser.add_argument("--common-root", type=Path, required=True)
    cleanup_parser.add_argument("--source-commit", required=True)
    cleanup_parser.add_argument("--target-dir", type=Path, required=True)
    cleanup_parser.add_argument("--scratch-dir", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.operation == "export-baseline":
            result = export_baseline(
                common_root=args.common_root,
                baseline_reference_root=args.baseline_reference_root,
                source_commit=args.source_commit,
                scratch_dir=args.scratch_dir,
            )
        elif args.operation == "v8-build":
            exec_v8_build(
                side=args.side,
                source_root=args.source_root,
                source_commit=args.source_commit,
                baseline_reference_root=args.baseline_reference_root,
            )
        elif args.operation == "prepare":
            value = json.loads(args.build_command_json)
            if not isinstance(value, list):
                raise BinaryFreezeError("build command JSON must be an argv array")
            result = prepare(_request_from_args(args), value)
        elif args.operation == "verify":
            result = verify(_request_from_args(args))
        elif args.operation == "prepare-companion":
            value = json.loads(args.code_mode_host_build_command_json)
            if not isinstance(value, list):
                raise BinaryFreezeError("code-mode host build command JSON must be an argv array")
            result = prepare_companion(_companion_request_from_args(args), value)
        elif args.operation == "verify-companion":
            result = verify_companion(_companion_request_from_args(args))
        else:
            cleanup(
                side=args.side,
                common_root=args.common_root,
                source_commit=args.source_commit,
                target_dir=args.target_dir,
                scratch_dir=args.scratch_dir,
            )
        print(json.dumps(asdict(result), sort_keys=True, separators=(",", ":")))
        return 0
    except (BinaryFreezeError, json.JSONDecodeError, OSError, UnicodeError, ValueError) as exc:
        print(f"rondo-binary-freeze: {exc}", file=sys.stderr)
        return 78


if __name__ == "__main__":
    raise SystemExit(main())
