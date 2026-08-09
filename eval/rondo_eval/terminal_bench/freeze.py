"""First-party Terminal-Bench/Harbor facts frozen for the P1 smoke task."""

from __future__ import annotations

import re


class FreezeError(ValueError):
    """Raised when a run differs from the researched Terminal-Bench freeze."""


HARBOR_PACKAGE = "harbor"
HARBOR_VERSION = "0.20.0"
HARBOR_REQUIREMENT = f"{HARBOR_PACKAGE}=={HARBOR_VERSION}"
HARBOR_RELEASE_COMMIT = "459ff6ec99417589b7f679d14ddf3b3f0ae4f1dc"
HARBOR_WHEEL_SHA256 = "4b7e48223aea2384cdb8c9eff35eaebd482fc9b1ec09f8193a121c47356ff19a"

TERMINAL_BENCH_DATASET_ID = "terminal-bench/terminal-bench-2-1"
TERMINAL_BENCH_REPOSITORY = "harbor-framework/terminal-bench-2-1"
TERMINAL_BENCH_COMMIT = "ffccbe05ee73a9d59518217f294ad711bda39304"
TERMINAL_BENCH_REPO_REF = f"{TERMINAL_BENCH_REPOSITORY}@{TERMINAL_BENCH_COMMIT}"
TERMINAL_BENCH_VERSION = f"{TERMINAL_BENCH_DATASET_ID}@{TERMINAL_BENCH_COMMIT}"

FIX_GIT_TASK_ID = "terminal-bench/fix-git"
FIX_GIT_TASK_ARCHIVE_SHA256 = "16948b980df9d96de616a205f5acca1c5d395de83ff4f8ffabcafacb93226f2e"
FIX_GIT_IMAGE_REPOSITORY = "alexgshaw/fix-git"
# Research provenance only. It must never be projected into a RunSpec or run command.
FIX_GIT_IMAGE_TAG = f"{FIX_GIT_IMAGE_REPOSITORY}:20260403"
FIX_GIT_IMAGE_DIGEST = (
    "sha256:389b9c8247610c2c5be080b1ac00429007c2c69bf57f7f26c79f0f75ba2d5c74"
)
FIX_GIT_IMAGE_REF = f"{FIX_GIT_IMAGE_REPOSITORY}@{FIX_GIT_IMAGE_DIGEST}"

_SHA256 = re.compile(r"sha256:[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"[0-9a-f]{40}\Z")


def validate_freeze() -> None:
    """Fail closed if a checked-in first-party fact is malformed or inconsistent."""

    if HARBOR_REQUIREMENT != "harbor==0.20.0":
        raise FreezeError("Harbor requirement differs from the frozen release")
    if not _COMMIT.fullmatch(HARBOR_RELEASE_COMMIT):
        raise FreezeError("Harbor release commit is not a lowercase 40-character commit")
    if not _COMMIT.fullmatch(TERMINAL_BENCH_COMMIT):
        raise FreezeError("Terminal-Bench commit is not a lowercase 40-character commit")
    if TERMINAL_BENCH_REPO_REF != (
        f"harbor-framework/terminal-bench-2-1@{TERMINAL_BENCH_COMMIT}"
    ):
        raise FreezeError("Terminal-Bench repository reference is not commit-pinned")
    for value, label in (
        (f"sha256:{HARBOR_WHEEL_SHA256}", "Harbor wheel"),
        (f"sha256:{FIX_GIT_TASK_ARCHIVE_SHA256}", "fix-git task archive"),
    ):
        if not _SHA256.fullmatch(value):
            raise FreezeError(f"{label} digest is malformed")
    if FIX_GIT_TASK_ID != "terminal-bench/fix-git":
        raise FreezeError("the P1 task differs from the frozen fix-git task")
    if FIX_GIT_IMAGE_TAG != "alexgshaw/fix-git:20260403":
        raise FreezeError("fix-git research image tag differs from the task metadata")
    if not _SHA256.fullmatch(FIX_GIT_IMAGE_DIGEST):
        raise FreezeError("fix-git runtime image digest is malformed")
    if FIX_GIT_IMAGE_REF != f"{FIX_GIT_IMAGE_REPOSITORY}@{FIX_GIT_IMAGE_DIGEST}":
        raise FreezeError("fix-git runtime image reference is inconsistent")


def validate_runtime_image_digest(value: str) -> str:
    """Return the B1-proven linux/amd64 digest and reject every other value."""

    if value != FIX_GIT_IMAGE_DIGEST:
        raise FreezeError("runtime image differs from the supervised B1 image digest")
    return value


def pinned_image_ref(digest: str) -> str:
    return f"{FIX_GIT_IMAGE_REPOSITORY}@{validate_runtime_image_digest(digest)}"


validate_freeze()
