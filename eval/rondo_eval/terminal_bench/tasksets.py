"""Deterministic, ID-only Terminal-Bench 2.1 task partitions."""

from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from ..config import RepoPaths


TERMINAL_BENCH_COMMIT = "ffccbe05ee73a9d59518217f294ad711bda39304"
SOURCE_DIRECTORY = "terminal-bench-2-1-ffccbe05"
DATASET_TASKS_SHA256 = "8b7594d8cda7f423a5a487dfe30a83499bb76ab23384f6249484181b947441c2"
HOLDOUT_SHA256 = "c15845e7e277eb02e4fd637bdf26c59883be368797907902c368ba15e078177c"
CANARY_COUNT = 10
VALIDATION_COUNT = 61
HOLDOUT_COUNT = 18
_TASK_ID = re.compile(r"terminal-bench/[a-z0-9][a-z0-9.-]{0,95}")
_MAX_DATASET_BYTES = 1_000_000


class TasksetError(ValueError):
    """Raised when a pinned source or tracked task partition drifts."""


@dataclass(frozen=True)
class FrozenTasksets:
    source_commit: str
    dataset_tasks_sha256: str
    canary: tuple[str, ...]
    validation: tuple[str, ...]
    holdout: tuple[str, ...]

    @property
    def all_ids(self) -> tuple[str, ...]:
        return tuple(sorted((*self.canary, *self.validation, *self.holdout)))

    @property
    def taskset_sha256(self) -> str:
        value = "".join(
            f"{name}\0{task_id}\n"
            for name, values in (
                ("canary", self.canary),
                ("validation", self.validation),
                ("holdout", self.holdout),
            )
            for task_id in values
        )
        return hashlib.sha256(value.encode("utf-8")).hexdigest()


def load_frozen_tasksets(paths: RepoPaths) -> FrozenTasksets:
    """Validate the pinned ID catalog and the three tracked ID-only partitions."""

    source = paths.common_root / "eval-data" / "sources" / SOURCE_DIRECTORY
    if _git_output(source, "rev-parse", "HEAD") != TERMINAL_BENCH_COMMIT:
        raise TasksetError("Terminal-Bench source commit differs from the taskset freeze")
    if _git_output(source, "status", "--short"):
        raise TasksetError("Terminal-Bench source checkout is dirty")
    dataset_ids = _load_dataset_ids(source / "tasks" / "dataset.toml")
    if _digest_ids(dataset_ids) != DATASET_TASKS_SHA256:
        raise TasksetError("Terminal-Bench dataset task IDs differ from the freeze")

    tasksets_root = paths.worktree_root / "eval" / "tasksets"
    canary = _load_id_file(tasksets_root / "canary.txt")
    validation = _load_id_file(tasksets_root / "validation.txt")
    holdout = _load_id_file(tasksets_root / "holdout.txt")
    if (len(canary), len(validation), len(holdout)) != (
        CANARY_COUNT,
        VALIDATION_COUNT,
        HOLDOUT_COUNT,
    ):
        raise TasksetError("taskset partition counts differ from the freeze")
    if len(set(canary) | set(validation) | set(holdout)) != len(dataset_ids):
        raise TasksetError("taskset partitions overlap or omit IDs")
    if tuple(sorted((*canary, *validation, *holdout))) != dataset_ids:
        raise TasksetError("taskset partitions differ from the pinned dataset")

    expected_holdout = tuple(
        sorted(
            sorted(
                dataset_ids,
                key=lambda task_id: (
                    hashlib.sha256(task_id.encode("utf-8")).hexdigest(),
                    task_id,
                ),
            )[: (len(dataset_ids) + 4) // 5]
        )
    )
    if holdout != expected_holdout or _digest_ids(holdout) != HOLDOUT_SHA256:
        raise TasksetError("holdout is not the frozen ID-only SHA-256 partition")
    return FrozenTasksets(
        source_commit=TERMINAL_BENCH_COMMIT,
        dataset_tasks_sha256=DATASET_TASKS_SHA256,
        canary=canary,
        validation=validation,
        holdout=holdout,
    )


def _load_dataset_ids(path: Path) -> tuple[str, ...]:
    value = _read_regular(path, limit=_MAX_DATASET_BYTES)
    try:
        parsed = tomllib.loads(value.decode("utf-8"))
        tasks = parsed["tasks"]
    except (UnicodeDecodeError, tomllib.TOMLDecodeError, KeyError, TypeError) as exc:
        raise TasksetError("pinned dataset.toml is invalid") from exc
    if not isinstance(tasks, list):
        raise TasksetError("pinned dataset task table is invalid")
    ids: list[str] = []
    for item in tasks:
        if not isinstance(item, dict):
            raise TasksetError("pinned dataset task entry is invalid")
        task_id = item.get("name")
        if not isinstance(task_id, str) or _TASK_ID.fullmatch(task_id) is None:
            raise TasksetError("pinned dataset contains an invalid task ID")
        ids.append(task_id)
    if len(ids) != len(set(ids)):
        raise TasksetError("pinned dataset contains duplicate task IDs")
    return tuple(sorted(ids))


def _load_id_file(path: Path) -> tuple[str, ...]:
    try:
        text = _read_regular(path, limit=100_000).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise TasksetError("taskset file is not UTF-8") from exc
    if not text.endswith("\n") or "\r" in text:
        raise TasksetError("taskset file must use canonical LF text")
    values = tuple(text[:-1].split("\n"))
    if not values or any(_TASK_ID.fullmatch(value) is None for value in values):
        raise TasksetError("taskset file contains an invalid task ID")
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise TasksetError("taskset file must be sorted and unique")
    return values


def _read_regular(path: Path, *, limit: int) -> bytes:
    try:
        file_stat = path.lstat()
    except OSError as exc:
        raise TasksetError("taskset input is unavailable") from exc
    if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > limit:
        raise TasksetError("taskset input is unsafe")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
        try:
            value = os.read(descriptor, limit + 1)
        finally:
            os.close(descriptor)
    except OSError as exc:
        raise TasksetError("taskset input cannot be read safely") from exc
    if len(value) != file_stat.st_size or len(value) > limit:
        raise TasksetError("taskset input changed while reading")
    return value


def _digest_ids(values: tuple[str, ...]) -> str:
    return hashlib.sha256(("\n".join(values) + "\n").encode("utf-8")).hexdigest()


def _git_output(root: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ("git", "-C", os.fspath(root), *args),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise TasksetError("pinned Terminal-Bench checkout cannot be verified") from exc
    return completed.stdout.strip()
