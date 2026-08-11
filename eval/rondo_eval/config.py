"""Repository-root runtime configuration and strict secret loading."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import tomllib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .contracts import BinaryManifest, ModelPricing, ProviderProjection, RunSpec, Side


_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_PROFILE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_CONFIG_KEYS: dict[str, Any] = {
    "providers": {
        "deepseek": {"api", "base_url", "api_key_env", "model"},
        "qwen": {"api", "region", "base_url", "api_key_env", "model"},
    },
    "paid_eval": {
        "active_provider",
        "main_model",
        "guardian_model",
        "guardian_reasoning_effort",
        "max_attempts",
        "retry_backoff_seconds",
        "providers",
        "models",
    },
    "local_model": {
        "runtime",
        "api",
        "base_url",
        "api_key_env",
        "model_id",
        "model_path",
        "model_sha256",
        "format",
        "quantization",
        "server",
        "request",
    },
}
_PAID_PROVIDER_KEYS = {
    "display_name",
    "api",
    "base_url",
    "api_key_env",
    "unbilled_retry_statuses",
}
_PAID_MODEL_KEYS = {
    "model_id",
    "input_usd_per_million",
    "cached_input_usd_per_million",
    "output_usd_per_million",
    "long_context_threshold_tokens",
    "long_context_input_multiplier",
    "long_context_output_multiplier",
    "cache_write_input_multiplier",
    "price_snapshot_date",
    "price_source_url",
}
_REASONING_EFFORTS = {"none", "low", "medium", "high", "xhigh", "max"}
_MAX_PAID_PROFILES = 16
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
        """Return an existing non-paid provider without changing its schema."""

        providers = self.data.get("providers")
        if not isinstance(providers, dict) or not isinstance(providers.get(name), dict):
            raise ConfigError(f"provider {name!r} is not configured")
        return dict(providers[name])

    def paid_eval(self) -> dict[str, Any]:
        value = self.data.get("paid_eval")
        if not isinstance(value, dict):
            raise ConfigError("paid_eval is not configured")
        return dict(value)

    def active_provider_name(self) -> str:
        value = self.paid_eval().get("active_provider")
        if not isinstance(value, str):
            raise ConfigError("paid_eval active provider is invalid")
        return value

    def paid_provider(self, name: str | None = None) -> dict[str, Any]:
        active = self.active_provider_name()
        if name is not None and name != active:
            raise ConfigError("explicit provider differs from paid_eval.active_provider")
        providers = self.paid_eval().get("providers")
        if not isinstance(providers, dict) or not isinstance(
            providers.get(active), dict
        ):
            raise ConfigError(f"paid eval provider {active!r} is not configured")
        return dict(providers[active])

    def paid_model(self, name: str) -> dict[str, Any]:
        models = self.paid_eval().get("models")
        if not isinstance(models, dict) or not isinstance(models.get(name), dict):
            raise ConfigError(f"paid eval model {name!r} is not configured")
        return dict(models[name])

    def paid_provider_projection(self, name: str | None = None) -> ProviderProjection:
        return _resolve_paid_provider_projection(self, provider_name=name)

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
    allowed = _allowed_secret_names(paths.worktree_root / "rondo.secrets.example.env")
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
    provider_name: str | None = None,
    timeout_seconds: int = 1800,
    max_retries: int = 0,
    budget_usd: float = 5.0,
) -> RunSpec:
    """Create the only production RunSpec projection from rondo.local.toml."""

    projection = config.paid_provider_projection(provider_name)
    spec = RunSpec(
        side=side,
        batch_id=batch_id,
        task_id=task_id,
        task_image_digest=task_image_digest,
        binary=binary,
        terminal_bench_version=terminal_bench_version,
        provider=projection,
        sandbox_network_access=True,
        code_mode_host=True,
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
        budget_usd=budget_usd,
    )
    try:
        spec.validate()
    except ValueError as exc:
        raise ConfigError("rondo.local.toml does not satisfy the frozen RunSpec contract") from exc
    return spec


def load_provider_secret(
    config: RuntimeConfig, provider_name: str | None = None
) -> tuple[str, str]:
    provider = config.paid_provider(provider_name)
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
            config.paths.worktree_root / "rondo.secrets.example.env"
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
            config.paths.worktree_root / "rondo.secrets.example.env"
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

    _validate_paid_eval_schema(value.get("paid_eval"))

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
    paid_eval = value.get("paid_eval", {})
    paid_providers = paid_eval.get("providers", {}) if isinstance(paid_eval, dict) else {}
    if isinstance(paid_providers, dict):
        for provider in paid_providers.values():
            if isinstance(provider, dict):
                yield provider
    providers = value.get("providers", {})
    if isinstance(providers, dict):
        for provider in providers.values():
            if isinstance(provider, dict):
                yield provider
    local_model = value.get("local_model")
    if isinstance(local_model, dict):
        yield local_model


def _validate_paid_eval_schema(value: object) -> None:
    if not isinstance(value, dict) or set(value) != _CONFIG_KEYS["paid_eval"]:
        raise ConfigError("paid_eval does not match the supported schema")
    for key in ("active_provider", "main_model", "guardian_model"):
        selected = value.get(key)
        if not isinstance(selected, str) or not _PROFILE_NAME.fullmatch(selected):
            raise ConfigError(f"paid_eval {key} is invalid")
    effort = value.get("guardian_reasoning_effort")
    if not isinstance(effort, str) or effort not in _REASONING_EFFORTS:
        raise ConfigError("paid_eval guardian reasoning effort is invalid")
    attempts = value.get("max_attempts")
    if isinstance(attempts, bool) or not isinstance(attempts, int) or not 1 <= attempts <= 5:
        raise ConfigError("paid_eval max_attempts must be an integer from 1 through 5")
    backoff = value.get("retry_backoff_seconds")
    if (
        isinstance(backoff, bool)
        or not isinstance(backoff, (int, float))
        or not math.isfinite(backoff)
        or not 0 <= backoff <= 30
    ):
        raise ConfigError("paid_eval retry_backoff_seconds must be from 0 through 30")

    paid_providers = value.get("providers")
    if (
        not isinstance(paid_providers, dict)
        or not paid_providers
        or len(paid_providers) > _MAX_PAID_PROFILES
    ):
        raise ConfigError("paid_eval providers must contain 1 through 16 profiles")
    for alias, provider in paid_providers.items():
        if not isinstance(alias, str) or not _PROFILE_NAME.fullmatch(alias):
            raise ConfigError("paid_eval provider alias is invalid")
        _validate_paid_provider(provider)
    if value["active_provider"] not in paid_providers:
        raise ConfigError("paid_eval active_provider is not configured")

    models = value.get("models")
    if not isinstance(models, dict) or not models or len(models) > _MAX_PAID_PROFILES:
        raise ConfigError("paid_eval models must contain 1 through 16 profiles")
    model_ids: set[str] = set()
    for alias, model in models.items():
        if not isinstance(alias, str) or not _PROFILE_NAME.fullmatch(alias):
            raise ConfigError("paid_eval model alias is invalid")
        pricing = _model_pricing(model)
        try:
            pricing.validate()
        except ValueError as exc:
            raise ConfigError("paid_eval model profile is invalid") from exc
        if pricing.model_id in model_ids:
            raise ConfigError("paid_eval model ids must be unique")
        model_ids.add(pricing.model_id)
    if value["main_model"] not in models or value["guardian_model"] not in models:
        raise ConfigError("paid_eval selected model is not configured")

    selected_provider = paid_providers[value["active_provider"]]
    if attempts > 1 and not selected_provider["unbilled_retry_statuses"]:
        raise ConfigError("multiple paid_eval attempts require retryable HTTP statuses")


def _validate_paid_provider(value: object) -> None:
    if not isinstance(value, dict) or set(value) != _PAID_PROVIDER_KEYS:
        raise ConfigError("paid_eval provider does not match the supported schema")
    display_name = value.get("display_name")
    if (
        not isinstance(display_name, str)
        or display_name != display_name.strip()
        or not 1 <= len(display_name) <= 128
        or any(ord(character) < 0x20 for character in display_name)
    ):
        raise ConfigError("paid_eval provider display_name is invalid")
    if value.get("api") != "responses":
        raise ConfigError("paid_eval provider must use the Responses API")
    base_url = value.get("base_url")
    if (
        not isinstance(base_url, str)
        or not base_url
        or base_url != base_url.strip()
        or any(ord(character) < 0x20 or character == "\\" for character in base_url)
    ):
        raise ConfigError("paid_eval provider base_url is invalid")
    try:
        parsed = urlsplit(base_url)
        parsed.port
    except ValueError as exc:
        raise ConfigError("paid_eval provider base_url is invalid") from exc
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ConfigError("paid_eval provider requires a credential-free HTTPS base_url")
    env_name = value.get("api_key_env")
    if not isinstance(env_name, str) or not _ENV_NAME.fullmatch(env_name):
        raise ConfigError("paid_eval provider api_key_env is invalid")
    statuses = value.get("unbilled_retry_statuses")
    if (
        not isinstance(statuses, list)
        or any(
            isinstance(status, bool)
            or not isinstance(status, int)
            or not 400 <= status <= 599
            for status in statuses
        )
        or len(statuses) != len(set(statuses))
    ):
        raise ConfigError("paid_eval unbilled retry statuses are invalid")


def _model_pricing(value: object) -> ModelPricing:
    if not isinstance(value, dict) or set(value) != _PAID_MODEL_KEYS:
        raise ConfigError("paid_eval model does not match the supported schema")
    prices: list[Decimal] = []
    for key in (
        "input_usd_per_million",
        "cached_input_usd_per_million",
        "output_usd_per_million",
        "long_context_input_multiplier",
        "long_context_output_multiplier",
        "cache_write_input_multiplier",
    ):
        raw = value.get(key)
        if not isinstance(raw, str) or raw != raw.strip() or not raw:
            raise ConfigError("paid_eval model prices must be Decimal strings")
        try:
            prices.append(Decimal(raw))
        except InvalidOperation as exc:
            raise ConfigError("paid_eval model prices must be Decimal strings") from exc
    threshold = value.get("long_context_threshold_tokens")
    if isinstance(threshold, bool) or not isinstance(threshold, int):
        raise ConfigError("paid_eval long-context threshold must be an integer")
    return ModelPricing(
        model_id=value.get("model_id"),
        input_usd_per_million=prices[0],
        cached_input_usd_per_million=prices[1],
        output_usd_per_million=prices[2],
        long_context_threshold_tokens=threshold,
        long_context_input_multiplier=prices[3],
        long_context_output_multiplier=prices[4],
        cache_write_input_multiplier=prices[5],
        price_snapshot_date=value.get("price_snapshot_date"),
        price_source_url=value.get("price_source_url"),
    )


def _resolve_paid_provider_projection(
    config: RuntimeConfig, *, provider_name: str | None
) -> ProviderProjection:
    paid_eval = config.paid_eval()
    active_provider = config.active_provider_name()
    provider = config.paid_provider(provider_name)
    main_alias = paid_eval["main_model"]
    guardian_alias = paid_eval["guardian_model"]
    main_pricing = _model_pricing(config.paid_model(main_alias))
    guardian_pricing = _model_pricing(config.paid_model(guardian_alias))
    statuses = tuple(sorted(provider["unbilled_retry_statuses"]))
    canonical = {
        "active_provider": active_provider,
        "provider": {
            "display_name": provider["display_name"],
            "api": provider["api"],
            "base_url": provider["base_url"],
            "api_key_env": provider["api_key_env"],
            "unbilled_retry_statuses": list(statuses),
        },
        "main_model_alias": main_alias,
        "main_model": main_pricing.to_dict(),
        "guardian_model_alias": guardian_alias,
        "guardian_model": guardian_pricing.to_dict(),
        "guardian_reasoning_effort": paid_eval["guardian_reasoning_effort"],
        "max_attempts": paid_eval["max_attempts"],
        "retry_backoff_seconds": format(
            Decimal(str(paid_eval["retry_backoff_seconds"])).normalize(), "f"
        ),
    }
    encoded = json.dumps(
        canonical, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    projection = ProviderProjection(
        provider_id=active_provider,
        display_name=provider["display_name"],
        api=provider["api"],
        base_url=provider["base_url"],
        api_key_env=provider["api_key_env"],
        main_model=main_pricing.model_id,
        guardian_model=guardian_pricing.model_id,
        guardian_effort=paid_eval["guardian_reasoning_effort"],
        main_pricing=main_pricing,
        guardian_pricing=guardian_pricing,
        max_attempts=paid_eval["max_attempts"],
        retry_backoff_seconds=float(paid_eval["retry_backoff_seconds"]),
        unbilled_retry_statuses=statuses,
        profile_sha256=hashlib.sha256(encoded).hexdigest(),
        config_sha256=config.source_sha256,
    )
    try:
        projection.validate()
    except ValueError as exc:
        raise ConfigError("paid_eval profile does not satisfy the RunSpec contract") from exc
    return projection
