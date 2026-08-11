"""Bounded Plan 012 provider probes with no response-body logging."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, urlopen

from .api_budget_proxy import (
    OFFICIAL_MODEL,
    UPSTREAM_TIMEOUT_SECONDS,
    ApiBudgetProxyError,
    LoopbackResponsesProxy,
    PersistentBudgetLedger,
    _NoRedirect,
    _SseUsageCollector,
    _UrllibTransport,
    _atomic_private_json,
    _compatible_responses_endpoint,
    _usage_from_json_bytes,
)
from .config import ConfigError, RepoPaths, RuntimeConfig, load_provider_secret, load_runtime_config
from .exit_codes import EVIDENCE_ERROR, SUCCESS


PROBE_BATCH_ID = "plan012-provider-responses-r2"
PROBE_RUN_ID = "plan012-provider-responses-r2"
PROBE_TOTAL_CAP_USD = Decimal("5")
PROBE_MAX_OUTPUT_TOKENS = 64
PROBE_CLIENT_TIMEOUT_SECONDS = 120.0
PROBE_USER_AGENT = "codex_cli_rs/0.147.0 (rondo-eval-provider-probe)"
_MAX_PROBE_RESPONSE_BYTES = 8 * 1024 * 1024
_MAX_MODELS_RESPONSE_BYTES = 2 * 1024 * 1024


class ProviderProbeError(RuntimeError):
    """A provider probe failed without exposing response or credential data."""


@dataclass(frozen=True)
class ProviderResponseProbe:
    name: str
    http_status: int
    stream: bool
    terminal: bool
    usage_valid: bool
    charged_usd: str


def probe_models_status(
    base_url: str,
    api_key: str,
    *,
    timeout_seconds: float = UPSTREAM_TIMEOUT_SECONDS,
    _endpoint_override: str | None = None,
) -> int:
    """Return only the authenticated /models status; discard its body."""

    _compatible_responses_endpoint(base_url)
    if not api_key or "\r" in api_key or "\n" in api_key:
        raise ProviderProbeError("provider credential is invalid")
    if not 0 < timeout_seconds <= UPSTREAM_TIMEOUT_SECONDS:
        raise ProviderProbeError("models probe timeout exceeds the bounded transport limit")
    endpoint = f"{base_url.rstrip('/')}/models"
    if _endpoint_override is not None:
        parsed = urlsplit(_endpoint_override)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ProviderProbeError("models test override must be loopback HTTP")
        endpoint = _endpoint_override
    request = Request(
        endpoint,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "User-Agent": PROBE_USER_AGENT,
            "originator": "codex_cli_rs",
        },
        method="GET",
    )
    opener = build_opener(_NoRedirect())
    try:
        with opener.open(request, timeout=timeout_seconds) as response:
            status = int(response.status)
            if len(response.read(_MAX_MODELS_RESPONSE_BYTES + 1)) > _MAX_MODELS_RESPONSE_BYTES:
                raise ProviderProbeError("models response exceeds the bounded size")
    except HTTPError as response:
        status = int(response.code)
        response.close()
    except (OSError, URLError, TimeoutError) as exc:
        raise ProviderProbeError("models endpoint transport failed") from exc
    return status


def run_provider_probes(
    config: RuntimeConfig,
    api_key: str,
    *,
    output_root: Path,
    _transport: _UrllibTransport | None = None,
) -> dict[str, object]:
    """Run the two remaining bounded Responses probes after the models timeout."""

    provider = config.provider("openai")
    base_url = provider.get("base_url")
    model = provider.get("main_model")
    if not isinstance(base_url, str) or model != OFFICIAL_MODEL:
        raise ProviderProbeError("provider probe configuration differs from the frozen main model")
    output_root = Path(output_root)
    if output_root.exists() or output_root.is_symlink():
        raise ProviderProbeError("provider probe output already exists; retries are disabled")
    output_root.mkdir(parents=True, mode=0o700)
    output_root.chmod(0o700)
    metadata_path = output_root / "api-metadata.json"
    probes: list[ProviderResponseProbe] = []
    ledger_path = output_root / "budget.json"
    with PersistentBudgetLedger(
        ledger_path,
        batch_id=PROBE_BATCH_ID,
        total_cap_usd=PROBE_TOTAL_CAP_USD,
        max_runs=1,
        default_run_cap_usd=PROBE_TOTAL_CAP_USD,
    ) as ledger:
        with LoopbackResponsesProxy(
            upstream_base_url=base_url,
            api_key=api_key,
            ledger=ledger,
            run_id=PROBE_RUN_ID,
            metadata_path=metadata_path,
            timeout_seconds=UPSTREAM_TIMEOUT_SECONDS,
            _transport=_transport,
        ) as proxy:
            for name, stream in (("nonstream", False), ("stream", True)):
                probes.append(_run_responses_probe(proxy, ledger, name=name, stream=stream))
        snapshot = ledger.snapshot()
    if snapshot["reserved_usd"] != "0.000000":
        raise ProviderProbeError("provider probe reservation did not settle")
    receipt: dict[str, object] = {
        "schema_version": 1,
        "batch_id": PROBE_BATCH_ID,
        "request_count": 2,
        "responses": [probe.__dict__ for probe in probes],
        "spent_usd": snapshot["spent_usd"],
        "reserved_usd": snapshot["reserved_usd"],
        "total_cap_usd": snapshot["total_cap_usd"],
    }
    _atomic_private_json(output_root / "receipt.json", receipt)
    return receipt


def _run_responses_probe(
    proxy: LoopbackResponsesProxy,
    ledger: PersistentBudgetLedger,
    *,
    name: str,
    stream: bool,
) -> ProviderResponseProbe:
    body = json.dumps(
        {
            "model": OFFICIAL_MODEL,
            "input": "Reply only with OK.",
            "reasoning": {"effort": "low"},
            "max_output_tokens": PROBE_MAX_OUTPUT_TOKENS,
            "stream": stream,
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        proxy.base_url + "/responses",
        data=body,
        headers={
            "Authorization": f"Bearer {proxy.downstream_api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream" if stream else "application/json",
            "X-RONDO-Eval-Role": "main",
            "X-RONDO-Eval-Request-Id": f"plan012-{name}",
            "User-Agent": PROBE_USER_AGENT,
            "originator": "codex_cli_rs",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=PROBE_CLIENT_TIMEOUT_SECONDS) as response:
            status = int(response.status)
            payload = response.read(_MAX_PROBE_RESPONSE_BYTES + 1)
    except HTTPError as response:
        status = int(response.code)
        response.close()
        raise ProviderProbeError(f"{name} Responses probe returned HTTP {status}") from None
    except (OSError, URLError, TimeoutError) as exc:
        raise ProviderProbeError(f"{name} Responses probe transport failed") from exc
    if len(payload) > _MAX_PROBE_RESPONSE_BYTES or not 200 <= status < 300:
        raise ProviderProbeError(f"{name} Responses probe returned an invalid response")
    if stream:
        collector = _SseUsageCollector()
        collector.feed(payload)
        collector.finish()
        terminal = collector.completed
        usage_valid = collector.usage is not None
    else:
        try:
            response_value = json.loads(payload)
        except (UnicodeError, json.JSONDecodeError):
            response_value = None
        terminal = isinstance(response_value, dict) and response_value.get("status") == "completed"
        usage_valid = _usage_from_json_bytes(payload) is not None
    snapshot = ledger.snapshot()
    request_state = snapshot["runs"][PROBE_RUN_ID]["requests"].get(f"plan012-{name}")
    settled = (
        isinstance(request_state, dict)
        and request_state.get("status") == "settled"
        and request_state.get("usage_valid") is True
    )
    if not terminal or not usage_valid or not settled or snapshot["reserved_usd"] != "0.000000":
        raise ProviderProbeError(f"{name} Responses probe lacked terminal usage settlement")
    return ProviderResponseProbe(
        name=name,
        http_status=status,
        stream=stream,
        terminal=terminal,
        usage_valid=usage_valid,
        charged_usd=str(request_state["charged_usd"]),
    )


def main() -> int:
    try:
        paths = RepoPaths.discover(Path.cwd())
        config = load_runtime_config(paths)
        _secret_name, api_key = load_provider_secret(config, "openai")
        receipt = run_provider_probes(
            config,
            api_key,
            output_root=(
                paths.common_root
                / "eval-data"
                / "provider-probes"
                / "plan012-v8-responses-r2"
            ),
        )
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        return SUCCESS
    except (ApiBudgetProxyError, ConfigError, ProviderProbeError, OSError, ValueError) as exc:
        reason = str(exc)
        if not reason or any(character in reason for character in "\r\n\0"):
            reason = "provider probe failed"
        print(json.dumps(
            {"schema_version": 1, "status": "failed", "reason": reason},
            sort_keys=True,
            separators=(",", ":"),
        ))
        return EVIDENCE_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
