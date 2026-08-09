"""Tool-free static approval through the pinned local llama.cpp runtime."""

from .client import (
    LocalApprovalClient,
    LocalApprovalError,
    LocalApprovalSettings,
    ServiceUnavailableError,
    StructuredOutputError,
    settings_from_config,
)

__all__ = [
    "LocalApprovalClient",
    "LocalApprovalError",
    "LocalApprovalSettings",
    "ServiceUnavailableError",
    "StructuredOutputError",
    "settings_from_config",
]
