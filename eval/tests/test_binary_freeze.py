from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval import binary_freeze  # noqa: E402
from rondo_eval.binary_freeze import (  # noqa: E402
    BinaryFreezeError,
    CompanionFreezeRequest,
    FreezeRequest,
    RuntimeFreezeRequest,
    cleanup,
    exec_v8_build,
    export_baseline,
    prepare,
    prepare_companion,
    prepare_libcap,
    prepare_runtime,
    verify,
    verify_companion,
    verify_libcap,
    verify_runtime,
)
from rondo_eval.contracts import Side  # noqa: E402


TOOLCHAIN = """\
rustc:
rustc 1.95.0 (fixture)
binary: rustc
commit-hash: fixture
commit-date: fixture
host: x86_64-unknown-linux-gnu
release: 1.95.0
LLVM version: fixture
cargo:
cargo 1.95.0 (fixture)
target: x86_64-unknown-linux-musl
target-libdir: /fixture/rustlib/x86_64-unknown-linux-musl/lib
""".strip()


class _Lease:
    held = True
    token = "a" * 48

    def validate(self) -> None:
        return None


class _Guard:
    def __init__(self) -> None:
        self.held = True

    def is_held(self, lease: object) -> bool:
        return self.held and lease is LEASE


LEASE = _Lease()
GUARD = _Guard()


class _Proof:
    lease = LEASE
    guard = GUARD


def _lease_factory() -> _Proof:
    return _Proof()


def _run(*argv: str, cwd: Path) -> str:
    result = subprocess.run(
        argv,
        cwd=cwd,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.strip()


def _write_workspace(root: Path, lock: bytes, *, gate: bool) -> None:
    workspace = root / "mydev" / "codex-rs" if gate else root / "codex-rs"
    (workspace / "cli" / "src").mkdir(parents=True)
    (workspace / "Cargo.lock").write_bytes(lock)
    (workspace / "rust-toolchain.toml").write_text(
        '[toolchain]\nchannel = "1.95.0"\n', encoding="utf-8"
    )
    (workspace / "Cargo.toml").write_text(
        '[workspace]\nmembers = ["cli"]\n\n[workspace.package]\nversion = "0.147.0"\n',
        encoding="utf-8",
    )
    (workspace / "cli" / "Cargo.toml").write_text(
        '[package]\nname = "codex-cli"\nversion.workspace = true\n\n'
        '[[bin]]\nname = "codex"\npath = "src/main.rs"\n',
        encoding="utf-8",
    )
    (workspace / "cli" / "src" / "main.rs").write_text("fn main() {}\n", encoding="utf-8")
    (workspace / "code-mode-host" / "src").mkdir(parents=True)
    (workspace / "code-mode-host" / "Cargo.toml").write_text(
        '[package]\nname = "codex-code-mode-host"\nversion.workspace = true\n\n'
        '[[bin]]\nname = "codex-code-mode-host"\npath = "src/main.rs"\n',
        encoding="utf-8",
    )
    (workspace / "code-mode-host" / "src" / "main.rs").write_text(
        "fn main() {}\n", encoding="utf-8"
    )
    (workspace / "bwrap" / "src").mkdir(parents=True)
    (workspace / "bwrap" / "Cargo.toml").write_text(
        '[package]\nname = "codex-bwrap"\nversion.workspace = true\n\n'
        '[[bin]]\nname = "bwrap"\npath = "src/main.rs"\n',
        encoding="utf-8",
    )
    (workspace / "bwrap" / "src" / "main.rs").write_text(
        "fn main() {}\n", encoding="utf-8"
    )
    if gate:
        scripts = root / "mydev" / "scripts"
        scripts.mkdir(parents=True)
        watchdog = scripts / "with-build-lock.sh"
        watchdog.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        watchdog.chmod(0o755)
        v8_gate = scripts / "with_codex_v8_artifacts.py"
        v8_gate.write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        v8_gate.chmod(0o644)


def _init_detached_repository(root: Path, *, tag: str | None = None) -> str:
    _run("git", "init", "-q", cwd=root)
    _run("git", "config", "user.name", "Rondo Test", cwd=root)
    _run("git", "config", "user.email", "rondo@example.invalid", cwd=root)
    _run("git", "add", ".", cwd=root)
    _run("git", "commit", "-qm", "fixture", cwd=root)
    commit = _run("git", "rev-parse", "HEAD", cwd=root)
    if tag is not None:
        _run("git", "tag", tag, cwd=root)
    _run("git", "checkout", "-q", "--detach", commit, cwd=root)
    return commit


def _build_command(
    *,
    common: Path,
    source: Path,
    target: Path,
    gate: Path,
    side: Side,
    source_commit: str,
    package: str = "codex-cli",
    binary: str = "codex",
    baseline_reference: Path | None = None,
) -> tuple[str, ...]:
    manifest = source / ("mydev/codex-rs/Cargo.toml" if side is Side.RONDO else "codex-rs/Cargo.toml")
    companion = package == "codex-code-mode-host" and binary == "codex-code-mode-host"
    argv = [
        f"cwd={gate}",
        "env",
        "-i",
        f"HOME={os.environ['HOME']}",
        f"PATH={os.environ['PATH']}",
        "LC_ALL=C.UTF-8",
        f"XDG_RUNTIME_DIR=/run/user/{os.getuid()}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{os.getuid()}/bus",
    ]
    if companion:
        argv.append(f"PYTHONPATH={binary_freeze.EVAL_ROOT}")
    argv.extend(
        (
        f"RONDO_PROJECT_ROOT={common}",
        f"CARGO_TARGET_DIR={target}",
        f"RONDO_BUILD_METRICS_DIR={common}/eval-data/build-metrics/test",
        str(gate / "mydev/scripts/with-build-lock.sh"),
        "rustup",
        "run",
        "1.95.0",
        )
    )
    if companion:
        argv.extend(
            (
                "python3",
                "-m",
                "rondo_eval.binary_freeze",
                "v8-build",
                "--side",
                side.value,
                "--source-root",
                str(source),
                "--source-commit",
                source_commit,
            )
        )
        if side is Side.CODEX:
            assert baseline_reference is not None
            argv.extend(("--baseline-reference-root", str(baseline_reference)))
        return tuple(argv)
    argv.extend(
        (
        "python3",
        str(gate / "mydev/scripts/with_codex_v8_artifacts.py"),
        "--",
        "cargo",
        "build",
        "--locked",
        "--release",
        "--target",
        binary_freeze.RUST_TARGET,
        "--manifest-path",
        str(manifest),
        "-p",
        "codex-cli",
        "--bin",
        "codex",
        )
    )
    return tuple(argv)


def _write_watchdog_summary(common: Path) -> None:
    run = common / "eval-data/build-metrics/test/run-1"
    run.mkdir(parents=True)
    (run / "summary.env").write_text(
        "command_name=rustup\n"
        "wrapper_status=complete\n"
        "run_rc=0\n"
        "final_rc=0\n"
        "stop_reason=none\n"
        "cleanup_reason=none\n"
        "target_after_bytes=1024\n"
        "target_peak_sampled_bytes=2048\n",
        encoding="ascii",
    )


def _bwrap_build_command(
    *, common: Path, source: Path, target: Path, gate: Path, side: Side, libcap: Path
) -> tuple[str, ...]:
    manifest = source / (
        "mydev/codex-rs/Cargo.toml" if side is Side.RONDO else "codex-rs/Cargo.toml"
    )
    return (
        f"cwd={gate}",
        "env",
        "-i",
        f"HOME={os.environ['HOME']}",
        f"PATH={os.environ['PATH']}",
        "LC_ALL=C.UTF-8",
        f"XDG_RUNTIME_DIR=/run/user/{os.getuid()}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{os.getuid()}/bus",
        "PKG_CONFIG_ALLOW_CROSS=1",
        f"PKG_CONFIG_PATH={libcap}/lib/pkgconfig",
        "LIBCAP_STATIC=1",
        f"RONDO_PROJECT_ROOT={common}",
        f"CARGO_TARGET_DIR={target}",
        f"RONDO_BUILD_METRICS_DIR={common}/eval-data/build-metrics/test",
        str(gate / "mydev/scripts/with-build-lock.sh"),
        "rustup",
        "run",
        "1.95.0",
        "cargo",
        "build",
        "--locked",
        "--release",
        "--target",
        binary_freeze.RUST_TARGET,
        "--manifest-path",
        str(manifest),
        "-p",
        "codex-bwrap",
        "--bin",
        "bwrap",
    )


def _write_libcap_dependency(common: Path) -> Path:
    destination = common / "eval-data" / "deps" / binary_freeze.LIBCAP_DEPENDENCY_NAME
    destination.mkdir(parents=True, mode=0o700)
    (destination / "include").mkdir(mode=0o700)
    (destination / "include/sys").mkdir(mode=0o700)
    (destination / "lib").mkdir(mode=0o700)
    (destination / "lib/pkgconfig").mkdir(mode=0o700)
    header = destination / "include/sys/capability.h"
    header.write_bytes(b"#define LIBCAP_FIXTURE 1\n")
    header.chmod(0o444)
    library = destination / "lib/libcap.a"
    library.write_bytes(b"!<arch>\nfixture")
    library.chmod(0o444)
    pc = destination / "lib/pkgconfig/libcap.pc"
    pc.write_bytes(binary_freeze._libcap_pc_bytes(destination))
    pc.chmod(0o444)
    manifest = {
        "schema_version": 1,
        "name": "libcap",
        "version": binary_freeze.LIBCAP_VERSION,
        "target": binary_freeze.RUST_TARGET,
        "url": binary_freeze.LIBCAP_URL,
        "archive_sha256": binary_freeze.LIBCAP_ARCHIVE_SHA256,
        "static_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
        "build_command": list(binary_freeze._LIBCAP_BUILD_COMMAND),
    }
    manifest_path = destination / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    manifest_path.chmod(0o600)
    return destination


def _libcap_archive_bytes(*, unsafe_member: str | None = None) -> bytes:
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:xz") as archive:
        entries = {
            "libcap-2.78/libcap/Makefile": b"libcap.a:\n\t@true\n",
            "libcap-2.78/libcap/include/sys/capability.h": b"#define LIBCAP_FIXTURE 1\n",
        }
        if unsafe_member is not None:
            entries[unsafe_member] = b"escape"
        for name, payload in entries.items():
            info = tarfile.TarInfo(name)
            info.mode = 0o644
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return output.getvalue()


class LibcapFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        GUARD.held = True
        self.temporary = tempfile.TemporaryDirectory()
        self.common = Path(self.temporary.name).resolve()
        self.archive = _libcap_archive_bytes()
        self.archive_sha = hashlib.sha256(self.archive).hexdigest()
        self.lock = binary_freeze._LibcapLock(
            schema_version=1,
            name="libcap",
            version=binary_freeze.LIBCAP_VERSION,
            target=binary_freeze.RUST_TARGET,
            url=binary_freeze.LIBCAP_URL,
            archive_sha256=self.archive_sha,
        )

    def tearDown(self) -> None:
        GUARD.held = True
        self.temporary.cleanup()

    def test_tracked_lock_matches_frozen_release(self) -> None:
        lock = binary_freeze._load_libcap_lock()
        self.assertEqual(lock.version, "2.78")
        self.assertEqual(lock.target, binary_freeze.RUST_TARGET)
        self.assertEqual(lock.archive_sha256, binary_freeze.LIBCAP_ARCHIVE_SHA256)

    def _download(self, payload: bytes):
        def download(url: str, destination: Path, proof: object) -> None:
            self.assertEqual(url, binary_freeze.LIBCAP_URL)
            destination.write_bytes(payload)
            destination.chmod(0o600)

        return download

    def _build(self, *, expire_lease: bool = False):
        def run(argv: object, *, cwd: Path, environment: object) -> None:
            self.assertEqual(tuple(argv), binary_freeze._LIBCAP_BUILD_COMMAND)
            self.assertEqual(
                dict(environment),
                {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "SOURCE_DATE_EPOCH": "0"},
            )
            self.assertEqual((cwd / "libcap/Makefile").read_text("utf-8"), "libcap.a:\n\t@true\n")
            library = cwd / "libcap/libcap.a"
            library.write_bytes(b"!<arch>\nfixture-libcap")
            if expire_lease:
                GUARD.held = False

        return run

    def test_prepares_and_verifies_pinned_dependency_without_overwrite(self) -> None:
        with mock.patch.object(binary_freeze, "_load_libcap_lock", return_value=self.lock):
            prepared = prepare_libcap(
                common_root=self.common,
                lease_factory=_lease_factory,
                download_function=self._download(self.archive),
                run_function=self._build(),
            )
            verified = verify_libcap(
                common_root=self.common,
                lease_factory=_lease_factory,
            )
            with self.assertRaises(BinaryFreezeError):
                prepare_libcap(
                    common_root=self.common,
                    lease_factory=_lease_factory,
                    download_function=self._download(self.archive),
                    run_function=self._build(),
                )

        self.assertEqual(prepared, verified)
        dependency = Path(prepared.dependency_path)
        self.assertEqual(dependency.name, binary_freeze.LIBCAP_DEPENDENCY_NAME)
        self.assertEqual((dependency / "lib/libcap.a").stat().st_mode & 0o777, 0o444)
        self.assertEqual((dependency / "manifest.json").stat().st_mode & 0o777, 0o600)
        manifest = json.loads((dependency / "manifest.json").read_text("utf-8"))
        self.assertEqual(manifest["archive_sha256"], self.archive_sha)
        self.assertEqual(manifest["static_sha256"], prepared.static_sha256)
        self.assertEqual(manifest["build_command"], list(binary_freeze._LIBCAP_BUILD_COMMAND))

    def test_rejects_bad_checksum_and_unsafe_tar_member(self) -> None:
        runner = mock.Mock()
        wrong_lock = binary_freeze._LibcapLock(
            schema_version=1,
            name="libcap",
            version=binary_freeze.LIBCAP_VERSION,
            target=binary_freeze.RUST_TARGET,
            url=binary_freeze.LIBCAP_URL,
            archive_sha256="0" * 64,
        )
        with (
            mock.patch.object(binary_freeze, "_load_libcap_lock", return_value=wrong_lock),
            self.assertRaises(BinaryFreezeError),
        ):
            prepare_libcap(
                common_root=self.common,
                lease_factory=_lease_factory,
                download_function=self._download(self.archive),
                run_function=runner,
            )
        runner.assert_not_called()

        unsafe = _libcap_archive_bytes(unsafe_member="libcap-2.78/../../escape")
        unsafe_lock = binary_freeze._LibcapLock(
            schema_version=1,
            name="libcap",
            version=binary_freeze.LIBCAP_VERSION,
            target=binary_freeze.RUST_TARGET,
            url=binary_freeze.LIBCAP_URL,
            archive_sha256=hashlib.sha256(unsafe).hexdigest(),
        )
        with (
            mock.patch.object(binary_freeze, "_load_libcap_lock", return_value=unsafe_lock),
            self.assertRaises(BinaryFreezeError),
        ):
            prepare_libcap(
                common_root=self.common,
                lease_factory=_lease_factory,
                download_function=self._download(unsafe),
                run_function=runner,
            )
        self.assertFalse((self.common / "escape").exists())
        runner.assert_not_called()

    def test_expired_watchdog_cannot_publish_dependency(self) -> None:
        with (
            mock.patch.object(binary_freeze, "_load_libcap_lock", return_value=self.lock),
            self.assertRaises(BinaryFreezeError),
        ):
            prepare_libcap(
                common_root=self.common,
                lease_factory=_lease_factory,
                download_function=self._download(self.archive),
                run_function=self._build(expire_lease=True),
            )
        self.assertFalse(
            (self.common / "eval-data/deps" / binary_freeze.LIBCAP_DEPENDENCY_NAME).exists()
        )


class RondoFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        GUARD.held = True
        self.temporary = tempfile.TemporaryDirectory()
        self.common = Path(self.temporary.name).resolve()
        self.source = self.common / "measurement"
        self.source.mkdir()
        self.lock = b'version = 4\n\n[[package]]\nname = "codex-cli"\nversion = "0.147.0"\n'
        _write_workspace(self.source, self.lock, gate=True)
        self.commit = _init_detached_repository(self.source)
        self.target = (
            self.common
            / "eval-data/build"
            / f"rondo-{self.commit}-{binary_freeze.RUST_TARGET}"
        )
        (self.target / binary_freeze.RUST_TARGET / "release").mkdir(parents=True)
        self.release = self.target / binary_freeze.RUST_TARGET / "release/codex"
        self.release.write_bytes(b"frozen-rondo-binary")
        self.release.chmod(0o755)
        self.artifact = (
            self.common
            / "eval-data/bin/rondo"
            / f"{self.commit}-{binary_freeze.RUST_TARGET}"
        )
        self.request = FreezeRequest(
            side=Side.RONDO,
            common_root=self.common,
            source_root=self.source,
            source_commit=self.commit,
            target_dir=self.target,
            artifact_dir=self.artifact,
            gate_root=self.source,
        )
        self.command = _build_command(
            common=self.common,
            source=self.source,
            target=self.target,
            gate=self.source,
            side=Side.RONDO,
            source_commit=self.commit,
        )
        _write_watchdog_summary(self.common)
        self.lock_sha = hashlib.sha256(self.lock).hexdigest()
        self.constants = mock.patch.object(binary_freeze, "NORMALIZED_LOCK_SHA256", self.lock_sha)
        self.constants.start()
        self.portable = mock.patch.object(binary_freeze, "_validate_static_musl_binary")
        self.portable.start()

    def tearDown(self) -> None:
        self.portable.stop()
        self.constants.stop()
        self.temporary.cleanup()

    def _companion_fixture(
        self,
    ) -> tuple[CompanionFreezeRequest, tuple[str, ...], Path, Path]:
        prepare(
            self.request,
            self.command,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )
        host_release = (
            self.target / binary_freeze.RUST_TARGET / "release/codex-code-mode-host"
        )
        host_release.write_bytes(b"frozen-rondo-code-mode-host")
        host_release.chmod(0o755)
        bundle = self.artifact.with_name(f"{self.artifact.name}-code-mode-bundle")
        request = CompanionFreezeRequest(
            side=Side.RONDO,
            common_root=self.common,
            source_root=self.source,
            source_commit=self.commit,
            target_dir=self.target,
            legacy_artifact_dir=self.artifact,
            bundle_dir=bundle,
            gate_root=self.source,
        )
        command = _build_command(
            common=self.common,
            source=self.source,
            target=self.target,
            gate=self.source,
            side=Side.RONDO,
            source_commit=self.commit,
            package="codex-code-mode-host",
            binary="codex-code-mode-host",
        )
        return request, command, bundle, host_release

    def _runtime_fixture(
        self,
    ) -> tuple[RuntimeFreezeRequest, tuple[str, ...], Path, Path, Path]:
        companion_request, companion_command, companion_bundle, _ = self._companion_fixture()
        prepare_companion(
            companion_request,
            companion_command,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )
        bwrap_release = self.target / binary_freeze.RUST_TARGET / "release/bwrap"
        bwrap_release.write_bytes(b"frozen-rondo-bwrap")
        bwrap_release.chmod(0o755)
        libcap = _write_libcap_dependency(self.common)
        runtime_bundle = self.artifact.with_name(f"{self.artifact.name}-runtime-bundle")
        request = RuntimeFreezeRequest(
            side=Side.RONDO,
            common_root=self.common,
            source_root=self.source,
            source_commit=self.commit,
            target_dir=self.target,
            companion_bundle_dir=companion_bundle,
            libcap_dir=libcap,
            runtime_bundle_dir=runtime_bundle,
            gate_root=self.source,
        )
        command = _bwrap_build_command(
            common=self.common,
            source=self.source,
            target=self.target,
            gate=self.source,
            side=Side.RONDO,
            libcap=libcap,
        )
        return request, command, runtime_bundle, companion_bundle, bwrap_release

    def test_prepares_and_verifies_atomic_manifest_and_modes(self) -> None:
        prepared = prepare(
            self.request,
            self.command,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )
        verified = verify(
            self.request,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )

        self.assertEqual(prepared, verified)
        self.assertEqual((self.artifact / "codex").read_bytes(), self.release.read_bytes())
        self.assertEqual((self.artifact / "codex").stat().st_mode & 0o777, 0o555)
        self.assertEqual((self.artifact / "manifest.json").stat().st_mode & 0o777, 0o600)
        manifest = json.loads((self.artifact / "manifest.json").read_text(encoding="utf-8"))
        self.assertFalse(manifest["source_dirty"])
        self.assertIsNone(manifest["workspace_lock_normalization"])
        self.assertEqual(manifest["build_command"], list(self.command))
        with self.assertRaises(BinaryFreezeError):
            prepare(
                self.request,
                self.command,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )

    def test_rejects_dirty_source_wrong_v8_shape_and_expired_lease(self) -> None:
        dirty = self.source / "untracked"
        dirty.write_text("dirty", encoding="utf-8")
        with self.assertRaises(BinaryFreezeError):
            prepare(
                self.request,
                self.command,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )
        dirty.unlink()
        command = list(self.command)
        command[command.index(str(self.source / "mydev/scripts/with_codex_v8_artifacts.py"))] = (
            "/wrong/v8-gate.py"
        )
        with self.assertRaises(BinaryFreezeError):
            prepare(
                self.request,
                command,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )
        command = list(self.command)
        watchdog_index = command.index(str(self.source / "mydev/scripts/with-build-lock.sh"))
        command.insert(watchdog_index, "OPENAI_API_KEY=must-not-cross")
        with self.assertRaises(BinaryFreezeError) as caught:
            prepare(
                self.request,
                command,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )
        self.assertNotIn("must-not-cross", str(caught.exception))
        GUARD.held = False
        with self.assertRaises(BinaryFreezeError):
            prepare(
                self.request,
                self.command,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )

    def test_verify_rejects_binary_and_manifest_mode_tampering(self) -> None:
        prepare(
            self.request,
            self.command,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )
        binary = self.artifact / "codex"
        binary.chmod(0o755)
        with self.assertRaises(BinaryFreezeError):
            verify(
                self.request,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )
        binary.chmod(0o555)
        manifest = self.artifact / "manifest.json"
        manifest.chmod(0o644)
        with self.assertRaises(BinaryFreezeError):
            verify(
                self.request,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )

    def test_publication_refuses_a_racing_destination_without_replacement(self) -> None:
        rename = binary_freeze._rename_noreplace

        def race(source: Path, destination: Path) -> None:
            destination.mkdir()
            rename(source, destination)

        with mock.patch.object(binary_freeze, "_rename_noreplace", side_effect=race):
            with self.assertRaises(BinaryFreezeError):
                prepare(
                    self.request,
                    self.command,
                    lease_factory=_lease_factory,
                    toolchain_probe=lambda: TOOLCHAIN,
                )
        self.assertTrue(self.artifact.is_dir())
        self.assertEqual(list(self.artifact.iterdir()), [])

    def test_companion_migrates_legacy_cli_into_verified_bundle(self) -> None:
        request, command, bundle, host_release = self._companion_fixture()

        prepared = prepare_companion(
            request,
            command,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )
        verified = verify_companion(
            request,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )

        self.assertEqual(prepared, verified)
        self.assertEqual((bundle / "codex").read_bytes(), (self.artifact / "codex").read_bytes())
        self.assertEqual((bundle / "codex-code-mode-host").read_bytes(), host_release.read_bytes())
        self.assertEqual((bundle / "codex").stat().st_mode & 0o777, 0o555)
        self.assertEqual((bundle / "codex-code-mode-host").stat().st_mode & 0o777, 0o555)
        manifest_path = bundle / "manifest.json"
        self.assertEqual(manifest_path.stat().st_mode & 0o777, 0o600)
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(set(manifest), binary_freeze._COMPANION_MANIFEST_KEYS)
        self.assertEqual(manifest["path"], str(bundle / "codex"))
        self.assertEqual(
            manifest["code_mode_host_path"], str(bundle / "codex-code-mode-host")
        )
        self.assertEqual(manifest["build_command"], list(self.command))
        self.assertEqual(manifest["code_mode_host_build_command"], list(command))
        with self.assertRaises(BinaryFreezeError):
            prepare_companion(
                request,
                command,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )

    def test_companion_rejects_wrong_host_command_and_tampering(self) -> None:
        request, command, bundle, _ = self._companion_fixture()
        with self.assertRaises(BinaryFreezeError):
            prepare_companion(
                request,
                self.command,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )
        without_pythonpath = [
            item for item in command if not item.startswith("PYTHONPATH=")
        ]
        with self.assertRaises(BinaryFreezeError):
            prepare_companion(
                request,
                without_pythonpath,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )
        with self.assertRaises(BinaryFreezeError):
            prepare_companion(
                request,
                command[:-3],
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )
        wrong_command = list(command)
        wrong_command[wrong_command.index("rondo_eval.binary_freeze")] = "wrong.v8_gate"
        with self.assertRaises(BinaryFreezeError):
            prepare_companion(
                request,
                wrong_command,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )
        prepare_companion(
            request,
            command,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )
        frozen_host = bundle / "codex-code-mode-host"
        frozen_host.chmod(0o755)
        frozen_host.write_bytes(b"tampered")
        frozen_host.chmod(0o555)
        with self.assertRaises(BinaryFreezeError):
            verify_companion(
                request,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )

    def test_companion_does_not_publish_after_watchdog_lease_loss(self) -> None:
        request, command, bundle, _ = self._companion_fixture()
        copy_regular = binary_freeze._copy_regular
        copies = 0

        def lose_lease_after_copy(source: Path, destination: Path, *, mode: int) -> None:
            nonlocal copies
            copy_regular(source, destination, mode=mode)
            copies += 1
            if copies == 2:
                GUARD.held = False

        with mock.patch.object(
            binary_freeze, "_copy_regular", side_effect=lose_lease_after_copy
        ):
            with self.assertRaises(BinaryFreezeError):
                prepare_companion(
                    request,
                    command,
                    lease_factory=_lease_factory,
                    toolchain_probe=lambda: TOOLCHAIN,
                )
        self.assertFalse(bundle.exists())

    def test_eval_v8_gate_resolves_musl_and_execs_only_the_two_frozen_bins(self) -> None:
        archive = self.common / "cache/librusty_v8_musl.a.gz"
        binding = self.common / "cache/src_binding_musl.rs"
        archive.parent.mkdir()
        archive.write_bytes(b"official-musl-archive")
        binding.write_bytes(b"official-musl-binding")
        spec = SimpleNamespace(target=binary_freeze.RUST_TARGET)
        fetch_calls: list[tuple[object, str]] = []

        def fetch(selected: object, *, version: str) -> object:
            fetch_calls.append((selected, version))
            return SimpleNamespace(archive=archive, binding=binding)

        class ExecCalled(Exception):
            pass

        executed: list[tuple[str, list[str], dict[str, str]]] = []

        def fake_exec(executable: str, argv: list[str], environment: dict[str, str]) -> None:
            executed.append((executable, argv, environment))
            raise ExecCalled

        stderr = io.StringIO()
        with (
            mock.patch.object(
                binary_freeze,
                "_load_source_v8_resolver",
                return_value=(
                    {binary_freeze.RUST_TARGET: spec},
                    fetch,
                    lambda: "150.4.0",
                ),
            ),
            mock.patch.object(binary_freeze.sys, "stderr", stderr),
            self.assertRaises(ExecCalled),
        ):
            exec_v8_build(
                side=Side.RONDO,
                source_root=self.source,
                source_commit=self.commit,
                lease_factory=_lease_factory,
                exec_function=fake_exec,
                environ={"PATH": "/safe/bin", "HOME": "/safe/home"},
            )

        self.assertEqual(fetch_calls, [(spec, "150.4.0")])
        executable, argv, environment = executed[0]
        self.assertEqual(executable, "cargo")
        self.assertEqual(
            argv[-8:],
            [
                "-p",
                "codex-cli",
                "--bin",
                "codex",
                "-p",
                "codex-code-mode-host",
                "--bin",
                "codex-code-mode-host",
            ],
        )
        self.assertEqual(environment["RUSTY_V8_ARCHIVE"], str(archive))
        self.assertEqual(environment["RUSTY_V8_SRC_BINDING_PATH"], str(binding))
        self.assertIn(f"target={binary_freeze.RUST_TARGET}", stderr.getvalue())
        self.assertIn(hashlib.sha256(archive.read_bytes()).hexdigest(), stderr.getvalue())
        self.assertNotIn("/safe/home", stderr.getvalue())

    def test_eval_v8_gate_rejects_ambient_overrides_before_resolution(self) -> None:
        for name in (
            "V8_FROM_SOURCE",
            "RUSTY_V8_ARCHIVE",
            "RUSTY_V8_SRC_BINDING_PATH",
        ):
            with (
                self.subTest(name=name),
                mock.patch.object(binary_freeze, "_load_source_v8_resolver") as resolver,
                self.assertRaises(BinaryFreezeError),
            ):
                exec_v8_build(
                    side=Side.RONDO,
                    source_root=self.source,
                    source_commit=self.commit,
                    lease_factory=_lease_factory,
                    environ={name: ""},
                )
            resolver.assert_not_called()

    def test_runtime_bundle_preserves_companion_and_adds_nested_static_bwrap(self) -> None:
        request, command, runtime, companion, bwrap_release = self._runtime_fixture()

        prepared = prepare_runtime(
            request,
            command,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )
        verified = verify_runtime(
            request,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )

        self.assertEqual(prepared, verified)
        self.assertEqual((runtime / "codex").read_bytes(), (companion / "codex").read_bytes())
        self.assertEqual(
            (runtime / "codex-code-mode-host").read_bytes(),
            (companion / "codex-code-mode-host").read_bytes(),
        )
        self.assertEqual(
            (runtime / "codex-resources/bwrap").read_bytes(), bwrap_release.read_bytes()
        )
        self.assertEqual((runtime / "codex-resources/bwrap").stat().st_mode & 0o777, 0o555)
        self.assertEqual((runtime / "codex-resources").stat().st_mode & 0o777, 0o700)
        manifest = json.loads((runtime / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest), binary_freeze._MANIFEST_KEYS)
        self.assertEqual(manifest["bwrap_path"], str(runtime / "codex-resources/bwrap"))
        self.assertEqual(manifest["bwrap_build_command"], list(command))
        self.assertEqual(manifest["libcap_version"], binary_freeze.LIBCAP_VERSION)
        self.assertEqual(
            manifest["libcap_archive_sha256"], binary_freeze.LIBCAP_ARCHIVE_SHA256
        )
        companion_manifest = json.loads(
            (companion / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["sha256"], companion_manifest["sha256"])
        self.assertEqual(
            manifest["code_mode_host_sha256"], companion_manifest["code_mode_host_sha256"]
        )
        with self.assertRaises(BinaryFreezeError):
            prepare_runtime(
                request,
                command,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )

    def test_runtime_bundle_rejects_non_bwrap_argv_and_tampering(self) -> None:
        request, command, runtime, _, _ = self._runtime_fixture()
        wrong = list(command)
        wrong[wrong.index("codex-bwrap")] = "codex-cli"
        with self.assertRaises(BinaryFreezeError):
            prepare_runtime(
                request,
                wrong,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )
        wrong_environment = list(command)
        wrong_environment[wrong_environment.index("PKG_CONFIG_ALLOW_CROSS=1")] = (
            "PKG_CONFIG_ALLOW_CROSS=0"
        )
        with self.assertRaises(BinaryFreezeError):
            prepare_runtime(
                request,
                wrong_environment,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )
        prepare_runtime(
            request,
            command,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )
        frozen = runtime / "codex-resources/bwrap"
        frozen.chmod(0o755)
        frozen.write_bytes(b"tampered")
        frozen.chmod(0o555)
        with self.assertRaises(BinaryFreezeError):
            verify_runtime(
                request,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )

    def test_runtime_bundle_rejects_tampered_libcap_dependency(self) -> None:
        request, command, _, _, _ = self._runtime_fixture()
        library = request.libcap_dir / "lib/libcap.a"
        library.chmod(0o644)
        library.write_bytes(b"!<arch>\ntampered")
        library.chmod(0o444)
        with self.assertRaises(BinaryFreezeError):
            prepare_runtime(
                request,
                command,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )


class BaselineFreezeTests(unittest.TestCase):
    def setUp(self) -> None:
        GUARD.held = True
        self.temporary = tempfile.TemporaryDirectory()
        self.common = Path(self.temporary.name).resolve()
        self.gate = self.common / "gate"
        self.gate.mkdir()
        _write_workspace(self.gate, b"fixture", gate=True)
        self.reference = self.common / "reference"
        self.reference.mkdir()
        self.original_lock = self._lock_fixture()
        _write_workspace(self.reference, self.original_lock, gate=False)
        symlink = self.reference / "codex-rs/link"
        symlink.symlink_to("cli/Cargo.toml")
        self.commit = _init_detached_repository(self.reference, tag="rust-v0.147.0")
        self.normalized_lock = self.original_lock.replace(
            b'version = "0.0.0"\n', b'version = "0.147.0"\n'
        )
        self.scratch = self.common / "eval-data/sources" / f"codex-rust-v0.147.0-{self.commit}"
        shutil.copytree(self.reference, self.scratch, ignore=shutil.ignore_patterns(".git"), symlinks=True)
        (self.scratch / "codex-rs/Cargo.lock").write_bytes(self.normalized_lock)
        self.target = (
            self.common
            / "eval-data/build"
            / f"codex-rust-v0.147.0-{self.commit}-{binary_freeze.RUST_TARGET}"
        )
        release = self.target / binary_freeze.RUST_TARGET / "release/codex"
        release.parent.mkdir(parents=True)
        release.write_bytes(b"frozen-baseline-binary")
        release.chmod(0o755)
        self.artifact = (
            self.common
            / "eval-data/bin/codex"
            / f"rust-v0.147.0-{self.commit}-{binary_freeze.RUST_TARGET}"
        )
        self.request = FreezeRequest(
            side=Side.CODEX,
            common_root=self.common,
            source_root=self.scratch,
            source_commit=self.commit,
            target_dir=self.target,
            artifact_dir=self.artifact,
            gate_root=self.gate,
            baseline_reference_root=self.reference,
        )
        self.command = _build_command(
            common=self.common,
            source=self.scratch,
            target=self.target,
            gate=self.gate,
            side=Side.CODEX,
            source_commit=self.commit,
        )
        _write_watchdog_summary(self.common)
        self.stack = ExitStack()
        self.stack.enter_context(
            mock.patch.object(binary_freeze, "_validate_static_musl_binary")
        )
        self.stack.enter_context(mock.patch.object(binary_freeze, "BASELINE_COMMIT", self.commit))
        self.stack.enter_context(
            mock.patch.object(
                binary_freeze,
                "BASELINE_LOCK_SHA256",
                hashlib.sha256(self.original_lock).hexdigest(),
            )
        )
        self.stack.enter_context(
            mock.patch.object(
                binary_freeze,
                "NORMALIZED_LOCK_SHA256",
                hashlib.sha256(self.normalized_lock).hexdigest(),
            )
        )

    def tearDown(self) -> None:
        self.stack.close()
        self.temporary.cleanup()

    @staticmethod
    def _lock_fixture() -> bytes:
        parts = [b"version = 4\n"]
        for index in range(135):
            parts.append(
                f'\n[[package]]\nname = "workspace-{index}"\nversion = "0.0.0"\n'.encode()
            )
        return b"".join(parts)

    def test_exact_135_normalization_and_only_lock_delta_are_accepted(self) -> None:
        prepared = prepare(
            self.request,
            self.command,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )
        manifest = json.loads(Path(prepared.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["workspace_lock_normalization"], binary_freeze.LOCK_NORMALIZATION)
        verify(
            self.request,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )
        (self.scratch / "codex-rs/cli/src/main.rs").write_text("fn changed() {}\n", encoding="utf-8")
        with self.assertRaises(BinaryFreezeError):
            verify(
                self.request,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )

    def test_exports_exact_normalized_tree_atomically_without_overwrite(self) -> None:
        shutil.rmtree(self.scratch)
        exported = export_baseline(
            common_root=self.common,
            baseline_reference_root=self.reference,
            source_commit=self.commit,
            scratch_dir=self.scratch,
            lease_factory=_lease_factory,
        )
        self.assertEqual(exported.scratch_path, str(self.scratch))
        self.assertEqual((self.scratch / "codex-rs/Cargo.lock").read_bytes(), self.normalized_lock)
        self.assertTrue((self.scratch / "codex-rs/link").is_symlink())
        with self.assertRaises(BinaryFreezeError):
            export_baseline(
                common_root=self.common,
                baseline_reference_root=self.reference,
                source_commit=self.commit,
                scratch_dir=self.scratch,
                lease_factory=_lease_factory,
            )

    def test_rejects_nonmechanical_lock_change(self) -> None:
        lock = self.scratch / "codex-rs/Cargo.lock"
        lock.write_bytes(self.normalized_lock + b"# extra\n")
        with self.assertRaises(BinaryFreezeError):
            prepare(
                self.request,
                self.command,
                lease_factory=_lease_factory,
                toolchain_probe=lambda: TOOLCHAIN,
            )

    def test_companion_keeps_exact_baseline_normalization(self) -> None:
        prepare(
            self.request,
            self.command,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )
        host_release = (
            self.target / binary_freeze.RUST_TARGET / "release/codex-code-mode-host"
        )
        host_release.write_bytes(b"frozen-baseline-code-mode-host")
        host_release.chmod(0o755)
        bundle = self.artifact.with_name(f"{self.artifact.name}-code-mode-bundle")
        companion = CompanionFreezeRequest(
            side=Side.CODEX,
            common_root=self.common,
            source_root=self.scratch,
            source_commit=self.commit,
            target_dir=self.target,
            legacy_artifact_dir=self.artifact,
            bundle_dir=bundle,
            gate_root=self.gate,
            baseline_reference_root=self.reference,
        )
        host_command = _build_command(
            common=self.common,
            source=self.scratch,
            target=self.target,
            gate=self.gate,
            side=Side.CODEX,
            source_commit=self.commit,
            package="codex-code-mode-host",
            binary="codex-code-mode-host",
            baseline_reference=self.reference,
        )

        prepare_companion(
            companion,
            host_command,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )
        verified = verify_companion(
            companion,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )

        manifest = json.loads(Path(verified.manifest_path).read_text(encoding="utf-8"))
        self.assertEqual(manifest["workspace_lock_normalization"], binary_freeze.LOCK_NORMALIZATION)
        bwrap_release = self.target / binary_freeze.RUST_TARGET / "release/bwrap"
        bwrap_release.write_bytes(b"frozen-baseline-bwrap")
        bwrap_release.chmod(0o755)
        libcap = _write_libcap_dependency(self.common)
        runtime = self.artifact.with_name(f"{self.artifact.name}-runtime-bundle")
        runtime_request = RuntimeFreezeRequest(
            side=Side.CODEX,
            common_root=self.common,
            source_root=self.scratch,
            source_commit=self.commit,
            target_dir=self.target,
            companion_bundle_dir=bundle,
            libcap_dir=libcap,
            runtime_bundle_dir=runtime,
            gate_root=self.gate,
            baseline_reference_root=self.reference,
        )
        bwrap_command = _bwrap_build_command(
            common=self.common,
            source=self.scratch,
            target=self.target,
            gate=self.gate,
            side=Side.CODEX,
            libcap=libcap,
        )
        prepare_runtime(
            runtime_request,
            bwrap_command,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )
        runtime_verified = verify_runtime(
            runtime_request,
            lease_factory=_lease_factory,
            toolchain_probe=lambda: TOOLCHAIN,
        )
        runtime_manifest = json.loads(
            Path(runtime_verified.manifest_path).read_text(encoding="utf-8")
        )
        self.assertEqual(
            runtime_manifest["workspace_lock_normalization"], binary_freeze.LOCK_NORMALIZATION
        )


class CleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        GUARD.held = True

    def test_execs_only_exact_codex_target_and_scratch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            common = Path(temporary).resolve()
            commit = "b" * 40
            target = (
                common
                / "eval-data/build"
                / f"codex-rust-v0.147.0-{commit}-{binary_freeze.RUST_TARGET}"
            )
            scratch = common / "eval-data/sources" / f"codex-rust-v0.147.0-{commit}"
            target.mkdir(parents=True)
            scratch.mkdir(parents=True)
            executable = common / "rm"
            executable.write_text("fixture", encoding="utf-8")
            executable.chmod(0o755)

            class ExecCalled(Exception):
                pass

            calls: list[tuple[str, list[str]]] = []

            def fake_exec(path: str, argv: list[str]) -> None:
                calls.append((path, argv))
                raise ExecCalled

            with mock.patch.object(binary_freeze, "BASELINE_COMMIT", commit):
                with self.assertRaises(ExecCalled):
                    cleanup(
                        side=Side.CODEX,
                        common_root=common,
                        source_commit=commit,
                        target_dir=target,
                        scratch_dir=scratch,
                        lease_factory=_lease_factory,
                        exec_function=fake_exec,
                        rm_executable=executable,
                    )
            self.assertEqual(calls[0][1], [str(executable), "-rf", "--", str(target), str(scratch)])

    def test_rejects_neighbor_target_and_rondo_scratch(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            common = Path(temporary).resolve()
            commit = "c" * 40
            expected = (
                common
                / "eval-data/build"
                / f"rondo-{commit}-{binary_freeze.RUST_TARGET}"
            )
            neighbor = common / "eval-data/build/not-the-target"
            expected.mkdir(parents=True)
            neighbor.mkdir()
            with self.assertRaises(BinaryFreezeError):
                cleanup(
                    side=Side.RONDO,
                    common_root=common,
                    source_commit=commit,
                    target_dir=neighbor,
                    lease_factory=_lease_factory,
                )
            with self.assertRaises(BinaryFreezeError):
                cleanup(
                    side=Side.RONDO,
                    common_root=common,
                    source_commit=commit,
                    target_dir=expected,
                    scratch_dir=neighbor,
                    lease_factory=_lease_factory,
                )


class StaticBinaryValidationTests(unittest.TestCase):
    def test_accepts_static_x86_64_and_rejects_dynamic_loader_dependencies(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            binary = Path(temporary) / "codex"
            binary.write_bytes(b"fixture")
            static = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=(
                    "Class: ELF64\n"
                    "Machine: Advanced Micro Devices X86-64\n"
                    "Program Headers:\n  LOAD 0x0\n"
                    "There is no dynamic section in this file.\n"
                ),
                stderr="",
            )
            with mock.patch.object(binary_freeze.subprocess, "run", return_value=static):
                binary_freeze._validate_static_musl_binary(binary)

            dynamic = subprocess.CompletedProcess(
                args=[],
                returncode=0,
                stdout=static.stdout + " INTERP 0x1\n (NEEDED) Shared library: [libc.so.6]\n",
                stderr="",
            )
            with mock.patch.object(binary_freeze.subprocess, "run", return_value=dynamic):
                with self.assertRaises(BinaryFreezeError):
                    binary_freeze._validate_static_musl_binary(binary)


class SourceV8ResolverTests(unittest.TestCase):
    def test_import_disables_bytecode_writes_temporarily_and_restores_flag(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            scripts = Path(temporary).resolve()
            package = scripts / "codex_package"
            package.mkdir()
            targets_file = package / "targets.py"
            v8_file = package / "v8.py"
            targets_file.write_text("# fixture\n", encoding="utf-8")
            v8_file.write_text("# fixture\n", encoding="utf-8")
            target_specs: dict[str, object] = {}
            fetch = lambda *_args, **_kwargs: None
            version = lambda: "fixture"
            modules = {
                "codex_package.targets": SimpleNamespace(
                    __file__=str(targets_file), TARGET_SPECS=target_specs
                ),
                "codex_package.v8": SimpleNamespace(
                    __file__=str(v8_file),
                    fetch_codex_v8_artifacts=fetch,
                    resolved_v8_crate_version=version,
                ),
            }
            observed: list[bool] = []

            def fake_import(name: str) -> object:
                observed.append(binary_freeze.sys.dont_write_bytecode)
                return modules[name]

            original = binary_freeze.sys.dont_write_bytecode
            binary_freeze.sys.dont_write_bytecode = False
            try:
                with mock.patch.object(
                    binary_freeze.importlib, "import_module", side_effect=fake_import
                ):
                    loaded = binary_freeze._load_source_v8_resolver(scripts)
                self.assertEqual(observed, [True, True])
                self.assertFalse(binary_freeze.sys.dont_write_bytecode)
                self.assertEqual(loaded, (target_specs, fetch, version))
                self.assertFalse((package / "__pycache__").exists())
            finally:
                binary_freeze.sys.dont_write_bytecode = original


if __name__ == "__main__":
    unittest.main()
