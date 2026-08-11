"""Bounded configured-provider probes with no response-body logging."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, urlopen

from .api_budget_proxy import (
    GUARDIAN_OUTPUT_SCHEMA,
    UPSTREAM_TIMEOUT_SECONDS,
    ApiBudgetProxyError,
    LoopbackResponsesProxy,
    PersistentBudgetLedger,
    SHORT_REQUEST_RESERVATION_USD,
    _NoRedirect,
    _UrllibTransport,
    _atomic_private_json,
    _compatible_responses_endpoint,
    _usage_from_json_bytes,
)
from .config import ConfigError, RepoPaths, RuntimeConfig, load_provider_secret, load_runtime_config
from .exit_codes import EVIDENCE_ERROR, SUCCESS


PROBE_BATCH_ID = "plan013-configured-provider-probe-v2"
PROBE_RUN_ID = "plan013-configured-provider-probe-v2"
# v2 receives only the remaining 5 USD of Plan 013's local authorization. The
# execution log distinguishes the earlier v1 transport failure from ledger facts.
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
    role: str
    model: str
    http_status: int
    stream: bool
    terminal: bool
    usage_valid: bool
    charged_usd: str
    attempt_count: int
    settlement_kind: str


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
    """Run one main and one Guardian-shaped request through the budget proxy."""

    provider = config.paid_provider_projection()
    base_url = provider.base_url
    output_root = Path(output_root)
    if output_root.exists() or output_root.is_symlink():
        _reconcile_existing_probe(output_root)
    output_root.mkdir(parents=True, mode=0o700)
    output_root.chmod(0o700)
    profile_summary: dict[str, object] = {
        "schema_version": 1,
        "batch_id": PROBE_BATCH_ID,
        "run_id": PROBE_RUN_ID,
        "provider_profile_sha256": provider.profile_sha256,
        "provider_endpoint_sha256": hashlib.sha256(
            base_url.encode("utf-8")
        ).hexdigest(),
        "main_model": provider.main_model,
        "guardian_model": provider.guardian_model,
        "guardian_effort": provider.guardian_effort,
        "request_reservation_usd": format(SHORT_REQUEST_RESERVATION_USD, "f"),
        "max_guardian_logical_requests": 1,
        "total_cap_usd": format(PROBE_TOTAL_CAP_USD, "f"),
    }
    _atomic_private_json(output_root / "profile.json", profile_summary)
    metadata_path = output_root / "api-metadata.json"
    probes: list[ProviderResponseProbe] = []
    ledger_path = output_root / "budget.json"
    with PersistentBudgetLedger(
        ledger_path,
        batch_id=PROBE_BATCH_ID,
        total_cap_usd=PROBE_TOTAL_CAP_USD,
        max_runs=1,
        default_run_cap_usd=Decimal("5"),
    ) as ledger:
        try:
            with LoopbackResponsesProxy(
                upstream_base_url=base_url,
                api_key=api_key,
                ledger=ledger,
                run_id=PROBE_RUN_ID,
                metadata_path=metadata_path,
                main_model=provider.main_model,
                main_pricing=provider.main_pricing,
                guardian_model=provider.guardian_model,
                guardian_pricing=provider.guardian_pricing,
                guardian_effort=provider.guardian_effort,
                max_attempts=provider.max_attempts,
                retry_backoff_seconds=provider.retry_backoff_seconds,
                unbilled_retry_statuses=provider.unbilled_retry_statuses,
                request_reservation_usd=SHORT_REQUEST_RESERVATION_USD,
                max_guardian_logical_requests=1,
                timeout_seconds=UPSTREAM_TIMEOUT_SECONDS,
                _transport=_transport,
            ) as proxy:
                for name, role, model in (
                    ("main", "main", provider.main_model),
                    ("guardian", "guardian", provider.guardian_model),
                ):
                    probes.append(
                        _run_responses_probe(
                            proxy,
                            ledger,
                            name=name,
                            role=role,
                            model=model,
                            guardian_effort=provider.guardian_effort,
                        )
                    )
            snapshot = ledger.snapshot()
        except (ApiBudgetProxyError, ProviderProbeError, OSError, ValueError) as exc:
            snapshot = ledger.snapshot()
            _atomic_private_json(
                output_root / "receipt.json",
                _probe_receipt(
                    profile_summary,
                    snapshot,
                    probes=probes,
                    status="failed",
                    failure_reason=_safe_failure_reason(exc),
                ),
            )
            raise
    if snapshot["reserved_usd"] != "0.000000":
        raise ProviderProbeError("provider probe reservation did not settle")
    receipt = _probe_receipt(profile_summary, snapshot, probes=probes, status="completed")
    _atomic_private_json(output_root / "receipt.json", receipt)
    return receipt


def _probe_receipt(
    profile_summary: dict[str, object],
    snapshot: dict[str, Any],
    *,
    probes: list[ProviderResponseProbe],
    status: str,
    failure_reason: str | None = None,
) -> dict[str, object]:
    runs = snapshot.get("runs")
    run = runs.get(PROBE_RUN_ID) if isinstance(runs, dict) else None
    requests = run.get("requests") if isinstance(run, dict) else {}
    if not isinstance(requests, dict):
        requests = {}
    receipt: dict[str, object] = {
        **profile_summary,
        "schema_version": 2,
        "status": status,
        "logical_request_count": len(requests),
        "upstream_attempt_count": sum(
            item.get("attempt_count", 0)
            for item in requests.values()
            if isinstance(item, dict) and isinstance(item.get("attempt_count"), int)
        ),
        "responses": [probe.__dict__ for probe in probes],
        "settlements": {
            request_id: {
                key: item.get(key)
                for key in (
                    "status",
                    "charged_usd",
                    "usage_valid",
                    "attempt_count",
                    "settlement_kind",
                )
            }
            for request_id, item in requests.items()
            if isinstance(request_id, str) and isinstance(item, dict)
        },
        "estimated_spent_usd": snapshot["spent_usd"],
        "actual_usd": None,
        "reserved_usd": snapshot["reserved_usd"],
    }
    if failure_reason is not None:
        receipt["failure_reason"] = failure_reason
    return receipt


def _reconcile_existing_probe(output_root: Path) -> None:
    if output_root.is_symlink() or not output_root.is_dir():
        raise ProviderProbeError("provider probe output path is unsafe")
    ledger_path = output_root / "budget.json"
    if ledger_path.is_symlink() or not ledger_path.is_file():
        raise ProviderProbeError("existing provider probe has no safe budget ledger")
    with PersistentBudgetLedger(
        ledger_path,
        batch_id=PROBE_BATCH_ID,
        total_cap_usd=PROBE_TOTAL_CAP_USD,
        max_runs=1,
        default_run_cap_usd=Decimal("5"),
    ) as ledger:
        snapshot = ledger.snapshot()
    receipt_path = output_root / "receipt.json"
    profile_path = output_root / "profile.json"
    if profile_path.is_file() and not profile_path.is_symlink():
        try:
            profile = json.loads(profile_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ProviderProbeError("existing provider probe profile is unreadable") from exc
        if not isinstance(profile, dict):
            raise ProviderProbeError("existing provider probe profile is invalid")
        previous_receipt: object = None
        if receipt_path.exists() or receipt_path.is_symlink():
            if receipt_path.is_symlink() or not receipt_path.is_file():
                raise ProviderProbeError("existing provider probe receipt is unsafe")
            try:
                previous_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise ProviderProbeError("existing provider probe receipt is unreadable") from exc
            if not isinstance(previous_receipt, dict):
                raise ProviderProbeError("existing provider probe receipt is invalid")
        current_summary = _probe_receipt(
            profile,
            snapshot,
            probes=[],
            status="reconciled_without_retry",
        )
        comparison_keys = (
            "logical_request_count",
            "upstream_attempt_count",
            "settlements",
            "estimated_spent_usd",
            "reserved_usd",
        )
        receipt_is_current = isinstance(previous_receipt, dict) and all(
            previous_receipt.get(key) == current_summary[key]
            for key in comparison_keys
        )
        if not receipt_is_current:
            current_summary["failure_reason"] = (
                "previous_process_ended_before_receipt"
                if previous_receipt is None
                else "previous_receipt_updated_after_ledger_recovery"
            )
            _atomic_private_json(receipt_path, current_summary)
    raise ProviderProbeError("provider probe output already exists; ledger reconciled without retry")


def _safe_failure_reason(exc: BaseException) -> str:
    reason = str(exc)
    if not reason or len(reason) > 256 or any(character in reason for character in "\r\n\0"):
        return "provider probe failed"
    return reason


def _run_responses_probe(
    proxy: LoopbackResponsesProxy,
    ledger: PersistentBudgetLedger,
    *,
    name: str,
    role: str,
    model: str,
    guardian_effort: str,
) -> ProviderResponseProbe:
    if role not in {"main", "guardian"}:
        raise ProviderProbeError("provider probe role is invalid")
    request_value: dict[str, object] = {
        "model": model,
        "input": (
            "Return an allow decision that matches the required JSON schema."
            if role == "guardian"
            else "Reply only with OK."
        ),
        "reasoning": {"effort": guardian_effort if role == "guardian" else "low"},
        "max_output_tokens": PROBE_MAX_OUTPUT_TOKENS,
        "stream": False,
        # Frozen Codex/RONDO send store=false for non-Azure Responses
        # providers.  Keep the synthetic probe on the same privacy contract.
        "store": False,
    }
    if role == "guardian":
        request_value["text"] = {
            "format": {
                "type": "json_schema",
                "name": "codex_output_schema",
                # Guardian intentionally leaves its optional diagnostic fields
                # optional.  strict=true would require every property to be in
                # `required` and is not the real Codex request contract.
                "strict": False,
                "schema": GUARDIAN_OUTPUT_SCHEMA,
            }
        }
    body = json.dumps(request_value, separators=(",", ":")).encode("utf-8")
    request = Request(
        proxy.base_url + "/responses",
        data=body,
        headers={
            "Authorization": f"Bearer {proxy.downstream_api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "X-RONDO-Eval-Role": role,
            "X-RONDO-Eval-Request-Id": f"plan013-{name}",
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
    try:
        response_value = json.loads(payload)
    except (UnicodeError, json.JSONDecodeError):
        response_value = None
    terminal = isinstance(response_value, dict) and response_value.get("status") == "completed"
    usage_valid = _usage_from_json_bytes(payload) is not None
    snapshot = ledger.snapshot()
    request_state = snapshot["runs"][PROBE_RUN_ID]["requests"].get(f"plan013-{name}")
    settled = (
        isinstance(request_state, dict)
        and request_state.get("status") == "settled"
        and request_state.get("usage_valid") is True
    )
    if not terminal or not usage_valid or not settled or snapshot["reserved_usd"] != "0.000000":
        raise ProviderProbeError(f"{name} Responses probe lacked terminal usage settlement")
    return ProviderResponseProbe(
        name=name,
        role=role,
        model=model,
        http_status=status,
        stream=False,
        terminal=terminal,
        usage_valid=usage_valid,
        charged_usd=str(request_state["charged_usd"]),
        attempt_count=int(request_state["attempt_count"]),
        settlement_kind=str(request_state["settlement_kind"]),
    )


def main() -> int:
    try:
        paths = RepoPaths.discover(Path.cwd())
        config = load_runtime_config(paths)
        _secret_name, api_key = load_provider_secret(config)
        receipt = run_provider_probes(
            config,
            api_key,
            output_root=(
                paths.common_root
                / "eval-data"
                / "provider-probes"
                / "plan013-configured-provider-probe-v2"
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
