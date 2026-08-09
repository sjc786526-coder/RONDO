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


_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_EVAL_PROVIDER_ID = "rondo_eval_openai"


class AdapterError(RuntimeError):
    """Raised before or during an agent run when its frozen contract is unsafe."""


class UploadBinaryAdapter(HarborCodexAgent):
    """Reuse Harbor's Codex result parser but replace both install and run.

    Harbor 0.20.0 dynamically constructs import-path agents as
    ``Agent(logs_dir=..., model_name=..., **agent_kwargs)``.  Every constructor
    argument below is non-secret and is projected onto ``--agent-kwarg`` by the
    unified runner.  Compose reads the provider key only from the Harbor process
    environment and exposes it as a mounted secret, never an argv value.
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
    _REMOTE_CODEX_HOME = PurePosixPath("/tmp/rondo-eval-codex-home")
    _REMOTE_CODEX_SECRETS_DIR = PurePosixPath("/tmp/rondo-eval-codex-secrets")

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
        binary_source_commit: str,
        binary_source_dirty: bool,
        binary_rust_toolchain: str,
        binary_build_command: list[str] | tuple[str, ...],
        binary_code_mode_host_build_command: list[str] | tuple[str, ...],
        binary_bwrap_build_command: list[str] | tuple[str, ...],
        binary_workspace_lock_normalization: str | None,
        provider_base_url: str,
        provider_api_key_env: str,
        guardian_model: str,
        guardian_effort: str,
        extra_env: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        for name, command in (
            ("binary_build_command", binary_build_command),
            ("binary_code_mode_host_build_command", binary_code_mode_host_build_command),
            ("binary_bwrap_build_command", binary_bwrap_build_command),
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
            source_commit=binary_source_commit,
            source_dirty=binary_source_dirty,
            rust_toolchain=binary_rust_toolchain,
            build_command=tuple(binary_build_command),
            code_mode_host_build_command=tuple(binary_code_mode_host_build_command),
            bwrap_build_command=tuple(binary_bwrap_build_command),
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
        if guardian_model != "gpt-5.6-luna" or guardian_effort != "low":
            raise AdapterError("guardian projection differs from the frozen P1 contract")

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
        self._guardian_model = guardian_model
        self._guardian_effort = guardian_effort

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

    def get_version_command(self) -> str:
        return f"{shlex.quote(self.remote_path)} --version"

    def validate_local_binary(self) -> None:
        _verify_local_binary(Path(self.manifest.path), self.manifest.sha256)
        _verify_local_binary(
            Path(self.manifest.code_mode_host_path),
            self.manifest.code_mode_host_sha256,
        )
        _verify_local_binary(Path(self.manifest.bwrap_path), self.manifest.bwrap_sha256)

    async def install(self, environment: EnvironmentLike) -> None:
        source = Path(self.manifest.path)
        code_mode_host_source = Path(self.manifest.code_mode_host_path)
        bwrap_source = Path(self.manifest.bwrap_path)
        self.validate_local_binary()

        await _checked_exec(
            environment,
            f"mkdir -p {shlex.quote(str(self.remote_directory))} "
            f"{shlex.quote(str(PurePosixPath(self.remote_bwrap_path).parent))} && "
            f"chmod 0755 {shlex.quote(str(self.remote_directory))} "
            f"{shlex.quote(str(PurePosixPath(self.remote_bwrap_path).parent))}",
        )
        try:
            await environment.upload_file(source, self.remote_path)
            await environment.upload_file(
                code_mode_host_source,
                self.remote_code_mode_host_path,
            )
            await environment.upload_file(bwrap_source, self.remote_bwrap_path)
        except Exception as exc:
            raise AdapterError("binary bundle upload failed") from exc
        for remote_path, expected_digest in (
            (self.remote_path, self.manifest.sha256),
            (self.remote_code_mode_host_path, self.manifest.code_mode_host_sha256),
            (self.remote_bwrap_path, self.manifest.bwrap_sha256),
        ):
            await _checked_exec(environment, f"chmod 0555 {shlex.quote(remote_path)}")
            result = await _checked_exec(
                environment,
                f"sha256sum -- {shlex.quote(remote_path)}",
            )
            remote_digest = _parse_sha256sum(result, remote_path)
            if remote_digest != expected_digest:
                raise AdapterError("uploaded binary sha256 does not match BinaryManifest")
        await _checked_exec(
            environment,
            f"{shlex.quote(self.remote_path)} --version",
        )

    @with_prompt_template
    async def run(self, instruction, environment, context) -> None:
        del context  # Harbor's Codex parser populates context in populate_context_post_run.
        if not isinstance(instruction, str):
            raise AdapterError("instruction must be text")
        remote_home = self._REMOTE_CODEX_HOME.as_posix()
        remote_secrets = self._REMOTE_CODEX_SECRETS_DIR.as_posix()
        remote_auth = (self._REMOTE_CODEX_SECRETS_DIR / "auth.json").as_posix()
        agent_dir = EnvironmentPaths.agent_dir.as_posix()
        output_path = (EnvironmentPaths.agent_dir / self._OUTPUT_FILENAME).as_posix()
        nonsecret_env = {"CODEX_HOME": remote_home}

        await self.exec_as_agent(
            environment,
            command=(
                f"mkdir -p {shlex.quote(remote_home)} {shlex.quote(remote_secrets)} "
                f"{shlex.quote(agent_dir)}"
            ),
            env=nonsecret_env,
        )

        try:
            # Compose mounts this from the Harbor process environment as a Docker
            # secret.  No environment.exec ``-e KEY=value`` argument is used because
            # Harbor's Docker backend would serialize that value into docker argv.
            auth_command = (
                "set -e; test -s /run/secrets/rondo_eval_provider_api_key; umask 077; "
                "python3 -c 'import json,sys; print(json.dumps({\"OPENAI_API_KEY\":sys.stdin.read()}))' "
                "< /run/secrets/rondo_eval_provider_api_key "
                f"> {shlex.quote(remote_auth)}; "
                f"ln -sf {shlex.quote(remote_auth)} {shlex.quote(remote_home + '/auth.json')}"
            )
            auth_result = await environment.exec(
                auth_command,
                timeout_sec=30,
            )
            try:
                auth_code, _stdout, _stderr = exec_result(auth_result)
            except TypeError as exc:
                raise AdapterError(
                    "credential injection returned an unsupported result"
                ) from exc
            if auth_code != 0:
                raise AdapterError("credential injection failed")

            model = self.model_name.split("/", maxsplit=1)[-1]
            common_overrides = (
                'approvals_reviewer="auto_review"',
                'approval_policy="on-request"',
                'sandbox_mode="workspace-write"',
                "sandbox_workspace_write.network_access=true",
                "features.code_mode_host=true",
                f'model_provider={json.dumps(_EVAL_PROVIDER_ID)}',
                f'model_providers.{_EVAL_PROVIDER_ID}.name="OpenAI"',
                f'model_providers.{_EVAL_PROVIDER_ID}.base_url='
                f'{json.dumps(self._provider_base_url)}',
                f'model_providers.{_EVAL_PROVIDER_ID}.wire_api="responses"',
                f"model_providers.{_EVAL_PROVIDER_ID}.requires_openai_auth=true",
                f"model_providers.{_EVAL_PROVIDER_ID}.supports_websockets=false",
                f"model_providers.{_EVAL_PROVIDER_ID}.request_max_retries=0",
                f"model_providers.{_EVAL_PROVIDER_ID}.stream_max_retries=0",
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
                overrides = common_overrides
            override_args = " ".join(f"-c {shlex.quote(value)}" for value in overrides)
            command = (
                f"set -o pipefail; {shlex.quote(self.remote_path)} exec "
                "--strict-config --ignore-user-config "
                "--skip-git-repo-check "
                f"--model {shlex.quote(model)} --json --enable unified_exec "
                f"{override_args} -- {shlex.quote(instruction)} "
                f"2>&1 </dev/null | tee {shlex.quote(output_path)}"
            )
            _validate_safe_codex_command(command, side=self.side)
            await self.exec_as_agent(environment, command=command, env=nonsecret_env)
        finally:
            # Cleanup is deliberately restricted to the two adapter-owned paths.
            try:
                await self.exec_as_agent(
                    environment,
                    command=(
                        f"rm -rf -- {shlex.quote(remote_secrets)} "
                        f"{shlex.quote(remote_home)}"
                    ),
                    env=nonsecret_env,
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
    guardian_model: str,
    guardian_effort: str,
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
        binary_source_commit=manifest.source_commit,
        binary_source_dirty=manifest.source_dirty,
        binary_rust_toolchain=manifest.rust_toolchain,
        binary_build_command=list(manifest.build_command),
        binary_code_mode_host_build_command=list(manifest.code_mode_host_build_command),
        binary_bwrap_build_command=list(manifest.bwrap_build_command),
        binary_workspace_lock_normalization=manifest.workspace_lock_normalization,
        provider_base_url=provider_base_url,
        provider_api_key_env=provider_api_key_env,
        guardian_model=guardian_model,
        guardian_effort=guardian_effort,
    )


def manifest_agent_kwargs(adapter: UploadBinaryAdapter) -> tuple[tuple[str, str], ...]:
    """Return Harbor-parseable, non-secret constructor kwargs."""

    manifest = adapter.manifest
    return (
        ("binary_path", manifest.path),
        ("binary_sha256", manifest.sha256),
        ("binary_code_mode_host_path", manifest.code_mode_host_path),
        ("binary_code_mode_host_sha256", manifest.code_mode_host_sha256),
        ("binary_bwrap_path", manifest.bwrap_path),
        ("binary_bwrap_sha256", manifest.bwrap_sha256),
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
            "binary_bwrap_build_command",
            json.dumps(list(manifest.bwrap_build_command), separators=(",", ":")),
        ),
        (
            "binary_workspace_lock_normalization",
            json.dumps(manifest.workspace_lock_normalization, separators=(",", ":")),
        ),
        ("provider_base_url", adapter._provider_base_url),
        ("provider_api_key_env", adapter._provider_api_key_env),
        ("guardian_model", adapter._guardian_model),
        ("guardian_effort", adapter._guardian_effort),
    )


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


def _validate_safe_codex_command(command: str, *, side: Side) -> None:
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
    required = (
        'approvals_reviewer="auto_review"',
        'approval_policy="on-request"',
        'sandbox_mode="workspace-write"',
        "sandbox_workspace_write.network_access=true",
        "features.code_mode_host=true",
        'model_provider="rondo_eval_openai"',
        'model_providers.rondo_eval_openai.name="OpenAI"',
        "model_providers.rondo_eval_openai.base_url=",
        'model_providers.rondo_eval_openai.wire_api="responses"',
        "model_providers.rondo_eval_openai.requires_openai_auth=true",
        "model_providers.rondo_eval_openai.supports_websockets=false",
        "model_providers.rondo_eval_openai.request_max_retries=0",
        "model_providers.rondo_eval_openai.stream_max_retries=0",
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
        'auto_review.model="gpt-5.6-luna"',
        'auto_review.reasoning_effort="low"',
        'auto_review.evidence_dir="/logs/agent/guardian-evidence"',
    )
    if side is Side.RONDO and any(value not in command for value in rondo_only):
        raise AdapterError("RONDO Guardian overrides are incomplete")
    if side is Side.CODEX and any(value in command for value in rondo_only):
        raise AdapterError("frozen Codex received unsupported RONDO config fields")


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


async def _checked_exec(environment: EnvironmentLike, command: str):
    try:
        result = await environment.exec(command, timeout_sec=30, user="root")
        code, _stdout, _stderr = exec_result(result)
    except Exception as exc:
        if isinstance(exc, AdapterError):
            raise
        raise AdapterError("container command failed") from exc
    if code != 0:
        raise AdapterError("container command failed")
    return result


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
