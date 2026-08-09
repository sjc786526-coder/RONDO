"""Versioned contracts shared by the Terminal-Bench and approval tracks."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import urlsplit


SCHEMA_VERSION = 1
_ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*\Z")


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
    source_commit: str
    source_dirty: bool
    rust_toolchain: str
    build_command: tuple[str, ...]
    workspace_lock_normalization: str | None = None

    def validate(self) -> None:
        if not isinstance(self.path, str) or not self.path:
            raise ContractError("binary path is required")
        _require_sha256(self.sha256, "binary sha256")
        _require_commit(self.source_commit, "binary source commit")
        if not isinstance(self.source_dirty, bool):
            raise ContractError("binary source_dirty must be boolean")
        if (
            not isinstance(self.rust_toolchain, str)
            or not self.rust_toolchain
            or not isinstance(self.build_command, tuple)
            or not self.build_command
            or any(not isinstance(item, str) or not item for item in self.build_command)
        ):
            raise ContractError("binary toolchain and build command are required")
        if self.workspace_lock_normalization is not None and (
            not isinstance(self.workspace_lock_normalization, str)
            or not self.workspace_lock_normalization
        ):
            raise ContractError("workspace lock normalization must be non-empty or null")


@dataclass(frozen=True)
class ProviderProjection:
    """Immutable, non-secret projection of one provider from rondo.local.toml."""

    provider_id: str
    api: str
    base_url: str
    api_key_env: str
    main_model: str
    guardian_model: str
    guardian_effort: str
    config_sha256: str
    config_source: str = "rondo.local.toml"

    def validate(self) -> None:
        if not self.provider_id or self.api != "responses":
            raise ContractError("provider id and Responses API are required")
        parsed = urlsplit(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ContractError("provider base_url must be a credential-free HTTP URL")
        if not _ENV_NAME.fullmatch(self.api_key_env):
            raise ContractError("provider api_key_env is invalid")
        if (
            self.main_model != "gpt-5.6-luna"
            or self.guardian_model != "gpt-5.6-luna"
            or self.guardian_effort != "low"
        ):
            raise ContractError("provider projection differs from the frozen P1 model contract")
        _require_sha256(self.config_sha256, "runtime config sha256")
        if self.config_source != "rondo.local.toml":
            raise ContractError("provider projection must originate from rondo.local.toml")


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
    websocket: bool = False
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
            and not self.websocket
        )
        if not expected:
            raise ContractError("run conditions differ from the frozen P1 fairness contract")
        if self.timeout_seconds <= 0 or self.max_retries < 0:
            raise ContractError("timeout and retry values must be bounded")
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
            "provider": asdict(self.provider),
            "approvals_reviewer": self.approvals_reviewer,
            "approval_policy": self.approval_policy,
            "sandbox_mode": self.sandbox_mode,
            "websocket": self.websocket,
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "budget_usd": self.budget_usd,
        }

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        value = asdict(self)
        value["side"] = self.side.value
        value["binary"]["build_command"] = list(self.binary.build_command)
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
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ContractError(f"{label} must be 64 lowercase hexadecimal characters")


def _require_commit(value: str, label: str) -> None:
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise ContractError(f"{label} must be 40 lowercase hexadecimal characters")
