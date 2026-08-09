"""Repository-root runtime configuration and strict secret loading."""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .contracts import BinaryManifest, ProviderProjection, RunSpec, Side


_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_CONFIG_KEYS: dict[str, Any] = {
    "providers": {
        "openai": {
            "api",
            "base_url",
            "api_key_env",
            "main_model",
            "guardian_model",
            "guardian_reasoning_effort",
        },
        "deepseek": {"api", "base_url", "api_key_env", "model"},
        "qwen": {"api", "region", "base_url", "api_key_env", "model"},
    },
    "local_model": {
        "runtime",
        "api",
        "base_url",
        "api_key_env",
        "model_id",
        "model_path",
        "format",
        "quantization",
        "server",
        "request",
    },
}
_LOCAL_SERVER_KEYS = {
    "binary", "host", "port", "context_size", "gpu_layers", "flash_attention",
    "parallel", "metrics", "slots", "web_ui", "tools",
}
_LOCAL_REQUEST_KEYS = {
    "stream", "temperature", "top_p", "seed", "max_output_tokens",
    "timeout_seconds", "max_retries", "structured_output",
}


class ConfigError(ValueError):
    """Raised without including secret values when local configuration is unsafe."""


@dataclass(frozen=True)
class RepoPaths:
    common_root: Path
    worktree_root: Path

    @classmethod
    def discover(cls, start: Path) -> "RepoPaths":
        start = start.resolve(strict=True)
        common_dir = _git_path(start, "--git-common-dir")
        worktree_root = _git_path(start, "--show-toplevel")
        common_root = common_dir.parent if common_dir.name == ".git" else common_dir
        if not (common_root / ".git").is_dir():
            raise ConfigError("Git common directory does not resolve to the RONDO main root")
        return cls(common_root.resolve(strict=True), worktree_root.resolve(strict=True))


@dataclass(frozen=True)
class RuntimeConfig:
    paths: RepoPaths
    data: dict[str, Any]
    source_sha256: str

    def provider(self, name: str) -> dict[str, Any]:
        providers = self.data.get("providers")
        if not isinstance(providers, dict) or not isinstance(providers.get(name), dict):
            raise ConfigError(f"provider {name!r} is not configured")
        return dict(providers[name])

    def local_model(self) -> dict[str, Any]:
        value = self.data.get("local_model")
        if not isinstance(value, dict):
            raise ConfigError("local_model is not configured")
        return dict(value)


def load_runtime_config(paths: RepoPaths) -> RuntimeConfig:
    path = paths.common_root / "rondo.local.toml"
    _require_regular_file(path, "rondo.local.toml")
    try:
        raw = path.read_bytes()
        data = tomllib.loads(raw.decode("utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError("rondo.local.toml is unreadable or invalid") from exc
    if not isinstance(data, dict):
        raise ConfigError("rondo.local.toml must contain a TOML table")
    _validate_config_schema(data)
    allowed = _allowed_secret_names(paths.common_root / "rondo.secrets.example.env")
    for table in _api_key_env_tables(data):
        name = table.get("api_key_env")
        if not isinstance(name, str) or name not in allowed:
            raise ConfigError("api_key_env is absent from the tracked secret allowlist")
    return RuntimeConfig(paths, data, hashlib.sha256(raw).hexdigest())


def make_run_spec(
    config: RuntimeConfig,
    *,
    side: Side,
    batch_id: str,
    task_id: str,
    task_image_digest: str,
    binary: BinaryManifest,
    terminal_bench_version: str,
    provider_name: str = "openai",
    timeout_seconds: int = 1800,
    max_retries: int = 0,
    budget_usd: float = 5.0,
) -> RunSpec:
    """Create the only production RunSpec projection from rondo.local.toml."""

    provider = config.provider(provider_name)
    required = {
        "api", "base_url", "api_key_env", "main_model", "guardian_model",
        "guardian_reasoning_effort",
    }
    if set(provider) != required or any(not isinstance(provider[key], str) for key in required):
        raise ConfigError("selected provider does not match the frozen RunSpec schema")
    projection = ProviderProjection(
        provider_id=provider_name,
        api=provider["api"],
        base_url=provider["base_url"],
        api_key_env=provider["api_key_env"],
        main_model=provider["main_model"],
        guardian_model=provider["guardian_model"],
        guardian_effort=provider["guardian_reasoning_effort"],
        config_sha256=config.source_sha256,
    )
    spec = RunSpec(
        side=side,
        batch_id=batch_id,
        task_id=task_id,
        task_image_digest=task_image_digest,
        binary=binary,
        terminal_bench_version=terminal_bench_version,
        provider=projection,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        budget_usd=budget_usd,
    )
    try:
        spec.validate()
    except ValueError as exc:
        raise ConfigError("rondo.local.toml does not satisfy the frozen RunSpec contract") from exc
    return spec


def load_provider_secret(config: RuntimeConfig, provider_name: str) -> tuple[str, str]:
    provider = config.provider(provider_name)
    env_name = provider.get("api_key_env")
    if not isinstance(env_name, str):
        raise ConfigError("provider api_key_env is missing")
    return _load_secret_by_name(config, env_name)


def load_local_model_secret(config: RuntimeConfig) -> tuple[str, str] | None:
    env_name = config.local_model().get("api_key_env")
    if env_name is None:
        return None
    if not isinstance(env_name, str):
        raise ConfigError("local_model api_key_env is invalid")
    values = _parse_env_file(
        config.paths.common_root / ".env.local",
        require_mode=True,
        allow_empty=True,
        allowed_names=_allowed_secret_names(
            config.paths.common_root / "rondo.secrets.example.env"
        ),
    )
    value = values.get(env_name)
    return (env_name, value) if value else None


def _load_secret_by_name(config: RuntimeConfig, env_name: str) -> tuple[str, str]:
    values = _parse_env_file(
        config.paths.common_root / ".env.local",
        require_mode=True,
        allow_empty=True,
        allowed_names=_allowed_secret_names(
            config.paths.common_root / "rondo.secrets.example.env"
        ),
    )
    value = values.get(env_name)
    if value is None or not value:
        raise ConfigError(f"required secret {env_name} is missing or empty")
    return env_name, value


def _git_path(start: Path, option: str) -> Path:
    command = ["git", "rev-parse", "--path-format=absolute", option]
    completed = subprocess.run(
        command,
        cwd=start,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    if completed.returncode != 0:
        raise ConfigError("cannot resolve RONDO Git roots")
    value = completed.stdout.strip()
    if not value:
        raise ConfigError("Git returned an empty repository path")
    return Path(value)


def _allowed_secret_names(path: Path) -> set[str]:
    _require_regular_file(path, "secret allowlist")
    values = _parse_env_file(path, require_mode=False, allow_empty=True)
    if not values:
        raise ConfigError("tracked secret allowlist is empty")
    if any(values.values()):
        raise ConfigError("tracked secret allowlist must not contain values")
    return set(values)


def _parse_env_file(
    path: Path,
    *,
    require_mode: bool,
    allow_empty: bool = False,
    allowed_names: set[str] | None = None,
) -> dict[str, str]:
    _require_regular_file(path, ".env.local")
    if require_mode and os.name == "posix" and (path.stat().st_mode & 0o777) != 0o600:
        raise ConfigError(".env.local permissions must be 0600")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ConfigError("environment data file is unreadable or invalid UTF-8") from exc
    values: dict[str, str] = {}
    for number, line in enumerate(lines, start=1):
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ConfigError(f"invalid environment data at line {number}")
        name, value = line.split("=", 1)
        if not _ENV_NAME.fullmatch(name):
            raise ConfigError(f"invalid environment name at line {number}")
        if name in values:
            raise ConfigError(f"duplicate environment name at line {number}")
        if allowed_names is not None and name not in allowed_names:
            raise ConfigError(f"environment name at line {number} is not allowlisted")
        if not allow_empty and not value:
            raise ConfigError(f"empty environment value at line {number}")
        if any(marker in value for marker in ("$(", "${", "`")):
            raise ConfigError(f"shell syntax is forbidden at line {number}")
        values[name] = value
    return values


def _require_regular_file(path: Path, label: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise ConfigError(f"{label} must be a regular file")


def _validate_config_schema(value: dict[str, Any]) -> None:
    unknown_top = set(value) - set(_CONFIG_KEYS)
    if unknown_top:
        raise ConfigError("rondo.local.toml contains unsupported top-level fields")

    providers = value.get("providers", {})
    if not isinstance(providers, dict):
        raise ConfigError("providers must be a TOML table")
    unknown_providers = set(providers) - set(_CONFIG_KEYS["providers"])
    if unknown_providers:
        raise ConfigError("rondo.local.toml contains an unsupported provider")
    for name, provider in providers.items():
        if not isinstance(provider, dict):
            raise ConfigError("provider configuration must be a TOML table")
        if set(provider) - _CONFIG_KEYS["providers"][name]:
            raise ConfigError("provider configuration contains unsupported fields")

    local = value.get("local_model")
    if local is None:
        return
    if not isinstance(local, dict) or set(local) - _CONFIG_KEYS["local_model"]:
        raise ConfigError("local_model contains unsupported fields")
    for key, allowed in (("server", _LOCAL_SERVER_KEYS), ("request", _LOCAL_REQUEST_KEYS)):
        nested = local.get(key)
        if nested is not None and (not isinstance(nested, dict) or set(nested) - allowed):
            raise ConfigError(f"local_model.{key} contains unsupported fields")


def _api_key_env_tables(value: dict[str, Any]):
    providers = value.get("providers", {})
    if isinstance(providers, dict):
        for provider in providers.values():
            if isinstance(provider, dict):
                yield provider
    local_model = value.get("local_model")
    if isinstance(local_model, dict):
        yield local_model
