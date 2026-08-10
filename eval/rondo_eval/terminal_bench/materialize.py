"""Fail-closed materialization of one pinned Terminal-Bench task."""

from __future__ import annotations

import hashlib
import re
import shutil
import stat
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .freeze import (
    FIX_GIT_IMAGE_DIGEST,
    FIX_GIT_IMAGE_REF,
    FIX_GIT_IMAGE_TAG,
    FIX_GIT_TASK_ARCHIVE_SHA256,
    FIX_GIT_TASK_ID,
    TERMINAL_BENCH_COMMIT,
    TERMINAL_BENCH_REPO_REF,
)


class MaterializationError(RuntimeError):
    """The local dataset checkout or staged task differs from its freeze."""


TERMINAL_BENCH_AGENT_UID = 1000
TERMINAL_BENCH_AGENT_GID = 1000
TERMINAL_BENCH_AGENT_USER = (
    f"{TERMINAL_BENCH_AGENT_UID}:{TERMINAL_BENCH_AGENT_GID}"
)


@dataclass(frozen=True)
class MaterializedTask:
    task_path: Path
    overlay_path: Path
    source_repo_ref: str
    source_commit: str
    source_digest: str
    source_image_tag: str
    runtime_image_ref: str
    task_label: str
    memory_bytes: int
    memory_swap_bytes: int
    pids_limit: int
    provider_api_key_env: str
    runtime_user: str
    staged_task_digest: str
    overlay_sha256: str
    seccomp_profile: Path | None = None
    seccomp_profile_source_sha256: str | None = None
    seccomp_profile_effective_sha256: str | None = None

    def validate(self) -> None:
        if (
            not self.task_path.is_dir()
            or self.task_path.is_symlink()
            or not self.overlay_path.is_file()
            or self.overlay_path.is_symlink()
        ):
            raise MaterializationError("staged task or Compose overlay is unavailable")
        if (
            self.source_repo_ref != TERMINAL_BENCH_REPO_REF
            or self.source_commit != TERMINAL_BENCH_COMMIT
            or self.source_digest != f"sha256:{FIX_GIT_TASK_ARCHIVE_SHA256}"
            or self.source_image_tag != FIX_GIT_IMAGE_TAG
            or self.runtime_image_ref != FIX_GIT_IMAGE_REF
        ):
            raise MaterializationError("staged task provenance differs from the freeze")
        if not self.task_label.startswith("dev.rondo.eval.task="):
            raise MaterializationError("staged task label is invalid")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", self.provider_api_key_env):
            raise MaterializationError("staged provider key variable is invalid")
        if self.runtime_user != TERMINAL_BENCH_AGENT_USER:
            raise MaterializationError("staged task runtime user differs from the freeze")
        if (
            self.memory_bytes <= 0
            or self.memory_swap_bytes < self.memory_bytes
            or self.pids_limit <= 0
        ):
            raise MaterializationError("staged task resource limits are invalid")
        profile_values = (
            self.seccomp_profile,
            self.seccomp_profile_source_sha256,
            self.seccomp_profile_effective_sha256,
        )
        if any(value is not None for value in profile_values):
            if not all(value is not None for value in profile_values):
                raise MaterializationError("staged seccomp profile identity is incomplete")
            assert self.seccomp_profile is not None
            try:
                from .namespace_diagnostic import (
                    _EFFECTIVE_PROFILE_SHA256,
                    _validate_frozen_profile,
                )

                profile_stat = self.seccomp_profile.lstat()
                if (
                    self.seccomp_profile.is_symlink()
                    or not stat.S_ISREG(profile_stat.st_mode)
                    or _file_sha256(self.seccomp_profile)
                    != self.seccomp_profile_source_sha256
                    or self.seccomp_profile_effective_sha256
                    != _EFFECTIVE_PROFILE_SHA256
                ):
                    raise MaterializationError("staged seccomp profile identity differs")
                _validate_frozen_profile(self.seccomp_profile.read_bytes())
            except MaterializationError:
                raise
            except Exception as exc:
                raise MaterializationError("staged seccomp profile is invalid") from exc
        if _harbor_content_digest(self.task_path) != self.staged_task_digest:
            raise MaterializationError("staged task changed after materialization")
        try:
            overlay_text = self.overlay_path.read_text(encoding="utf-8")
        except OSError as exc:
            raise MaterializationError("Compose overlay is unreadable") from exc
        expected_overlay = _compose_overlay_text(
            task_label=self.task_label,
            memory_bytes=self.memory_bytes,
            memory_swap_bytes=self.memory_swap_bytes,
            pids_limit=self.pids_limit,
            provider_api_key_env=self.provider_api_key_env,
            runtime_user=self.runtime_user,
            seccomp_profile=self.seccomp_profile,
            seccomp_profile_source_sha256=self.seccomp_profile_source_sha256,
            seccomp_profile_effective_sha256=self.seccomp_profile_effective_sha256,
        )
        if overlay_text != expected_overlay:
            raise MaterializationError("Compose overlay differs from the frozen contract")
        if _file_sha256(self.overlay_path) != self.overlay_sha256:
            raise MaterializationError("Compose overlay changed after materialization")


class PinnedTaskMaterializer:
    """Copy only fix-git from the pinned checkout and rewrite its image by digest."""

    def materialize(
        self,
        *,
        source_checkout: Path,
        staging_root: Path,
        staging_name: str,
        image_digest: str,
        task_label: str,
        memory_bytes: int,
        memory_swap_bytes: int,
        pids_limit: int,
        provider_api_key_env: str,
        seccomp_profile: Path | None = None,
        seccomp_profile_source_sha256: str | None = None,
        seccomp_profile_effective_sha256: str | None = None,
    ) -> MaterializedTask:
        if image_digest != FIX_GIT_IMAGE_DIGEST:
            raise MaterializationError("runtime image digest is not the B1 freeze")
        _validate_limits(memory_bytes, memory_swap_bytes, pids_limit)
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*", provider_api_key_env):
            raise MaterializationError("provider key variable is invalid")
        source_checkout = _regular_directory(source_checkout, "dataset checkout")
        source_task = _regular_directory(source_checkout / "tasks" / "fix-git", "task")
        dataset_manifest = _regular_file(source_checkout / "tasks" / "dataset.toml")

        if _git(source_checkout, "rev-parse", "HEAD") != TERMINAL_BENCH_COMMIT:
            raise MaterializationError("dataset checkout commit differs from the freeze")
        top = Path(_git(source_checkout, "rev-parse", "--show-toplevel")).resolve()
        if top != source_checkout.resolve():
            raise MaterializationError("dataset checkout is not its Git worktree root")
        scoped_status = _git(
            source_checkout,
            "status",
            "--porcelain=v1",
            "--untracked-files=all",
            "--",
            "tasks/fix-git",
            "tasks/dataset.toml",
        )
        if scoped_status:
            raise MaterializationError("frozen task source or dataset manifest is dirty")
        _reject_symlinks(source_task)

        task_document = _read_toml(source_task / "task.toml")
        _validate_task_metadata(task_document)
        _validate_dataset_manifest(_read_toml(dataset_manifest))
        source_digest = _harbor_content_digest(source_task)
        if source_digest != FIX_GIT_TASK_ARCHIVE_SHA256:
            raise MaterializationError("task content digest differs from dataset.toml")

        staging_root = staging_root.resolve()
        _require_ignored_staging(staging_root)
        if not staging_name or any(
            character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
            for character in staging_name
        ):
            raise MaterializationError("staging name is unsafe")
        destination = staging_root / staging_name
        overlay = staging_root / f"{staging_name}.compose.yaml"
        if destination.exists() or destination.is_symlink() or overlay.exists():
            raise MaterializationError("staging destination already exists")
        staging_root.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_task, destination, symlinks=True)

        task_toml = destination / "task.toml"
        text = task_toml.read_text(encoding="utf-8")
        needle = f'docker_image = "{FIX_GIT_IMAGE_TAG}"'
        replacement = f'docker_image = "{FIX_GIT_IMAGE_REF}"'
        if text.count(needle) != 1:
            raise MaterializationError("task image metadata is missing or ambiguous")
        task_toml.write_text(text.replace(needle, replacement), encoding="utf-8")
        text = task_toml.read_text(encoding="utf-8")
        agent_needle = "[agent]\n"
        if text.count(agent_needle) != 1:
            raise MaterializationError("task agent metadata is missing or ambiguous")
        task_toml.write_text(
            text.replace(
                agent_needle,
                f'{agent_needle}user = "{TERMINAL_BENCH_AGENT_USER}"\n',
            ),
            encoding="utf-8",
        )
        _validate_staged_task(_read_toml(task_toml))

        overlay.write_text(
            _compose_overlay_text(
                task_label=task_label,
                memory_bytes=memory_bytes,
                memory_swap_bytes=memory_swap_bytes,
                pids_limit=pids_limit,
                provider_api_key_env=provider_api_key_env,
                runtime_user=TERMINAL_BENCH_AGENT_USER,
                seccomp_profile=seccomp_profile,
                seccomp_profile_source_sha256=seccomp_profile_source_sha256,
                seccomp_profile_effective_sha256=seccomp_profile_effective_sha256,
            ),
            encoding="utf-8",
        )
        result = MaterializedTask(
            task_path=destination,
            overlay_path=overlay,
            source_repo_ref=TERMINAL_BENCH_REPO_REF,
            source_commit=TERMINAL_BENCH_COMMIT,
            source_digest=f"sha256:{source_digest}",
            source_image_tag=FIX_GIT_IMAGE_TAG,
            runtime_image_ref=FIX_GIT_IMAGE_REF,
            task_label=task_label,
            memory_bytes=memory_bytes,
            memory_swap_bytes=memory_swap_bytes,
            pids_limit=pids_limit,
            provider_api_key_env=provider_api_key_env,
            runtime_user=TERMINAL_BENCH_AGENT_USER,
            staged_task_digest=_harbor_content_digest(destination),
            overlay_sha256=_file_sha256(overlay),
            seccomp_profile=seccomp_profile,
            seccomp_profile_source_sha256=seccomp_profile_source_sha256,
            seccomp_profile_effective_sha256=seccomp_profile_effective_sha256,
        )
        result.validate()
        return result


def _git(checkout: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ("git", "-C", str(checkout), *args),
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MaterializationError("Git source validation failed") from exc
    if result.returncode != 0:
        raise MaterializationError("Git source validation failed")
    return result.stdout.strip()


def _harbor_content_digest(task_path: Path) -> str:
    try:
        from harbor.publisher.packager import Packager

        digest, _files = Packager.compute_content_hash(task_path)
    except Exception as exc:
        raise MaterializationError("Harbor task digest calculation failed") from exc
    if not isinstance(digest, str):
        raise MaterializationError("Harbor task digest calculation failed")
    return digest


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise MaterializationError("staged file digest calculation failed") from exc
    return digest.hexdigest()


def _read_toml(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            document = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise MaterializationError("frozen task metadata is unreadable") from exc
    if not isinstance(document, dict):
        raise MaterializationError("frozen task metadata is invalid")
    return document


def _validate_task_metadata(document: dict) -> None:
    task = document.get("task")
    metadata = document.get("metadata")
    verifier = document.get("verifier")
    agent = document.get("agent")
    environment = document.get("environment")
    expected = (
        document.get("schema_version") == "1.1"
        and isinstance(task, dict)
        and task.get("name") == FIX_GIT_TASK_ID
        and isinstance(metadata, dict)
        and metadata.get("difficulty") == "easy"
        and metadata.get("category") == "software-engineering"
        and metadata.get("expert_time_estimate_min") == 5.0
        and isinstance(verifier, dict)
        and verifier.get("timeout_sec") == 900.0
        and isinstance(agent, dict)
        and agent.get("timeout_sec") == 900.0
        and isinstance(environment, dict)
        and environment.get("docker_image") == FIX_GIT_IMAGE_TAG
        and environment.get("cpus") == 1
        and environment.get("memory_mb") == 2048
        and environment.get("storage_mb") == 10240
        and environment.get("gpus") == 0
        and environment.get("allow_internet") is True
    )
    if not expected:
        raise MaterializationError("fix-git task metadata differs from the freeze")


def _validate_staged_task(document: dict) -> None:
    _validate_task_metadata(
        {
            **document,
            "environment": {
                **document.get("environment", {}),
                "docker_image": FIX_GIT_IMAGE_TAG,
            },
        }
    )
    environment = document.get("environment")
    if not isinstance(environment, dict) or environment.get("docker_image") != FIX_GIT_IMAGE_REF:
        raise MaterializationError("staged task did not receive the pinned runtime image")
    agent = document.get("agent")
    if not isinstance(agent, dict) or agent.get("user") != TERMINAL_BENCH_AGENT_USER:
        raise MaterializationError("staged task did not receive the pinned runtime user")


def _validate_dataset_manifest(document: dict) -> None:
    tasks = document.get("tasks")
    matches = [
        item
        for item in tasks if isinstance(item, dict) and item.get("name") == FIX_GIT_TASK_ID
    ] if isinstance(tasks, list) else []
    expected_digest = f"sha256:{FIX_GIT_TASK_ARCHIVE_SHA256}"
    if len(matches) != 1 or matches[0].get("digest") != expected_digest:
        raise MaterializationError("dataset manifest does not uniquely pin fix-git")


def _require_ignored_staging(staging_root: Path) -> None:
    probe = staging_root / ".rondo-ignore-probe"
    try:
        result = subprocess.run(
            ("git", "-C", str(staging_root.parent), "check-ignore", "--no-index", "-q", str(probe)),
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise MaterializationError("cannot verify ignored staging root") from exc
    if result.returncode != 0:
        raise MaterializationError("staging root is not ignored by the RONDO repository")


def _regular_directory(path: Path, label: str) -> Path:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise MaterializationError(f"{label} is unavailable") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        raise MaterializationError(f"{label} must be a regular directory")
    return path


def _regular_file(path: Path) -> Path:
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise MaterializationError("dataset manifest is unavailable") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise MaterializationError("dataset manifest must be a regular file")
    return path


def _reject_symlinks(root: Path) -> None:
    try:
        for path in root.rglob("*"):
            if path.is_symlink():
                raise MaterializationError("frozen task contains a symlink")
    except OSError as exc:
        raise MaterializationError("frozen task tree is unreadable") from exc


def _validate_limits(memory: int, swap: int, pids: int) -> None:
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (memory, swap, pids)):
        raise MaterializationError("resource limits must be integers")
    if memory <= 0 or swap < memory or pids <= 0:
        raise MaterializationError("resource limits are invalid")


def _split_label(value: str) -> tuple[str, str]:
    if value.count("=") != 1:
        raise MaterializationError("task label is invalid")
    key, label_value = value.split("=", maxsplit=1)
    if key != "dev.rondo.eval.task" or not label_value or any(
        char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-"
        for char in label_value
    ):
        raise MaterializationError("task label is invalid")
    return key, label_value


def _compose_overlay_text(
    *,
    task_label: str,
    memory_bytes: int,
    memory_swap_bytes: int,
    pids_limit: int,
    provider_api_key_env: str,
    runtime_user: str,
    seccomp_profile: Path | None = None,
    seccomp_profile_source_sha256: str | None = None,
    seccomp_profile_effective_sha256: str | None = None,
) -> str:
    if runtime_user != TERMINAL_BENCH_AGENT_USER:
        raise MaterializationError("runtime user differs from the freeze")
    label_key, label_value = _split_label(task_label)
    seccomp = ""
    values = (
        seccomp_profile,
        seccomp_profile_source_sha256,
        seccomp_profile_effective_sha256,
    )
    if any(value is not None for value in values):
        if (
            not all(value is not None for value in values)
            or not isinstance(seccomp_profile, Path)
            or not seccomp_profile.is_absolute()
            or not re.fullmatch(r"[0-9a-f]{64}", seccomp_profile_source_sha256 or "")
            or not re.fullmatch(r"[0-9a-f]{64}", seccomp_profile_effective_sha256 or "")
        ):
            raise MaterializationError("seccomp profile projection is incomplete")
        seccomp = (
            "    security_opt:\n"
            '      - "no-new-privileges=true"\n'
            f'      - "seccomp={seccomp_profile}"\n'
        )
    return (
        "secrets:\n"
        "  rondo_eval_provider_api_key:\n"
        f"    environment: {provider_api_key_env}\n"
        "services:\n"
        "  main:\n"
        f'    user: "{runtime_user}"\n'
        "    labels:\n"
        f"      {label_key}: {label_value}\n"
        f"    mem_limit: {memory_bytes}\n"
        f"    memswap_limit: {memory_swap_bytes}\n"
        f"    pids_limit: {pids_limit}\n"
        f"{seccomp}"
        "    secrets:\n"
        "      - source: rondo_eval_provider_api_key\n"
        "        target: rondo_eval_provider_api_key\n"
        "        mode: \"0400\"\n"
    )
