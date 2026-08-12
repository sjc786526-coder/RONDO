"""Minimal container preparation for frozen fix-git solution and verifier."""

from __future__ import annotations

import shlex
from pathlib import PurePosixPath

from .compat import EnvironmentLike, exec_result


FIX_GIT_WORKDIR = "/app/personal-site"
_APT_DIRS = (
    "/var/lib/apt/lists/partial",
    "/var/lib/apt/lists/auxfiles",
    "/var/cache/apt/archives/partial",
)
_ALLOWED_APT_OWNERS = {"0:0": "root", "42:0": "_apt"}


class VerifierRuntimeError(RuntimeError):
    """The pinned container cannot run its frozen solution or verifier."""


async def prepare_fix_git_workdir(environment: EnvironmentLike) -> None:
    await prepare_task_workdir(environment, FIX_GIT_WORKDIR)


async def prepare_task_workdir(
    environment: EnvironmentLike,
    task_workdir: str,
) -> None:
    if (
        not isinstance(task_workdir, str)
        or not task_workdir.startswith("/")
        or task_workdir == "/"
        or PurePosixPath(task_workdir).as_posix() != task_workdir
        or any(character in task_workdir for character in ("\x00", "\n", "\r"))
    ):
        raise VerifierRuntimeError("task workdir is invalid")
    result = await environment.exec(
        (
            "set -e; task_workdir=$(pwd -P); "
            f"test \"$task_workdir\" = {shlex.quote(task_workdir)}; "
            'test -d "$task_workdir"; test ! -L "$task_workdir"; '
            'chmod -R a+rwX -- "$task_workdir"'
        ),
        timeout_sec=30,
        user="root",
    )
    _require_success(result, "task workdir preparation failed")


async def prepare_verifier_apt_dirs(environment: EnvironmentLike) -> None:
    for path in _APT_DIRS:
        ensured = await environment.exec(
            (
                f"set -e; test ! -L {path}; mkdir -p -- {path}; "
                f"test -d {path}"
            ),
            timeout_sec=30,
            user="root",
        )
        _require_success(ensured, "verifier apt directory preparation failed")
        inspected = await environment.exec(
            f"stat -c '%u:%g' -- {path}",
            timeout_sec=30,
            user="root",
        )
        code, stdout, _stderr = _normalize(inspected)
        owner = stdout.strip()
        if code != 0 or owner not in _ALLOWED_APT_OWNERS:
            raise VerifierRuntimeError("verifier apt directory identity differs")
        prepared = await environment.exec(
            f"chmod 0777 -- {path}",
            timeout_sec=30,
            user=_ALLOWED_APT_OWNERS[owner],
        )
        _require_success(prepared, "verifier apt directory preparation failed")


def _normalize(result: object) -> tuple[int, str, str]:
    try:
        return exec_result(result)
    except TypeError as exc:
        raise VerifierRuntimeError("container preparation returned invalid evidence") from exc


def _require_success(result: object, message: str) -> None:
    code, _stdout, _stderr = _normalize(result)
    if code != 0:
        raise VerifierRuntimeError(message)
