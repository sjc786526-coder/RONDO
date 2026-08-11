"""Versioned contracts shared by the Terminal-Bench and approval tracks."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit


SCHEMA_VERSION = 1
_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")
_PROFILE_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}\Z")
_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_MAX_RUN_TIMEOUT_SECONDS = 3600
_MAX_RUN_RETRIES = 10
_MAX_RETRY_BACKOFF_SECONDS = 30.0
_MAX_RATE_USD_PER_MILLION = Decimal("1000")
_REASONING_EFFORTS = {"none", "low", "medium", "high", "xhigh", "max"}
_OFFICIAL_PRICE_SOURCE_HOSTS = {"developers.openai.com", "platform.openai.com"}


class ContractError(ValueError):
    """Raised when a versioned evaluation contract is invalid."""


class Side(StrEnum):
    CODEX = "codex"
    RONDO = "rondo"


class RunOutcome(StrEnum):
    COMPLETED = "completed"
    AGENT_FAILED = "agent_failed"
    INFRA_FAILED = "infra_failed"
    BUDGET_STOPPED = "budget_stopped"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class BinaryManifest:
    path: str
    sha256: str
    code_mode_host_path: str
    code_mode_host_sha256: str
    bwrap_path: str
    bwrap_sha256: str
    source_commit: str
    source_dirty: bool
    rust_toolchain: str
    build_command: tuple[str, ...]
    code_mode_host_build_command: tuple[str, ...]
    bwrap_asset_url: str
    bwrap_archive_sha256: str
    bwrap_source_tree_sha256: str
    workspace_lock_normalization: str | None = None

    def validate(self) -> None:
        if not isinstance(self.path, str) or not self.path:
            raise ContractError("binary path is required")
        _require_sha256(self.sha256, "binary sha256")
        if (
            not isinstance(self.code_mode_host_path, str)
            or not self.code_mode_host_path
            or self.code_mode_host_path == self.path
        ):
            raise ContractError("code-mode host path is required and must differ from binary path")
        _require_sha256(self.code_mode_host_sha256, "code-mode host sha256")
        if (
            not isinstance(self.bwrap_path, str)
            or not self.bwrap_path
            or self.bwrap_path in {self.path, self.code_mode_host_path}
        ):
            raise ContractError("bwrap path is required and must differ from other binary paths")
        _require_sha256(self.bwrap_sha256, "bwrap sha256")
        if self.bwrap_asset_url != (
            "https://github.com/openai/codex/releases/download/rust-v0.147.0/"
            "bwrap-x86_64-unknown-linux-musl.tar.gz"
        ):
            raise ContractError("bwrap asset URL differs from the frozen release")
        _require_sha256(self.bwrap_archive_sha256, "bwrap archive sha256")
        _require_sha256(self.bwrap_source_tree_sha256, "bwrap source tree sha256")
        _require_commit(self.source_commit, "binary source commit")
        if not isinstance(self.source_dirty, bool):
            raise ContractError("binary source_dirty must be boolean")
        if (
            not isinstance(self.rust_toolchain, str)
            or not self.rust_toolchain
            or not isinstance(self.build_command, tuple)
            or not self.build_command
            or any(not isinstance(item, str) or not item for item in self.build_command)
            or not isinstance(self.code_mode_host_build_command, tuple)
            or not self.code_mode_host_build_command
            or any(
                not isinstance(item, str) or not item
                for item in self.code_mode_host_build_command
            )
        ):
            raise ContractError("binary toolchain and build commands are required")
        if self.workspace_lock_normalization is not None and (
            not isinstance(self.workspace_lock_normalization, str)
            or not self.workspace_lock_normalization
        ):
            raise ContractError("workspace lock normalization must be non-empty or null")


@dataclass(frozen=True)
class ModelPricing:
    """Immutable official Standard token pricing for one configured model."""

    model_id: str
    input_usd_per_million: Decimal
    cached_input_usd_per_million: Decimal
    output_usd_per_million: Decimal
    long_context_threshold_tokens: int
    long_context_input_multiplier: Decimal
    long_context_output_multiplier: Decimal
    cache_write_input_multiplier: Decimal
    price_snapshot_date: str
    price_source_url: str

    def validate(self) -> None:
        if not isinstance(self.model_id, str) or not _MODEL_ID.fullmatch(self.model_id):
            raise ContractError("model id is invalid")
        for value in (
            self.input_usd_per_million,
            self.cached_input_usd_per_million,
            self.output_usd_per_million,
            self.long_context_input_multiplier,
            self.long_context_output_multiplier,
            self.cache_write_input_multiplier,
        ):
            if (
                not isinstance(value, Decimal)
                or not value.is_finite()
                or value <= 0
                or value > _MAX_RATE_USD_PER_MILLION
            ):
                raise ContractError("model price must be a positive bounded Decimal")
        if (
            isinstance(self.long_context_threshold_tokens, bool)
            or not isinstance(self.long_context_threshold_tokens, int)
            or not 1 <= self.long_context_threshold_tokens <= 10_000_000
        ):
            raise ContractError("long-context threshold must be a bounded token count")
        if not isinstance(self.price_snapshot_date, str):
            raise ContractError("model price snapshot date must be ISO YYYY-MM-DD")
        try:
            parsed_date = date.fromisoformat(self.price_snapshot_date)
        except (TypeError, ValueError) as exc:
            raise ContractError("model price snapshot date must be ISO YYYY-MM-DD") from exc
        if parsed_date.isoformat() != self.price_snapshot_date:
            raise ContractError("model price snapshot date must be ISO YYYY-MM-DD")
        if not isinstance(self.price_source_url, str):
            raise ContractError("model price source URL is invalid")
        if (
            self.price_source_url != self.price_source_url.strip()
            or any(
                ord(character) < 0x20 or character == "\\"
                for character in self.price_source_url
            )
        ):
            raise ContractError("model price source URL is invalid")
        try:
            parsed_url = urlsplit(self.price_source_url)
            parsed_url.port
        except (TypeError, ValueError) as exc:
            raise ContractError("model price source URL is invalid") from exc
        if (
            parsed_url.scheme != "https"
            or parsed_url.hostname not in _OFFICIAL_PRICE_SOURCE_HOSTS
            or parsed_url.username is not None
            or parsed_url.password is not None
            or parsed_url.query
            or parsed_url.fragment
            or not parsed_url.path.startswith("/")
        ):
            raise ContractError("model price source must be an official HTTPS URL")

    def to_dict(self) -> dict[str, str]:
        self.validate()
        return {
            "model_id": self.model_id,
            "input_usd_per_million": _canonical_decimal(
                self.input_usd_per_million
            ),
            "cached_input_usd_per_million": _canonical_decimal(
                self.cached_input_usd_per_million
            ),
            "output_usd_per_million": _canonical_decimal(
                self.output_usd_per_million
            ),
            "long_context_threshold_tokens": str(
                self.long_context_threshold_tokens
            ),
            "long_context_input_multiplier": _canonical_decimal(
                self.long_context_input_multiplier
            ),
            "long_context_output_multiplier": _canonical_decimal(
                self.long_context_output_multiplier
            ),
            "cache_write_input_multiplier": _canonical_decimal(
                self.cache_write_input_multiplier
            ),
            "price_snapshot_date": self.price_snapshot_date,
            "price_source_url": self.price_source_url,
        }


@dataclass(frozen=True)
class ProviderProjection:
    """Immutable, non-secret paid-eval profile resolved from rondo.local.toml."""

    provider_id: str
    display_name: str
    api: str
    base_url: str
    api_key_env: str
    main_model: str
    guardian_model: str
    guardian_effort: str
    main_pricing: ModelPricing
    guardian_pricing: ModelPricing
    max_attempts: int
    retry_backoff_seconds: float
    unbilled_retry_statuses: tuple[int, ...]
    profile_sha256: str
    config_sha256: str
    config_source: str = "rondo.local.toml"

    def validate(self) -> None:
        if not isinstance(self.provider_id, str) or not _PROFILE_NAME.fullmatch(
            self.provider_id
        ):
            raise ContractError("provider id is invalid")
        if (
            not isinstance(self.display_name, str)
            or self.display_name != self.display_name.strip()
            or not 1 <= len(self.display_name) <= 128
            or any(ord(character) < 0x20 for character in self.display_name)
        ):
            raise ContractError("provider display name is invalid")
        if self.api != "responses":
            raise ContractError("provider id and Responses API are required")
        if (
            not isinstance(self.base_url, str)
            or not self.base_url
            or self.base_url != self.base_url.strip()
            or any(ord(character) < 0x20 or character == "\\" for character in self.base_url)
        ):
            raise ContractError("provider base_url must be a credential-free HTTPS URL")
        try:
            parsed = urlsplit(self.base_url)
            parsed.port
        except ValueError as exc:
            raise ContractError("provider base_url must be a credential-free HTTPS URL") from exc
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.hostname is None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ContractError("provider base_url must be a credential-free HTTPS URL")
        if not isinstance(self.api_key_env, str) or not _ENV_NAME.fullmatch(
            self.api_key_env
        ):
            raise ContractError("provider api_key_env is invalid")
        if not isinstance(self.main_pricing, ModelPricing) or not isinstance(
            self.guardian_pricing, ModelPricing
        ):
            raise ContractError("provider pricing profiles are invalid")
        self.main_pricing.validate()
        self.guardian_pricing.validate()
        if (
            self.main_model != self.main_pricing.model_id
            or self.guardian_model != self.guardian_pricing.model_id
        ):
            raise ContractError("provider models differ from their pricing profiles")
        if self.main_model == self.guardian_model and self.main_pricing != self.guardian_pricing:
            raise ContractError("one model id cannot have conflicting price profiles")
        if (
            not isinstance(self.guardian_effort, str)
            or self.guardian_effort not in _REASONING_EFFORTS
        ):
            raise ContractError("guardian reasoning effort is invalid")
        if (
            isinstance(self.max_attempts, bool)
            or not isinstance(self.max_attempts, int)
            or not 1 <= self.max_attempts <= 5
        ):
            raise ContractError("provider max_attempts must be an integer from 1 through 5")
        if (
            isinstance(self.retry_backoff_seconds, bool)
            or not isinstance(self.retry_backoff_seconds, (int, float))
            or not math.isfinite(self.retry_backoff_seconds)
            or not 0 <= self.retry_backoff_seconds <= _MAX_RETRY_BACKOFF_SECONDS
        ):
            raise ContractError("provider retry backoff must be from 0 through 30 seconds")
        if (
            not isinstance(self.unbilled_retry_statuses, tuple)
            or any(
                isinstance(status, bool)
                or not isinstance(status, int)
                or not 400 <= status <= 599
                for status in self.unbilled_retry_statuses
            )
            or len(self.unbilled_retry_statuses)
            != len(set(self.unbilled_retry_statuses))
            or self.unbilled_retry_statuses
            != tuple(sorted(self.unbilled_retry_statuses))
        ):
            raise ContractError("unbilled retry statuses must be unique sorted HTTP errors")
        if self.max_attempts > 1 and not self.unbilled_retry_statuses:
            raise ContractError("multiple attempts require an unbilled retry status allowlist")
        _require_sha256(self.profile_sha256, "paid eval profile sha256")
        _require_sha256(self.config_sha256, "runtime config sha256")
        if self.config_source != "rondo.local.toml":
            raise ContractError("provider projection must originate from rondo.local.toml")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "api": self.api,
            "base_url": self.base_url,
            "api_key_env": self.api_key_env,
            "main_model": self.main_model,
            "guardian_model": self.guardian_model,
            "guardian_effort": self.guardian_effort,
            "main_pricing": self.main_pricing.to_dict(),
            "guardian_pricing": self.guardian_pricing.to_dict(),
            "max_attempts": self.max_attempts,
            "retry_backoff_seconds": self.retry_backoff_seconds,
            "unbilled_retry_statuses": list(self.unbilled_retry_statuses),
            "profile_sha256": self.profile_sha256,
            "config_sha256": self.config_sha256,
            "config_source": self.config_source,
        }

    def to_public_dict(self) -> dict[str, Any]:
        """Return the tracked-result projection without local provider identity."""

        self.validate()
        return {
            "provider": self.provider_id,
            "provider_api": self.api,
            "provider_profile_sha256": self.profile_sha256,
            "provider_endpoint_sha256": hashlib.sha256(
                self.base_url.encode("utf-8")
            ).hexdigest(),
            "main_model": self.main_model,
            "guardian_model": self.guardian_model,
            "guardian_effort": self.guardian_effort,
            "main_pricing": self.main_pricing.to_dict(),
            "guardian_pricing": self.guardian_pricing.to_dict(),
            "provider_max_attempts": self.max_attempts,
            "provider_retry_backoff_seconds": self.retry_backoff_seconds,
            "provider_unbilled_retry_statuses": list(
                self.unbilled_retry_statuses
            ),
        }


@dataclass(frozen=True)
class RunSpec:
    side: Side
    batch_id: str
    task_id: str
    task_image_digest: str
    binary: BinaryManifest
    terminal_bench_version: str
    provider: ProviderProjection
    approvals_reviewer: str = "auto_review"
    approval_policy: str = "on-request"
    sandbox_mode: str = "workspace-write"
    sandbox_network_access: bool = True
    websocket: bool = False
    code_mode_host: bool = True
    timeout_seconds: int = 1800
    max_retries: int = 0
    budget_usd: float = 5.0
    schema_version: int = SCHEMA_VERSION

    def validate(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ContractError(f"unsupported RunSpec schema {self.schema_version}")
        if not self.batch_id or not self.task_id:
            raise ContractError("batch id and task id are required")
        if not self.task_image_digest.startswith("sha256:"):
            raise ContractError("task image must be pinned by sha256 digest")
        _require_sha256(self.task_image_digest.removeprefix("sha256:"), "task image digest")
        self.binary.validate()
        self.provider.validate()
        if not self.terminal_bench_version:
            raise ContractError("Terminal-Bench version is required")
        expected = (
            self.approvals_reviewer == "auto_review"
            and self.approval_policy == "on-request"
            and self.sandbox_mode == "workspace-write"
            and self.sandbox_network_access is True
            and not self.websocket
            and self.code_mode_host is True
        )
        if not expected:
            raise ContractError("run conditions differ from the frozen P1 fairness contract")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, int)
            or not 0 < self.timeout_seconds <= _MAX_RUN_TIMEOUT_SECONDS
        ):
            raise ContractError("run timeout must be an integer from 1 through 3600 seconds")
        if (
            isinstance(self.max_retries, bool)
            or not isinstance(self.max_retries, int)
            or not 0 <= self.max_retries <= _MAX_RUN_RETRIES
        ):
            raise ContractError("run retries must be an integer from 0 through 10")
        if (
            isinstance(self.budget_usd, bool)
            or not isinstance(self.budget_usd, (int, float))
            or not math.isfinite(self.budget_usd)
            or not 0 < self.budget_usd <= 5.0
        ):
            raise ContractError("run budget must be within the frozen 5 USD per-run cap")

    def fairness_fingerprint(self) -> dict[str, Any]:
        self.validate()
        return {
            "schema_version": self.schema_version,
            "batch_id": self.batch_id,
            "task_id": self.task_id,
            "task_image_digest": self.task_image_digest,
            "terminal_bench_version": self.terminal_bench_version,
            "provider": self.provider.to_dict(),
            "approvals_reviewer": self.approvals_reviewer,
            "approval_policy": self.approval_policy,
            "sandbox_mode": self.sandbox_mode,
            "sandbox_network_access": self.sandbox_network_access,
            "websocket": self.websocket,
            "code_mode_host": self.code_mode_host,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "budget_usd": self.budget_usd,
        }

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        value = asdict(self)
        value["side"] = self.side.value
        value["provider"] = self.provider.to_dict()
        value["binary"]["build_command"] = list(self.binary.build_command)
        value["binary"]["code_mode_host_build_command"] = list(
            self.binary.code_mode_host_build_command
        )
        return value


@dataclass(frozen=True)
class PreparedRun:
    run_id: str
    spec: RunSpec
    prepared_at: str

    def validate(self) -> None:
        self.spec.validate()
        if not self.run_id or not self.prepared_at:
            raise ContractError("prepared run requires run id and timestamp")


def assert_fair_pair(first: RunSpec, second: RunSpec) -> None:
    first.validate()
    second.validate()
    if first.side == second.side:
        raise ContractError("fair comparison requires one codex and one rondo side")
    if first.fairness_fingerprint() != second.fairness_fingerprint():
        raise ContractError("codex and rondo RunSpec fairness fields differ")


def _require_sha256(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ContractError(f"{label} must be 64 lowercase hexadecimal characters")


def _require_commit(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise ContractError(f"{label} must be 40 lowercase hexadecimal characters")


def _canonical_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")
