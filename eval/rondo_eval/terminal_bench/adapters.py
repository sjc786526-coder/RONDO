"""Harbor 0.20.0 Codex adapters for exact local binaries and safe execution."""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import stat
from pathlib import Path, PurePosixPath
from typing import Any, ClassVar
from urllib.parse import urlsplit

from ..contracts import BinaryManifest, ContractError, Side
from .compat import (
    EnvironmentLike,
    EnvironmentPaths,
    HarborCodexAgent,
    exec_result,
    with_prompt_template,
)
from .materialize import TERMINAL_BENCH_AGENT_USER
from .verifier_runtime import VerifierRuntimeError, prepare_verifier_apt_dirs


_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_EVAL_PROVIDER_ID = "rondo_eval_provider"
_REASONING_EFFORTS = {"none", "low", "medium", "high", "xhigh", "max"}
FIX_GIT_CANONICAL_WORKDIR = "/app/personal-site"


class AdapterError(RuntimeError):
    """Raised before or during an agent run when its frozen contract is unsafe."""

    def __init__(
        self,
        message: str,
        *,
        stage: str | None = None,
        command_id: str | None = None,
        stderr_summary: str | None = None,
    ) -> None:
        super().__init__(message)
        self.stage = stage
        self.command_id = command_id
        self.stderr_summary = stderr_summary


class UploadBinaryAdapter(HarborCodexAgent):
    """Reuse Harbor's Codex result parser but replace both install and run.

    Harbor 0.20.0 dynamically constructs import-path agents as
    ``Agent(logs_dir=..., model_name=..., **agent_kwargs)``.  Every constructor
    argument below is non-secret and is projected onto ``--agent-kwarg`` by the
    unified runner.  Compose reads the provider key only from the private staging
    file and exposes it as a mounted secret, never an argv or Harbor environment
    value.
    """

    side: ClassVar[Side]
    adapter_name: ClassVar[str]
    remote_filename: ClassVar[str]
    remote_directory: ClassVar[PurePosixPath] = PurePosixPath("/opt/rondo-eval/bin")
    remote_code_mode_host_filename: ClassVar[str] = "codex-code-mode-host"
    remote_bwrap_relative_path: ClassVar[PurePosixPath] = PurePosixPath(
        "codex-resources/bwrap"
    )
    agent_version: ClassVar[str] = "0.147.0"
    # This is part of Harbor 0.20's Codex result-parser contract.  Declare it
    # locally as well so the adapter does not depend on an untyped/private base
    # attribute that is absent from the lightweight compatibility test double.
    _OUTPUT_FILENAME: ClassVar[str] = "codex.txt"
    _STDERR_FILENAME: ClassVar[str] = "codex.stderr.txt"
    _REMOTE_CODEX_HOME = PurePosixPath("/tmp/rondo-eval-codex-home")
    _REMOTE_CODEX_SECRETS_DIR = PurePosixPath("/tmp/rondo-eval-codex-secrets")
    _REMOTE_FROZEN_MODEL_CATALOG = PurePosixPath(
        "/opt/rondo-eval/bin/frozen-model-catalog.json"
    )

    def __init__(
        self,
        logs_dir: Path,
        model_name: str | None,
        *,
        binary_path: str,
        binary_sha256: str,
        binary_code_mode_host_path: str,
        binary_code_mode_host_sha256: str,
        binary_bwrap_path: str,
        binary_bwrap_sha256: str,
        binary_bwrap_asset_url: str,
        binary_bwrap_archive_sha256: str,
        binary_bwrap_source_tree_sha256: str,
        binary_source_commit: str,
        binary_source_dirty: bool,
        binary_rust_toolchain: str,
        binary_build_command: list[str] | tuple[str, ...],
        binary_code_mode_host_build_command: list[str] | tuple[str, ...],
        binary_workspace_lock_normalization: str | None,
        provider_base_url: str,
        provider_api_key_env: str,
        main_effort: str,
        guardian_model: str,
        guardian_effort: str,
        frozen_model_catalog_path: str | None = None,
        frozen_model_catalog_sha256: str | None = None,
        frozen_model_catalog_source_commit: str | None = None,
        extra_env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        for name, command in (
            ("binary_build_command", binary_build_command),
            ("binary_code_mode_host_build_command", binary_code_mode_host_build_command),
        ):
            if not isinstance(command, (list, tuple)) or not command or not all(
                isinstance(value, str) and value for value in command
            ):
                raise AdapterError(f"{name} must be a non-empty string list")
        manifest = BinaryManifest(
            path=binary_path,
            sha256=binary_sha256,
            code_mode_host_path=binary_code_mode_host_path,
            code_mode_host_sha256=binary_code_mode_host_sha256,
            bwrap_path=binary_bwrap_path,
            bwrap_sha256=binary_bwrap_sha256,
            bwrap_asset_url=binary_bwrap_asset_url,
            bwrap_archive_sha256=binary_bwrap_archive_sha256,
            bwrap_source_tree_sha256=binary_bwrap_source_tree_sha256,
            source_commit=binary_source_commit,
            source_dirty=binary_source_dirty,
            rust_toolchain=binary_rust_toolchain,
            build_command=tuple(binary_build_command),
            code_mode_host_build_command=tuple(binary_code_mode_host_build_command),
            workspace_lock_normalization=binary_workspace_lock_normalization,
        )
        try:
            manifest.validate()
        except ContractError as exc:
            raise AdapterError("binary manifest is invalid") from exc
        if not isinstance(model_name, str) or not _MODEL_NAME.fullmatch(
            model_name.split("/", maxsplit=1)[-1]
        ):
            raise AdapterError("model_name is required and unsafe")
        _validate_provider_inputs(provider_base_url, provider_api_key_env)
        if main_effort not in _REASONING_EFFORTS:
            raise AdapterError("main reasoning effort is unsupported")
        if not _MODEL_NAME.fullmatch(guardian_model):
            raise AdapterError("guardian model is required and unsafe")
        if guardian_effort not in _REASONING_EFFORTS:
            raise AdapterError("guardian reasoning effort is unsupported")
        catalog_values = (
            frozen_model_catalog_path,
            frozen_model_catalog_sha256,
            frozen_model_catalog_source_commit,
        )
        if self.side is Side.RONDO and any(value is not None for value in catalog_values):
            raise AdapterError("RONDO cannot receive a frozen model catalog")
        if any(value is not None for value in catalog_values) and not all(
            isinstance(value, str) and value for value in catalog_values
        ):
            raise AdapterError("frozen model catalog identity is incomplete")
        if frozen_model_catalog_path is not None:
            catalog_path = Path(frozen_model_catalog_path)
            if (
                self.side is not Side.CODEX
                or not catalog_path.is_absolute()
                or frozen_model_catalog_source_commit != manifest.source_commit
                or not isinstance(frozen_model_catalog_sha256, str)
                or not re.fullmatch(r"[0-9a-f]{64}", frozen_model_catalog_sha256)
            ):
                raise AdapterError("frozen model catalog identity is invalid")

        # Harbor supplies logger/mcp_servers/skills_dir through kwargs.  Its base
        # constructor owns these fields and its post-run parser depends on them.
        super().__init__(
            logs_dir=Path(logs_dir),
            model_name=model_name,
            version=self.agent_version,
            extra_env=extra_env,
            **kwargs,
        )
        self._manifest = manifest
        self._provider_base_url = provider_base_url
        self._provider_api_key_env = provider_api_key_env
        self._main_effort = main_effort
        self._guardian_model = guardian_model
        self._guardian_effort = guardian_effort
        self._frozen_model_catalog_path = frozen_model_catalog_path
        self._frozen_model_catalog_sha256 = frozen_model_catalog_sha256
        self._frozen_model_catalog_source_commit = frozen_model_catalog_source_commit

    @property
    def manifest(self) -> BinaryManifest:
        return self._manifest

    @property
    def provider_base_url(self) -> str:
        return self._provider_base_url

    @classmethod
    def name(cls) -> str:
        return cls.adapter_name

    def version(self) -> str:
        return self.agent_version

    @property
    def remote_path(self) -> str:
        return str(self.remote_directory / self.remote_filename)

    @property
    def remote_code_mode_host_path(self) -> str:
        return str(self.remote_directory / self.remote_code_mode_host_filename)

    @property
    def remote_bwrap_path(self) -> str:
        return str(self.remote_directory / self.remote_bwrap_relative_path)

    @property
    def remote_frozen_model_catalog_path(self) -> str:
        return str(self._REMOTE_FROZEN_MODEL_CATALOG)

    def get_version_command(self) -> str:
        return f"{shlex.quote(self.remote_path)} --version"

    def validate_local_binary(self) -> None:
        _verify_local_binary(Path(self.manifest.path), self.manifest.sha256)
        _verify_local_binary(
            Path(self.manifest.code_mode_host_path),
            self.manifest.code_mode_host_sha256,
        )
        _verify_local_binary(Path(self.manifest.bwrap_path), self.manifest.bwrap_sha256)
        if self._frozen_model_catalog_path is not None:
            _verify_local_data_file(
                Path(self._frozen_model_catalog_path),
                self._frozen_model_catalog_sha256 or "",
                expected_mode=0o400,
            )

    async def install(self, environment: EnvironmentLike) -> None:
        source = Path(self.manifest.path)
        code_mode_host_source = Path(self.manifest.code_mode_host_path)
        bwrap_source = Path(self.manifest.bwrap_path)
        self.validate_local_binary()

        try:
            await prepare_verifier_apt_dirs(environment)
        except VerifierRuntimeError:
            raise _diagnostic_error(
                stage="install",
                command_id="prepare_verifier_apt",
                stderr_summary="other_redacted",
            ) from None

        await _checked_exec(
            environment,
            f"mkdir -p {shlex.quote(str(self.remote_directory))} "
            f"{shlex.quote(str(PurePosixPath(self.remote_bwrap_path).parent))} && "
            f"chmod 0755 {shlex.quote(str(self.remote_directory))} "
            f"{shlex.quote(str(PurePosixPath(self.remote_bwrap_path).parent))}",
            stage="install",
            command_id="prepare_bundle_dirs",
        )
        try:
            await environment.upload_file(source, self.remote_path)
            await environment.upload_file(
                code_mode_host_source,
                self.remote_code_mode_host_path,
            )
            await environment.upload_file(bwrap_source, self.remote_bwrap_path)
            if self._frozen_model_catalog_path is not None:
                await environment.upload_file(
                    Path(self._frozen_model_catalog_path),
                    self.remote_frozen_model_catalog_path,
                )
        except Exception:
            raise _diagnostic_error(
                stage="install",
                command_id="upload_bundle",
                stderr_summary="other_redacted",
            ) from None
        directories = (
            str(self.remote_directory),
            str(PurePosixPath(self.remote_bwrap_path).parent),
        )
        files = (
            self.remote_path,
            self.remote_code_mode_host_path,
            self.remote_bwrap_path,
        )
        # The bundle directories are created by root, while Docker Compose cp
        # preserves the frozen host files as the agent user.  With every
        # capability dropped, consume those facts instead of mutating them.
        for remote_path, kind in (
            *((path, "directory") for path in directories),
            *((path, "file") for path in files),
        ):
            quoted = shlex.quote(remote_path)
            type_test = "-d" if kind == "directory" else "-f"
            await _checked_exec(
                environment,
                f"test {type_test} {quoted} && test ! -L {quoted}",
                stage="install",
                command_id=f"verify_{kind}_type",
            )
            ownership = await _checked_exec(
                environment,
                f"stat -c '%u:%g' -- {quoted}",
                stage="install",
                command_id=f"verify_{kind}_owner",
            )
            try:
                _require_ownership(
                    ownership,
                    remote_path,
                    "0:0" if kind == "directory" else TERMINAL_BENCH_AGENT_USER,
                )
            except AdapterError:
                raise _diagnostic_error(
                    stage="install",
                    command_id=f"verify_{kind}_owner",
                    stderr_summary="other_redacted",
                ) from None
            if kind == "file":
                await _checked_exec(
                    environment,
                    f"test \"$(stat -c '%a' -- {quoted})\" = 555",
                    stage="install",
                    command_id="verify_file_mode",
                )
        await _checked_exec(
            environment,
            "chmod 0755 " + " ".join(shlex.quote(path) for path in directories),
            stage="install",
            command_id="set_bundle_dir_modes",
        )
        for remote_path, expected_digest in (
            (self.remote_path, self.manifest.sha256),
            (self.remote_code_mode_host_path, self.manifest.code_mode_host_sha256),
            (self.remote_bwrap_path, self.manifest.bwrap_sha256),
        ):
            result = await _checked_exec(
                environment,
                f"sha256sum -- {shlex.quote(remote_path)}",
                stage="install",
                command_id="verify_bundle_sha256",
            )
            try:
                remote_digest = _parse_sha256sum(result, remote_path)
            except AdapterError:
                raise _diagnostic_error(
                    stage="install",
                    command_id="verify_bundle_sha256",
                    stderr_summary="other_redacted",
                ) from None
            if remote_digest != expected_digest:
                raise _diagnostic_error(
                    stage="install",
                    command_id="verify_bundle_sha256",
                    stderr_summary="other_redacted",
                )
        if self._frozen_model_catalog_path is not None:
            catalog_path = self.remote_frozen_model_catalog_path
            quoted = shlex.quote(catalog_path)
            await _checked_exec(
                environment,
                f'test -f {quoted} && test ! -L {quoted} && '
                f'test "$(stat -c \'%a\' -- {quoted})" = 400',
                stage="install",
                command_id="verify_model_catalog_mode",
            )
            ownership = await _checked_exec(
                environment,
                f"stat -c '%u:%g' -- {quoted}",
                stage="install",
                command_id="verify_model_catalog_owner",
            )
            try:
                _require_ownership(
                    ownership,
                    catalog_path,
                    TERMINAL_BENCH_AGENT_USER,
                )
            except AdapterError:
                raise _diagnostic_error(
                    stage="install",
                    command_id="verify_model_catalog_owner",
                    stderr_summary="other_redacted",
                ) from None
            result = await _checked_exec(
                environment,
                f"sha256sum -- {quoted}",
                stage="install",
                command_id="verify_model_catalog_sha256",
            )
            try:
                remote_digest = _parse_sha256sum(result, catalog_path)
            except AdapterError:
                raise _diagnostic_error(
                    stage="install",
                    command_id="verify_model_catalog_sha256",
                    stderr_summary="other_redacted",
                ) from None
            if remote_digest != self._frozen_model_catalog_sha256:
                raise _diagnostic_error(
                    stage="install",
                    command_id="verify_model_catalog_sha256",
                    stderr_summary="other_redacted",
                )
        await _checked_exec(
            environment,
            f"{shlex.quote(self.remote_path)} --version",
            stage="install",
            command_id="verify_binary_version",
        )

    @with_prompt_template
    async def run(self, instruction, environment, context) -> None:
        del context  # Harbor's Codex parser populates context in populate_context_post_run.
        if not isinstance(instruction, str):
            raise AdapterError("instruction must be text")
        remote_home = self._REMOTE_CODEX_HOME.as_posix()
        remote_secrets = self._REMOTE_CODEX_SECRETS_DIR.as_posix()
        remote_auth = (self._REMOTE_CODEX_SECRETS_DIR / "auth.json").as_posix()
        remote_gitconfig = (self._REMOTE_CODEX_HOME / "gitconfig").as_posix()
        agent_dir = EnvironmentPaths.agent_dir.as_posix()
        output_path = (EnvironmentPaths.agent_dir / self._OUTPUT_FILENAME).as_posix()
        stderr_path = (EnvironmentPaths.agent_dir / self._STDERR_FILENAME).as_posix()
        nonsecret_env = {
            "CODEX_HOME": remote_home,
            "GIT_CONFIG_GLOBAL": remote_gitconfig,
        }

        # Harbor freezes environment.default_user to the task's 1000:1000
        # identity.  Root may only expose the exact current task workdir; all
        # adapter-owned state is created by the agent user itself.  This keeps
        # the path viable under cap_drop=ALL without ownership mutation.
        await _checked_exec(
            environment,
            (
                "set -e; task_workdir=$(pwd -P); "
                f'test "$task_workdir" = "{FIX_GIT_CANONICAL_WORKDIR}"; '
                'test -d "$task_workdir"; '
                'test ! -L "$task_workdir"; '
                'chmod -R a+rwX -- "$task_workdir"'
            ),
            stage="run",
            command_id="project_task_permissions",
        )
        await _checked_exec_as_agent(
            environment,
            command=(
                "set -e; "
                f'test "$(id -u):$(id -g)" = "{TERMINAL_BENCH_AGENT_USER}"; '
                "task_workdir=$(pwd -P); "
                f'test "$task_workdir" = "{FIX_GIT_CANONICAL_WORKDIR}"; '
                'test -d "$task_workdir"; '
                f"mkdir -p {shlex.quote(remote_home)} {shlex.quote(remote_secrets)} "
                f"{shlex.quote(agent_dir)}; "
                f"chmod 0700 {shlex.quote(remote_home)} {shlex.quote(remote_secrets)}; "
                f"chmod 0750 {shlex.quote(agent_dir)}; "
                f"test -O {shlex.quote(remote_home)}; "
                f"test -O {shlex.quote(remote_secrets)}; "
                f"test -O {shlex.quote(agent_dir)}; "
                'test -w "$task_workdir"; '
                'test -d "$task_workdir/.git"; test -w "$task_workdir/.git"; '
                'test -d "$task_workdir/.git/refs"; '
                'test -w "$task_workdir/.git/refs"; '
                'test -d "$task_workdir/.git/logs"; '
                'test -w "$task_workdir/.git/logs"; '
                'test -f "$task_workdir/.git/index"; '
                'test -w "$task_workdir/.git/index"; '
                f": > {shlex.quote(remote_gitconfig)}; "
                f"chmod 0600 {shlex.quote(remote_gitconfig)}; "
                'git config --global --replace-all safe.directory "$task_workdir"; '
                'test "$(git config --global --get-all safe.directory | wc -l)" -eq 1; '
                'test "$(git config --global --get-all safe.directory)" = "$task_workdir"; '
                'test "$(git -C "$task_workdir" rev-parse --is-inside-work-tree)" = true; '
                'git -C "$task_workdir" status --porcelain=v1 --untracked-files=no >/dev/null'
            ),
            env=nonsecret_env,
            stage="run",
            command_id="prepare_agent_and_git",
        )

        try:
            # Compose mounts the private staging file as a Docker secret.  No
            # environment.exec ``-e KEY=value`` argument is used because Harbor's
            # Docker backend would serialize that value into docker argv.
            secret_path = "/run/secrets/rondo_eval_provider_api_key"
            secret_owner = await _checked_exec_as_agent(
                environment,
                command=f"stat -c '%u:%g' -- {shlex.quote(secret_path)}",
                env=nonsecret_env,
                stage="run",
                command_id="inspect_secret_owner",
            )
            try:
                _require_ownership(
                    secret_owner,
                    secret_path,
                    TERMINAL_BENCH_AGENT_USER,
                )
            except AdapterError:
                raise _diagnostic_error(
                    stage="run",
                    command_id="verify_secret_owner",
                    stderr_summary="other_redacted",
                ) from None
            auth_command = (
                f"set -e; test -f {shlex.quote(secret_path)}; "
                f"test ! -L {shlex.quote(secret_path)}; "
                f"test -s {shlex.quote(secret_path)}; "
                f"test -r {shlex.quote(secret_path)}; "
                f"test ! -w {shlex.quote(secret_path)}; umask 077; "
                "python3 -c 'import json,sys; print(json.dumps({\"OPENAI_API_KEY\":sys.stdin.read()}))' "
                f"< {shlex.quote(secret_path)} "
                f"> {shlex.quote(remote_auth)}; "
                f"chmod 0600 {shlex.quote(remote_auth)}; "
                f"ln -sfn {shlex.quote(remote_auth)} "
                f"{shlex.quote(remote_home + '/auth.json')}"
            )
            await _checked_exec_as_agent(
                environment,
                command=auth_command,
                env=nonsecret_env,
                stage="run",
                command_id="write_auth",
            )

            await _checked_exec_as_agent(
                environment,
                command=(
                    f'test "$(id -u):$(id -g)" = "{TERMINAL_BENCH_AGENT_USER}" '
                    f"&& test -r {shlex.quote(remote_auth)} "
                    f"&& test ! -w {shlex.quote(self.remote_path)} "
                    f"&& test ! -w {shlex.quote(self.remote_code_mode_host_path)} "
                    f"&& test ! -w {shlex.quote(self.remote_bwrap_path)}"
                    + (
                        f" && test -r {shlex.quote(self.remote_frozen_model_catalog_path)}"
                        f" && test ! -w {shlex.quote(self.remote_frozen_model_catalog_path)}"
                        if self._frozen_model_catalog_path is not None
                        else ""
                    )
                ),
                env=nonsecret_env,
                stage="run",
                command_id="verify_runtime_access",
            )

            model = self.model_name.split("/", maxsplit=1)[-1]
            common_overrides = (
                'approvals_reviewer="auto_review"',
                'approval_policy="on-request"',
                'sandbox_mode="workspace-write"',
                "sandbox_workspace_write.network_access=true",
                "features.code_mode_host=true",
                f'model_provider={json.dumps(_EVAL_PROVIDER_ID)}',
                f'model_providers.{_EVAL_PROVIDER_ID}.name="Configured Provider"',
                f'model_providers.{_EVAL_PROVIDER_ID}.base_url='
                f'{json.dumps(self._provider_base_url)}',
                f'model_providers.{_EVAL_PROVIDER_ID}.wire_api="responses"',
                f"model_providers.{_EVAL_PROVIDER_ID}.requires_openai_auth=true",
                f"model_providers.{_EVAL_PROVIDER_ID}.supports_websockets=false",
                f"model_providers.{_EVAL_PROVIDER_ID}.request_max_retries=0",
                f"model_providers.{_EVAL_PROVIDER_ID}.stream_max_retries=0",
                f'model_reasoning_effort={json.dumps(self._main_effort)}',
            )
            if self.side is Side.RONDO:
                overrides = (
                    *common_overrides,
                    f'auto_review.model={json.dumps(self._guardian_model)}',
                    f'auto_review.reasoning_effort={json.dumps(self._guardian_effort)}',
                    "auto_review.evidence_dir=\"/logs/agent/guardian-evidence\"",
                )
            else:
                # Frozen Codex v0.147 does not deserialize RONDO's three new
                # auto_review fields.  Its effective Guardian model/effort are
                # verified from the outbound request by the budget proxy.
                overrides = (
                    *common_overrides,
                    *(
                        (
                            "model_catalog_json="
                            f"{json.dumps(self.remote_frozen_model_catalog_path)}",
                        )
                        if self._frozen_model_catalog_path is not None
                        else ()
                    ),
                )
            override_args = " ".join(f"-c {shlex.quote(value)}" for value in overrides)
            command = (
                f"set -o pipefail; {shlex.quote(self.remote_path)} exec "
                "--strict-config --ignore-user-config "
                "--skip-git-repo-check "
                f"--model {shlex.quote(model)} --json --enable unified_exec "
                f"{override_args} -- {shlex.quote(instruction)} "
                f"</dev/null 2>{shlex.quote(stderr_path)} | tee {shlex.quote(output_path)}"
            )
            _validate_safe_codex_command(
                command,
                side=self.side,
                main_effort=self._main_effort,
                guardian_model=self._guardian_model,
                guardian_effort=self._guardian_effort,
                frozen_model_catalog_path=(
                    self.remote_frozen_model_catalog_path
                    if self._frozen_model_catalog_path is not None
                    else None
                ),
            )
            await _checked_exec_as_agent(
                environment,
                command=command,
                env=nonsecret_env,
                stage="run",
                command_id="agent_exec",
                timeout_sec=None,
            )
        finally:
            # Cleanup is deliberately restricted to the two adapter-owned paths.
            try:
                await _checked_exec_as_agent(
                    environment,
                    command=(
                        f"rm -rf -- {shlex.quote(remote_secrets)} "
                        f"{shlex.quote(remote_home)}"
                    ),
                    env=nonsecret_env,
                    stage="run",
                    command_id="cleanup_agent_state",
                )
            except Exception:
                pass


class CodexUploadAdapter(UploadBinaryAdapter):
    side = Side.CODEX
    adapter_name = "rondo-frozen-codex"
    remote_filename = "codex"


class RondoUploadAdapter(UploadBinaryAdapter):
    side = Side.RONDO
    adapter_name = "rondo-under-test"
    remote_filename = "rondo"


def adapter_for(
    side: Side,
    manifest: BinaryManifest,
    *,
    logs_dir: Path,
    model_name: str,
    provider_base_url: str,
    provider_api_key_env: str,
    main_effort: str,
    guardian_model: str,
    guardian_effort: str,
    frozen_model_catalog_path: str | None = None,
    frozen_model_catalog_sha256: str | None = None,
    frozen_model_catalog_source_commit: str | None = None,
) -> UploadBinaryAdapter:
    adapter_type: type[UploadBinaryAdapter]
    if side is Side.CODEX:
        adapter_type = CodexUploadAdapter
    elif side is Side.RONDO:
        adapter_type = RondoUploadAdapter
    else:
        raise AdapterError("unsupported evaluation side")
    return adapter_type(
        logs_dir=logs_dir,
        model_name=model_name,
        binary_path=manifest.path,
        binary_sha256=manifest.sha256,
        binary_code_mode_host_path=manifest.code_mode_host_path,
        binary_code_mode_host_sha256=manifest.code_mode_host_sha256,
        binary_bwrap_path=manifest.bwrap_path,
        binary_bwrap_sha256=manifest.bwrap_sha256,
        binary_bwrap_asset_url=manifest.bwrap_asset_url,
        binary_bwrap_archive_sha256=manifest.bwrap_archive_sha256,
        binary_bwrap_source_tree_sha256=manifest.bwrap_source_tree_sha256,
        binary_source_commit=manifest.source_commit,
        binary_source_dirty=manifest.source_dirty,
        binary_rust_toolchain=manifest.rust_toolchain,
        binary_build_command=list(manifest.build_command),
        binary_code_mode_host_build_command=list(manifest.code_mode_host_build_command),
        binary_workspace_lock_normalization=manifest.workspace_lock_normalization,
        provider_base_url=provider_base_url,
        provider_api_key_env=provider_api_key_env,
        main_effort=main_effort,
        guardian_model=guardian_model,
        guardian_effort=guardian_effort,
        frozen_model_catalog_path=frozen_model_catalog_path,
        frozen_model_catalog_sha256=frozen_model_catalog_sha256,
        frozen_model_catalog_source_commit=frozen_model_catalog_source_commit,
    )


def manifest_agent_kwargs(adapter: UploadBinaryAdapter) -> tuple[tuple[str, str], ...]:
    """Return Harbor-parseable, non-secret constructor kwargs."""

    manifest = adapter.manifest
    values = [
        ("binary_path", manifest.path),
        ("binary_sha256", manifest.sha256),
        ("binary_code_mode_host_path", manifest.code_mode_host_path),
        ("binary_code_mode_host_sha256", manifest.code_mode_host_sha256),
        ("binary_bwrap_path", manifest.bwrap_path),
        ("binary_bwrap_sha256", manifest.bwrap_sha256),
        ("binary_bwrap_asset_url", json.dumps(manifest.bwrap_asset_url)),
        (
            "binary_bwrap_archive_sha256",
            json.dumps(manifest.bwrap_archive_sha256),
        ),
        (
            "binary_bwrap_source_tree_sha256",
            json.dumps(manifest.bwrap_source_tree_sha256),
        ),
        ("binary_source_commit", manifest.source_commit),
        ("binary_source_dirty", json.dumps(manifest.source_dirty)),
        # The frozen toolchain evidence intentionally contains the complete
        # multi-line rustc/cargo verbose output.  Encode it as JSON so Harbor's
        # parse_kwargs reconstructs the exact string without putting literal
        # line breaks into a CLI argument.
        ("binary_rust_toolchain", json.dumps(manifest.rust_toolchain, separators=(",", ":"))),
        ("binary_build_command", json.dumps(list(manifest.build_command), separators=(",", ":"))),
        (
            "binary_code_mode_host_build_command",
            json.dumps(list(manifest.code_mode_host_build_command), separators=(",", ":")),
        ),
        (
            "binary_workspace_lock_normalization",
            json.dumps(manifest.workspace_lock_normalization, separators=(",", ":")),
        ),
        ("provider_base_url", adapter._provider_base_url),
        ("provider_api_key_env", adapter._provider_api_key_env),
        ("main_effort", adapter._main_effort),
        ("guardian_model", adapter._guardian_model),
        ("guardian_effort", adapter._guardian_effort),
    ]
    if adapter._frozen_model_catalog_path is not None:
        values.extend(
            (
                ("frozen_model_catalog_path", adapter._frozen_model_catalog_path),
                (
                    "frozen_model_catalog_sha256",
                    adapter._frozen_model_catalog_sha256 or "",
                ),
                (
                    "frozen_model_catalog_source_commit",
                    adapter._frozen_model_catalog_source_commit or "",
                ),
            )
        )
    return tuple(values)


def _validate_provider_inputs(base_url: str, api_key_env: str) -> None:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise AdapterError("provider_base_url must be a credential-free HTTP URL")
    if not isinstance(api_key_env, str) or not _ENV_NAME.fullmatch(api_key_env):
        raise AdapterError("provider_api_key_env is invalid")


def _validate_safe_codex_command(
    command: str,
    *,
    side: Side,
    main_effort: str,
    guardian_model: str,
    guardian_effort: str,
    frozen_model_catalog_path: str | None = None,
) -> None:
    if not command.startswith("set -o pipefail; "):
        raise AdapterError("Codex output pipeline must preserve the command exit status")
    forbidden = (
        "--dangerously-bypass-approvals-and-sandbox",
        "--yolo",
        "approval_policy=\"never\"",
        "sandbox_mode=\"danger-full-access\"",
        "sandbox_workspace_write.network_access=false",
        "features.code_mode_host=false",
    )
    if any(value in command for value in forbidden):
        raise AdapterError("unsafe Codex execution option was generated")
    if "2>&1" in command or "2>/logs/agent/codex.stderr.txt" not in command:
        raise AdapterError("Codex JSONL output must be isolated from stderr")
    required = (
        'approvals_reviewer="auto_review"',
        'approval_policy="on-request"',
        'sandbox_mode="workspace-write"',
        "sandbox_workspace_write.network_access=true",
        "features.code_mode_host=true",
        'model_provider="rondo_eval_provider"',
        'model_providers.rondo_eval_provider.name="Configured Provider"',
        "model_providers.rondo_eval_provider.base_url=",
        'model_providers.rondo_eval_provider.wire_api="responses"',
        "model_providers.rondo_eval_provider.requires_openai_auth=true",
        "model_providers.rondo_eval_provider.supports_websockets=false",
        "model_providers.rondo_eval_provider.request_max_retries=0",
        "model_providers.rondo_eval_provider.stream_max_retries=0",
        f"model_reasoning_effort={json.dumps(main_effort)}",
    )
    if any(value not in command for value in required):
        raise AdapterError("safe Codex execution options are incomplete")
    if command.count("features.code_mode_host=true") != 1:
        raise AdapterError("code-mode host feature override is ambiguous")
    if command.count("sandbox_workspace_write.network_access=true") != 1:
        raise AdapterError("workspace-write network policy override is ambiguous")
    if "model_providers.openai." in command:
        raise AdapterError("built-in OpenAI provider may not be overridden")
    rondo_only = (
        f"auto_review.model={json.dumps(guardian_model)}",
        f"auto_review.reasoning_effort={json.dumps(guardian_effort)}",
        'auto_review.evidence_dir="/logs/agent/guardian-evidence"',
    )
    if side is Side.RONDO and any(value not in command for value in rondo_only):
        raise AdapterError("RONDO Guardian overrides are incomplete")
    if side is Side.CODEX and any(value in command for value in rondo_only):
        raise AdapterError("frozen Codex received unsupported RONDO config fields")
    catalog_override = (
        f"model_catalog_json={json.dumps(frozen_model_catalog_path)}"
        if frozen_model_catalog_path is not None
        else None
    )
    if side is Side.RONDO and "model_catalog_json=" in command:
        raise AdapterError("RONDO received a frozen model catalog")
    if side is Side.CODEX and catalog_override is not None and catalog_override not in command:
        raise AdapterError("frozen Codex model catalog override is incomplete")
    if side is Side.CODEX and catalog_override is None and "model_catalog_json=" in command:
        raise AdapterError("frozen Codex received an undeclared model catalog")


def _verify_local_binary(path: Path, expected: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise AdapterError("manifest binary is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise AdapterError("manifest binary must be a regular non-symlink file")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise AdapterError("manifest binary cannot be read") from exc
    if digest.hexdigest() != expected:
        raise AdapterError("local binary sha256 does not match BinaryManifest")


def _verify_local_data_file(path: Path, expected: str, *, expected_mode: int) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise AdapterError("local frozen model catalog is unavailable") from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or stat.S_IMODE(metadata.st_mode) != expected_mode
        or metadata.st_size <= 0
        or metadata.st_size > 4 * 1024 * 1024
    ):
        raise AdapterError("local frozen model catalog is unsafe")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise AdapterError("local frozen model catalog is unreadable") from exc
    if digest.hexdigest() != expected:
        raise AdapterError("local frozen model catalog digest differs")


async def _checked_exec(
    environment: EnvironmentLike,
    command: str,
    *,
    stage: str,
    command_id: str,
):
    if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,31}", stage) or not re.fullmatch(
        r"[a-z][a-z0-9_.-]{0,63}", command_id
    ):
        raise AdapterError("container diagnostic identity is invalid")
    try:
        result = await environment.exec(command, timeout_sec=30, user="root")
        code, _stdout, stderr = exec_result(result)
    except Exception:
        stderr_summary = "other_redacted"
        raise _diagnostic_error(
            stage=stage,
            command_id=command_id,
            stderr_summary=stderr_summary,
        ) from None
    if code != 0:
        stderr_summary = _classify_stderr(stderr)
        raise _diagnostic_error(
            stage=stage,
            command_id=command_id,
            stderr_summary=stderr_summary,
        )
    return result


async def _checked_exec_as_agent(
    environment: EnvironmentLike,
    *,
    command: str,
    env: dict[str, str],
    stage: str,
    command_id: str,
    timeout_sec: int | None = 30,
):
    """Execute as Harbor's frozen default user without its raw error renderer."""

    if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,31}", stage) or not re.fullmatch(
        r"[a-z][a-z0-9_.-]{0,63}", command_id
    ):
        raise AdapterError("container diagnostic identity is invalid")
    try:
        shell_command = (
            command
            if command.startswith("set -o pipefail; ")
            else f"set -o pipefail; {command}"
        )
        result = await environment.exec(
            shell_command,
            env=env,
            timeout_sec=timeout_sec,
        )
        code, _stdout, stderr = exec_result(result)
    except Exception as exc:
        raise _diagnostic_error(
            stage=stage,
            command_id=command_id,
            stderr_summary=_classify_stderr(str(exc)),
        ) from None
    if code != 0:
        raise _diagnostic_error(
            stage=stage,
            command_id=command_id,
            stderr_summary=_classify_stderr(stderr),
        )
    return result


def _classify_stderr(stderr: str) -> str:
    if not stderr:
        return "empty"
    lowered = stderr[:4096].casefold()
    if "permission denied" in lowered or "operation not permitted" in lowered:
        return "permission_denied"
    if "not found" in lowered or "no such file" in lowered:
        return "not_found"
    if "timed out" in lowered or "timeout" in lowered:
        return "timeout"
    return "other_redacted"


def _diagnostic_error(
    *, stage: str, command_id: str, stderr_summary: str
) -> AdapterError:
    return AdapterError(
        f"container command failed: stage={stage} command_id={command_id} "
        f"stderr={stderr_summary}",
        stage=stage,
        command_id=command_id,
        stderr_summary=stderr_summary,
    )


def _parse_sha256sum(result: object, expected_path: str) -> str:
    try:
        _code, stdout, _stderr = exec_result(result)
    except TypeError as exc:
        raise AdapterError("sha256 command returned an unsupported result") from exc
    lines = stdout.splitlines()
    if len(lines) != 1:
        raise AdapterError("sha256 command returned malformed output")
    fields = lines[0].split()
    if len(fields) != 2 or fields[1].lstrip("*") != expected_path:
        raise AdapterError("sha256 command returned malformed output")
    digest = fields[0]
    if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise AdapterError("sha256 command returned malformed output")
    return digest


def _require_ownership(
    result: object, expected_path: str, expected_owner: str
) -> None:
    try:
        _code, stdout, _stderr = exec_result(result)
    except TypeError as exc:
        raise AdapterError("container ownership command returned an unsupported result") from exc
    if stdout != f"{expected_owner}\n":
        raise AdapterError(f"container path ownership differs: {expected_path}")
