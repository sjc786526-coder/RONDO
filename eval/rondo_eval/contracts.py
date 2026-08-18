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


class Product(StrEnum):
    """Which RONDO product is under test.

    Orthogonal to ``Side``: ``side`` says whether a row is the RONDO side or
    the frozen upstream side, ``product`` says which RONDO product it is.
    ``codex`` is deliberately absent -- the frozen upstream is a comparison
    side, not a product line of this project.
    """

    RONDO_LOCAL = "rondo-local"
    RONDO_MULTI = "rondo-multi"


def product_for_side(side: Side, product: Product | None) -> Product | None:
    """Return the product identity that may be recorded for ``side``.

    The frozen upstream side never carries a product identity.  The RONDO side
    always does; an unset product means an artifact or request predates the
    product dimension, and those are Local by definition (see
    ``doc/eval-data-layout.md`` 3.1).  A Multi request therefore never arrives
    here as ``None`` -- it has to name itself.
    """

    if side is Side.CODEX:
        if product is not None:
            raise ContractError("the frozen upstream side has no product identity")
        return None
    if side is not Side.RONDO:
        raise ContractError("unsupported evaluation side")
    if product is None:
        return Product.RONDO_LOCAL
    if not isinstance(product, Product):
        raise ContractError("product identity is invalid")
    return product


@dataclass(frozen=True)
class ProductLayout:
    """Where one RONDO product keeps its source, build tree and artifacts.

    Every product-dependent path in the facility is derived from here so a new
    product cannot be half-wired: one entry decides the source directory, the
    Cargo target name, the frozen bundle namespace and the model catalog blob.
    """

    product: Product
    source_dir: str
    artifact_dir: str
    target_prefix: str

    @property
    def catalog_path(self) -> str:
        """Repository-relative path of this product's built-in model catalog."""

        return f"{self.source_dir}/codex-rs/models-manager/models.json"


_PRODUCT_LAYOUTS = {
    # `bin/rondo/` predates the product dimension and stays under its original
    # name; Multi must carry `multi` explicitly so the two can never collide.
    Product.RONDO_LOCAL: ProductLayout(
        product=Product.RONDO_LOCAL,
        source_dir="mydev",
        artifact_dir="rondo",
        target_prefix="rondo",
    ),
    Product.RONDO_MULTI: ProductLayout(
        product=Product.RONDO_MULTI,
        source_dir="multidev",
        artifact_dir="rondo-multi",
        target_prefix="rondo-multi",
    ),
}


def product_layout(product: Product | None) -> ProductLayout:
    """Return the layout for ``product``; ``None`` means the historical Local one."""

    resolved = Product.RONDO_LOCAL if product is None else product
    layout = _PRODUCT_LAYOUTS.get(resolved)
    if layout is None:
        raise ContractError("product identity is invalid")
    return layout


def parse_product(value: object) -> Product:
    try:
        return Product(str(value))
    except ValueError as exc:
        raise ContractError("product identity is invalid") from exc


AUTO_REVIEW_CONFIG_SCHEMA_VERSION = 1
AUTO_REVIEW_EVIDENCE_DIR = "/logs/agent/guardian-evidence"
TEAM_CAPABILITY_CONFIG_SCHEMA_VERSION = 1
# Inline TOML table consumed by `-c`. One override avoids boolean-vs-table
# clobbering if `features.multi_agent_v2=true` were mixed with nested keys.
TEAM_CAPABILITY_MULTI_TOML = (
    "{enabled=true,team_state_enabled=true,non_code_mode_only=false}"
)


def auto_review_overrides(
    product: Product | None,
    *,
    guardian_model: str,
    guardian_effort: str,
) -> dict[str, str | None]:
    """Return the ``[auto_review]`` fields the harness configures for a product.

    This is the single source of truth behind both the agent's ``-c`` overrides
    and the ``auto_review_config`` block recorded in results, so a run can never
    claim a configuration state its command line contradicts.

    RONDO Local keeps the frozen P1/P2 fairness contract: the Guardian model,
    effort and evidence directory are configured explicitly.  RONDO Multi's
    product baseline is defined as the closed state, so it configures none of
    them.  ``model_provider`` is never configured by the harness on either
    product -- the Guardian inherits the session provider.
    """

    if product is Product.RONDO_MULTI:
        return {
            "model": None,
            "model_provider": None,
            "reasoning_effort": None,
            "evidence_dir": None,
        }
    if product is Product.RONDO_LOCAL:
        return {
            "model": guardian_model,
            "model_provider": None,
            "reasoning_effort": guardian_effort,
            "evidence_dir": AUTO_REVIEW_EVIDENCE_DIR,
        }
    raise ContractError("product identity is invalid")


def auto_review_config_projection(
    side: Side,
    product: Product | None,
    *,
    guardian_model: str,
    guardian_effort: str,
) -> dict[str, object] | None:
    """Project the recorded ``[auto_review]`` state for one run.

    ``None`` values mean the field was left unset -- that is a statement about
    configuration, never about the model a provider or catalog ends up deriving.
    Returns ``None`` for the frozen upstream, which has no such configuration.
    """

    resolved = product_for_side(side, product)
    if resolved is None:
        return None
    return {
        "schema_version": AUTO_REVIEW_CONFIG_SCHEMA_VERSION,
        **auto_review_overrides(
            resolved,
            guardian_model=guardian_model,
            guardian_effort=guardian_effort,
        ),
    }


def team_capability_override_items(product: Product | None) -> tuple[str, ...]:
    """Return the ``-c`` items that turn Multi team capability on.

    Local and the frozen upstream get nothing: team tools are Multi-only, and
    ``--strict-config`` would reject ``team_state_enabled`` on v0.147.0 Codex.
    ``non_code_mode_only=false`` keeps spawn/team tools Direct while eval also
    enables ``code_mode_host``.
    """

    if product is not Product.RONDO_MULTI:
        return ()
    return (f"features.multi_agent_v2={TEAM_CAPABILITY_MULTI_TOML}",)


def team_capability_config_projection(
    side: Side,
    product: Product | None,
) -> dict[str, object] | None:
    """Record whether this run configured Multi team capability.

    ``None`` for the frozen upstream. Local records the closed state so a
    Multi/Local mix-up is visible in the archive rather than implied.
    """

    resolved = product_for_side(side, product)
    if resolved is None:
        return None
    enabled = resolved is Product.RONDO_MULTI
    return {
        "schema_version": TEAM_CAPABILITY_CONFIG_SCHEMA_VERSION,
        "multi_agent_v2_enabled": enabled,
        "team_state_enabled": enabled,
        "non_code_mode_only": False if enabled else None,
    }


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
    # Absent on every bundle frozen before the product dimension existed and on
    # every frozen-upstream bundle.  ``product_for_manifest`` resolves it.
    product: str | None = None

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
        if self.product is not None:
            parse_product(self.product)


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
    main_effort: str
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
            not isinstance(self.main_effort, str)
            or self.main_effort not in _REASONING_EFFORTS
        ):
            raise ContractError("main reasoning effort is invalid")
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
            "main_effort": self.main_effort,
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
            "main_effort": self.main_effort,
            "guardian_model": self.guardian_model,
            "guardian_effort": self.guardian_effort,
            "requested_main_model": self.main_model,
            "effective_main_model": self.main_model,
            "requested_guardian_model": self.guardian_model,
            "effective_guardian_model": self.guardian_model,
            "main_pricing": self.main_pricing.to_dict(),
            "guardian_pricing": self.guardian_pricing.to_dict(),
            "provider_max_attempts": self.max_attempts,
            "provider_retry_backoff_seconds": self.retry_backoff_seconds,
            "provider_unbilled_retry_statuses": list(
                self.unbilled_retry_statuses
            ),
        }


def product_for_manifest(side: Side, manifest: BinaryManifest) -> Product | None:
    """Resolve which product a frozen bundle belongs to.

    A bundle that names its product is authoritative.  One that does not is
    either the frozen upstream (never a product) or a RONDO bundle frozen
    before the dimension existed, which is Local.
    """

    declared = None if manifest.product is None else parse_product(manifest.product)
    return product_for_side(side, declared)


@dataclass(frozen=True)
class RunSpec:
    side: Side
    batch_id: str
    task_id: str
    task_image_digest: str
    binary: BinaryManifest
    terminal_bench_version: str
    provider: ProviderProjection
    # Which RONDO product is under test.  Orthogonal to ``side``; `None` means
    # the frozen upstream side or a caller that predates the dimension.
    product: Product | None = None
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
        # The run and the binary it runs must name the same product, otherwise
        # a Multi request could execute a Local bundle and still look coherent.
        if self.effective_product() != product_for_manifest(self.side, self.binary):
            raise ContractError("run product differs from its frozen binary product")
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
            or not 0 < self.budget_usd <= 40.0
        ):
            raise ContractError("run budget must be within the supported 40 USD cap")

    def effective_product(self) -> Product | None:
        return product_for_side(self.side, self.product)

    def fairness_fingerprint(self) -> dict[str, Any]:
        # Deliberately excludes ``product``: the two sides of a fair pair are
        # the RONDO product and the frozen upstream, so they can never share a
        # product value.  Product is an identity dimension, not a run condition.
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
        effective = self.effective_product()
        value["product"] = None if effective is None else effective.value
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
