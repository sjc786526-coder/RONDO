from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock


EVAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval import binary_freeze  # noqa: E402
from rondo_eval.binary_freeze import (  # noqa: E402
    BinaryFreezeError,
    FreezeRequest,
    cleanup,
    export_baseline,
    prepare,
    verify,
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
) -> tuple[str, ...]:
    manifest = source / ("mydev/codex-rs/Cargo.toml" if side is Side.RONDO else "codex-rs/Cargo.toml")
    return (
        f"cwd={gate}",
        "env",
        "-i",
        f"HOME={os.environ['HOME']}",
        f"PATH={os.environ['PATH']}",
        "LC_ALL=C.UTF-8",
        f"XDG_RUNTIME_DIR=/run/user/{os.getuid()}",
        f"DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/{os.getuid()}/bus",
        f"RONDO_PROJECT_ROOT={common}",
        f"CARGO_TARGET_DIR={target}",
        f"RONDO_BUILD_METRICS_DIR={common}/eval-data/build-metrics/test",
        str(gate / "mydev/scripts/with-build-lock.sh"),
        "rustup",
        "run",
        "1.95.0",
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


if __name__ == "__main__":
    unittest.main()
