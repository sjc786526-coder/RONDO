#!/usr/bin/env python3

import hashlib
import os
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from codex_package.targets import TARGET_SPECS
from codex_package.targets import TargetSpec
from codex_package.v8 import fetch_codex_v8_artifacts
from codex_package.v8 import resolved_v8_crate_version


def parse_command(argv: list[str]) -> list[str]:
    if not argv or argv[0] != "--" or len(argv) == 1:
        raise RuntimeError("usage: with_codex_v8_artifacts.py -- <command> [args...]")
    return argv[1:]


def parse_rustc_host(output: str) -> TargetSpec:
    hosts = [
        line.removeprefix("host:").strip()
        for line in output.splitlines()
        if line.startswith("host:")
    ]
    if len(hosts) != 1:
        raise RuntimeError(
            f"Expected exactly one host in `rustc -vV`, found {len(hosts)}."
        )

    host = hosts[0]
    spec = TARGET_SPECS.get(host)
    if spec is None:
        supported = ", ".join(sorted(TARGET_SPECS))
        raise RuntimeError(
            f"Unsupported rustc host target {host}. Supported targets: {supported}"
        )
    return spec


def source_build_requested(environ: Mapping[str, str]) -> bool:
    return "V8_FROM_SOURCE" in environ


def child_environment(
    environ: Mapping[str, str], archive: Path, binding: Path
) -> dict[str, str]:
    child_env = dict(environ)
    child_env["RUSTY_V8_ARCHIVE"] = str(archive)
    child_env["RUSTY_V8_SRC_BINDING_PATH"] = str(binding)
    return child_env


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as artifact:
        for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def rustc_host() -> TargetSpec:
    completed = subprocess.run(
        ["rustc", "-vV"],
        check=True,
        capture_output=True,
        text=True,
    )
    return parse_rustc_host(completed.stdout)


def main(argv: list[str]) -> int:
    try:
        command = parse_command(argv)
        if source_build_requested(os.environ):
            raise RuntimeError(
                "V8_FROM_SOURCE is set; the local Codex V8 artifact gate refuses source builds."
            )

        spec = rustc_host()
        version = resolved_v8_crate_version()
        ambient_overrides = any(
            name in os.environ
            for name in ["RUSTY_V8_ARCHIVE", "RUSTY_V8_SRC_BINDING_PATH"]
        )
        fetch_started_at_ns = time.time_ns()
        artifacts = fetch_codex_v8_artifacts(spec, version=version)
        cache_status = (
            "hit"
            if artifacts.archive.stat().st_mtime_ns < fetch_started_at_ns
            and artifacts.binding.stat().st_mtime_ns < fetch_started_at_ns
            else "downloaded_or_refreshed"
        )

        print(f"[rondo-v8] crate_version={version}", file=sys.stderr)
        print(f"[rondo-v8] target={spec.target}", file=sys.stderr)
        print(f"[rondo-v8] cache_status={cache_status}", file=sys.stderr)
        print(f"[rondo-v8] archive={artifacts.archive}", file=sys.stderr)
        print(
            f"[rondo-v8] archive_sha256={sha256_file(artifacts.archive)}",
            file=sys.stderr,
        )
        print(f"[rondo-v8] binding={artifacts.binding}", file=sys.stderr)
        print(
            f"[rondo-v8] binding_sha256={sha256_file(artifacts.binding)}",
            file=sys.stderr,
        )
        print(
            f"[rondo-v8] ambient_overrides_replaced={str(ambient_overrides).lower()}",
            file=sys.stderr,
            flush=True,
        )

        os.execvpe(
            command[0],
            command,
            child_environment(os.environ, artifacts.archive, artifacts.binding),
        )
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"[rondo-v8] error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
