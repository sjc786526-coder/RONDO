"""Deterministic, ID-only Terminal-Bench 2.1 task partitions."""

from __future__ import annotations

import hashlib
import json
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
_LEGACY_CANARY_CATALOG = Path("eval/tasksets/p2-b7-canary-catalog.json")
_SUCCESSOR_CANARY_CATALOG = Path("eval/tasksets/p2-b7-canary-catalog-v2.json")
_TASK_ID = re.compile(r"terminal-bench/[a-z0-9][a-z0-9.-]{0,95}")
_MAX_DATASET_BYTES = 1_000_000
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_IMAGE_TAG = re.compile(r"[a-z0-9][a-z0-9._/-]{0,127}:[A-Za-z0-9._-]{1,64}")
_IMAGE_REF = re.compile(
    r"(?P<repository>[a-z0-9][a-z0-9._/-]{0,127})@(?P<digest>sha256:[0-9a-f]{64})"
)
_WORKDIR = re.compile(r"/[A-Za-z0-9._/-]{0,255}")


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


@dataclass(frozen=True)
class FrozenTask:
    task_id: str
    source_digest: str
    image_tag: str
    image_ref: str
    workdir: str
    memory_mb: int
    timeout_seconds: int
    agent_timeout_seconds: int
    verifier_timeout_seconds: int
    build_timeout_seconds: int
    requires_existing_git_repo: bool = False
    pids_limit: int = 256

    @property
    def slug(self) -> str:
        return self.task_id.split("/", maxsplit=1)[1]

    @property
    def image_digest(self) -> str:
        return self.image_ref.rsplit("@", maxsplit=1)[1]

    def validate(self) -> None:
        image_match = _IMAGE_REF.fullmatch(self.image_ref)
        if (
            _TASK_ID.fullmatch(self.task_id) is None
            or _SHA256.fullmatch(self.source_digest) is None
            or _IMAGE_TAG.fullmatch(self.image_tag) is None
            or image_match is None
            or self.image_tag.rsplit(":", maxsplit=1)[0]
            != image_match.group("repository")
            or _WORKDIR.fullmatch(self.workdir) is None
            or self.workdir == "/"
            or self.memory_mb not in {2048, 8192}
            or self.timeout_seconds != 1800
            or self.agent_timeout_seconds not in {900, 1800}
            or self.verifier_timeout_seconds != self.agent_timeout_seconds
            or self.build_timeout_seconds != 600
            or not isinstance(self.requires_existing_git_repo, bool)
            or self.pids_limit not in {256, 512}
        ):
            raise TasksetError("frozen canary task is invalid")


@dataclass(frozen=True)
class FrozenCanaryCatalog:
    terminal_bench_commit: str
    taskset_sha256: str
    tasks: tuple[FrozenTask, ...]
    catalog_sha256: str

    def task(self, task_id: str) -> FrozenTask:
        matches = tuple(item for item in self.tasks if item.task_id == task_id)
        if len(matches) != 1:
            raise TasksetError("canary task is not uniquely frozen")
        return matches[0]


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


def load_frozen_canary_catalog(
    paths: RepoPaths,
    *,
    expected_sha256: str | None = None,
) -> FrozenCanaryCatalog:
    """Load the B7 execution catalog after validating its ID-only B4 parent."""

    tasksets = load_frozen_tasksets(paths)
    path = _catalog_path(paths, expected_sha256=expected_sha256)
    return _load_frozen_canary_catalog_path(paths, tasksets=tasksets, path=path)


def load_successor_canary_catalog(paths: RepoPaths) -> FrozenCanaryCatalog:
    """Load the current successor policy without changing historical catalogs."""

    tasksets = load_frozen_tasksets(paths)
    return _load_frozen_canary_catalog_path(
        paths,
        tasksets=tasksets,
        path=paths.worktree_root / _SUCCESSOR_CANARY_CATALOG,
    )


def _catalog_path(paths: RepoPaths, *, expected_sha256: str | None) -> Path:
    if expected_sha256 is None:
        return paths.worktree_root / _LEGACY_CANARY_CATALOG
    if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
        raise TasksetError("canary catalog SHA-256 is invalid")
    matches: list[Path] = []
    for relative in (_LEGACY_CANARY_CATALOG, _SUCCESSOR_CANARY_CATALOG):
        path = paths.worktree_root / relative
        raw = _read_regular(path, limit=1_000_000)
        if hashlib.sha256(raw).hexdigest() == expected_sha256:
            matches.append(path)
    if len(matches) != 1:
        raise TasksetError("canary catalog SHA-256 is not uniquely registered")
    return matches[0]


def _load_frozen_canary_catalog_path(
    paths: RepoPaths,
    *,
    tasksets: FrozenTasksets,
    path: Path,
) -> FrozenCanaryCatalog:
    raw = _read_regular(path, limit=1_000_000)
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TasksetError("canary catalog is invalid JSON") from exc
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "terminal_bench_commit",
        "taskset_sha256",
        "tasks",
    }:
        raise TasksetError("canary catalog schema is invalid")
    if (
        value["schema_version"] not in {1, 2}
        or value["terminal_bench_commit"] != TERMINAL_BENCH_COMMIT
        or value["taskset_sha256"] != tasksets.taskset_sha256
        or not isinstance(value["tasks"], list)
    ):
        raise TasksetError("canary catalog identity is invalid")
    expected_keys = {
        "task_id",
        "source_digest",
        "image_tag",
        "image_ref",
        "workdir",
        "memory_mb",
        "timeout_seconds",
        "agent_timeout_seconds",
        "verifier_timeout_seconds",
        "build_timeout_seconds",
        "requires_existing_git_repo",
    }
    if value["schema_version"] == 2:
        expected_keys.add("pids_limit")
    tasks: list[FrozenTask] = []
    for item in value["tasks"]:
        if not isinstance(item, dict) or set(item) != expected_keys:
            raise TasksetError("canary catalog task shape is invalid")
        try:
            task = FrozenTask(**item)
        except TypeError as exc:
            raise TasksetError("canary catalog task types are invalid") from exc
        task.validate()
        tasks.append(task)
    expected_pids = {
        "terminal-bench/filter-js-from-html": 512,
    }
    if value["schema_version"] == 2 and any(
        task.pids_limit != expected_pids.get(task.task_id, 256) for task in tasks
    ):
        raise TasksetError("canary catalog PID policy is invalid")
    if tuple(item.task_id for item in tasks) != tasksets.canary:
        raise TasksetError("canary catalog order differs from the B4 partition")
    return FrozenCanaryCatalog(
        terminal_bench_commit=TERMINAL_BENCH_COMMIT,
        taskset_sha256=tasksets.taskset_sha256,
        tasks=tuple(tasks),
        catalog_sha256=hashlib.sha256(raw).hexdigest(),
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
