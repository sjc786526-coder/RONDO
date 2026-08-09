"""Small Harbor compatibility surface used by adapters and standard-library tests.

Harbor is deliberately optional at import time.  Production environments may supply
its ``BaseEnvironment``; no-API tests use a duck-typed fake with the same two methods.
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any, Protocol


try:
    # Verified against Harbor 0.20.0.  Subclassing Codex deliberately retains its
    # output/trajectory parser, while RONDO overrides the unsafe install/run methods.
    from harbor.agents.installed.base import with_prompt_template
    from harbor.agents.installed.codex import Codex as HarborCodexAgent
    from harbor.models.trial.paths import EnvironmentPaths
except ModuleNotFoundError as exc:
    if exc.name is not None and not (
        exc.name == "harbor" or exc.name.startswith("harbor.")
    ):
        raise

    def with_prompt_template(function):  # type: ignore[no-redef]
        return function

    class HarborCodexAgent:  # type: ignore[no-redef]
        """Import-only fallback for standard-library contract tests."""

        SUPPORTS_ATIF = True
        SUPPORTS_RESUME = False

        def __init__(
            self,
            logs_dir: Path,
            model_name: str | None = None,
            *,
            extra_env: dict[str, str] | None = None,
            version: str | None = None,
            **_kwargs: Any,
        ) -> None:
            self.logs_dir = Path(logs_dir)
            self.model_name = model_name
            self._extra_env = dict(extra_env or {})
            self._version = version

        def _get_env(self, key: str) -> str | None:
            import os

            return self._extra_env.get(key, os.environ.get(key))

        async def exec_as_agent(self, environment, *, command, env=None, **kwargs):
            return await environment.exec(command, env=env, **kwargs)

        async def exec_as_root(self, environment, *, command, env=None, **kwargs):
            return await environment.exec(command, env=env, user="root", **kwargs)

    class EnvironmentPaths:  # type: ignore[no-redef]
        agent_dir = PurePosixPath("/logs/agent")



class EnvironmentLike(Protocol):
    async def upload_file(self, local_path: Any, remote_path: str) -> Any: ...

    async def exec(
        self,
        command: str,
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_sec: int | None = None,
        user: str | None = None,
    ) -> Any: ...


def exec_result(result: Any) -> tuple[int, str, str]:
    """Normalize the stable subset used from Harbor and lightweight fakes."""

    code = getattr(result, "return_code", getattr(result, "exit_code", None))
    stdout = getattr(result, "stdout", None)
    stderr = getattr(result, "stderr", None)
    # Harbor 0.20's real ExecResult models both streams as optional and uses
    # None for a successful command with no output.
    if stdout is None:
        stdout = ""
    if stderr is None:
        stderr = ""
    if (
        isinstance(code, bool)
        or not isinstance(code, int)
        or not isinstance(stdout, str)
        or not isinstance(stderr, str)
    ):
        raise TypeError("environment exec returned an unsupported result")
    return code, stdout, stderr
