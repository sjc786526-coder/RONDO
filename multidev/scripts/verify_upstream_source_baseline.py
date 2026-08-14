#!/usr/bin/env python3
"""Verify RONDO's pinned upstream Codex source during a baseline upgrade."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path


def fail(message: str) -> None:
    raise SystemExit(f"verify_upstream_source_baseline: {message}")


def git(
    snapshot: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(snapshot), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    args = parser.parse_args()

    mydev_root = Path(__file__).resolve().parents[1]
    repository_root = mydev_root.parent
    baseline_path = mydev_root / "codex-rs/core/upstream-source-baseline.toml"
    with baseline_path.open("rb") as handle:
        baseline = tomllib.load(handle)

    if set(baseline) != {"schema_version", "tag", "peeled_commit"}:
        fail(
            "baseline manifest must contain only schema_version, tag, and peeled_commit"
        )
    if baseline["schema_version"] != 1:
        fail("unsupported baseline manifest schema")
    tag = baseline["tag"]
    peeled_commit = baseline["peeled_commit"]
    if (
        not isinstance(tag, str)
        or re.fullmatch(r"rust-v[0-9]+\.[0-9]+\.[0-9]+", tag) is None
    ):
        fail("tag must use the rust-v<major>.<minor>.<patch> form")
    if (
        not isinstance(peeled_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", peeled_commit) is None
    ):
        fail("peeled_commit must be 40 lowercase hexadecimal characters")

    with (mydev_root / "codex-rs/Cargo.toml").open("rb") as handle:
        workspace = tomllib.load(handle)
    if tag != f"rust-v{workspace['workspace']['package']['version']}":
        fail("baseline tag does not match the imported workspace version")

    snapshot = args.snapshot.resolve(strict=True)
    actual_commit = git(snapshot, "rev-parse", f"{tag}^{{}}").stdout.strip()
    if actual_commit != peeled_commit:
        fail(f"{tag} peels to {actual_commit}, expected {peeled_commit}")
    if git(snapshot, "rev-parse", "HEAD").stdout.strip() != peeled_commit:
        fail("snapshot HEAD does not match peeled_commit")
    if git(snapshot, "symbolic-ref", "-q", "HEAD", check=False).returncode == 0:
        fail("snapshot must be detached")
    if git(snapshot, "status", "--porcelain").stdout:
        fail("snapshot worktree is not clean")

    manifest_reference = "mydev/codex-rs/core/upstream-source-baseline.toml"
    for relative_path in ["doc/WBS.md", "doc/development-environment.md"]:
        text = (repository_root / relative_path).read_text(encoding="utf-8")
        for expected in [manifest_reference, tag, peeled_commit]:
            if expected not in text:
                fail(f"{relative_path} does not reference {expected}")

    print(f"verified {tag} -> {peeled_commit} against {snapshot}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
