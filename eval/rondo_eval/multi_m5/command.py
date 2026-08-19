"""Shared `codex exec` argv for Multi M-5 host runs.

Loopback, the gate 1 rehearsal, and a later paid gate 1 run must construct the
same command. The team-capability `-c` items come only from
``contracts.team_capability_override_items``; this module refuses to drift.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..contracts import (
    Product,
    TEAM_CAPABILITY_MULTI_TOML,
    team_capability_override_items,
)
from .load import M5ContractError

EVAL_PROVIDER = "rondo_eval_provider"


def team_capability_overrides(
    *, member_model: str, member_effort: str
) -> tuple[str, ...]:
    """Team capability `-c` items with this campaign's own member identity.

    The member model has to come from the gate 1 lock, not the machine-wide
    default. A member started on a different model is rejected by the capture
    proxy before it sends anything, so it dies silently and every collaboration
    predicate reads false -- a product verdict produced entirely by a config
    mismatch.
    """

    items = team_capability_override_items(
        Product.RONDO_MULTI,
        subagent_model=member_model,
        subagent_effort=member_effort,
    )
    expected = (
        f"features.multi_agent_v2={TEAM_CAPABILITY_MULTI_TOML}",
        f"agents.default_subagent_model={json.dumps(member_model)}",
        f"agents.default_subagent_reasoning_effort={json.dumps(member_effort)}",
    )
    if items != expected:
        raise M5ContractError("team capability override drifted")
    return items


def build_multi_exec_command(
    binary: Path,
    *,
    base_url: str,
    instruction: str,
    model: str,
    effort: str,
    member_model: str | None = None,
    member_effort: str | None = None,
) -> list[str]:
    """Frozen Multi binary, strict config, team capability, Responses provider."""

    member_model = member_model or model
    member_effort = member_effort or effort

    overrides = (
        'approval_policy="never"',
        'sandbox_mode="workspace-write"',
        "sandbox_workspace_write.network_access=true",
        "features.code_mode_host=true",
        f"model_provider={json.dumps(EVAL_PROVIDER)}",
        f'model_providers.{EVAL_PROVIDER}.name="Configured Provider"',
        f"model_providers.{EVAL_PROVIDER}.base_url={json.dumps(base_url)}",
        f'model_providers.{EVAL_PROVIDER}.wire_api="responses"',
        f"model_providers.{EVAL_PROVIDER}.requires_openai_auth=true",
        f"model_providers.{EVAL_PROVIDER}.supports_websockets=false",
        f"model_providers.{EVAL_PROVIDER}.request_max_retries=0",
        f"model_providers.{EVAL_PROVIDER}.stream_max_retries=0",
        f"model_reasoning_effort={json.dumps(effort)}",
        *team_capability_overrides(
            member_model=member_model, member_effort=member_effort
        ),
    )
    command = [
        str(binary),
        "exec",
        "--strict-config",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--model",
        model,
        "--json",
    ]
    for value in overrides:
        command.extend(("-c", value))
    command.extend(("--", instruction))
    return command
