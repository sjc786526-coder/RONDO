"""Run a bounded configured-model diagnostic against frozen Codex before RONDO.

This is deliberately separate from the benchmark runner.  It exercises the
real CLI request shape while retaining the paid-eval loopback proxy, 1 USD
short-test reservation per upstream request, configured provider profile, and
redacted metadata. Model
selection is explicit and diagnostic-only; production provider selection
continues to come exclusively from ``rondo.local.toml``.
"""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable

from .api_budget_proxy import (
    ApiBudgetProxyError,
    LoopbackResponsesProxy,
    PersistentBudgetLedger,
    SHORT_REQUEST_RESERVATION_USD,
    UPSTREAM_TIMEOUT_SECONDS,
    _atomic_private_json,
    maximum_usage_cost,
)
from .config import ConfigError, RepoPaths, load_provider_secret, load_runtime_config
from .frozen_model_catalog import (
    _legacy_catalog_with_auto_review_override as _catalog_with_auto_review_override,
    load_frozen_model_catalog,
    load_shared_model_catalog,
)


MODEL_CAMPAIGN_CAP_USD = Decimal("150")
RUN_CAP_USD = Decimal("5")
PLAN014_CANARY_CAP_USD = Decimal("4")
MAX_RETRIES_PER_MODEL = 25
OUTER_RETRY_BASE_SECONDS = 5
OUTER_RETRY_MAX_SECONDS = 60
CLIENT_TIMEOUT_SECONDS = 360
MAX_CLI_JSONL_BYTES = 8 * 1024 * 1024
EXPECTED_MAIN_EFFORT = "medium"
EXPECTED_GUARDIAN_EFFORT = "low"
DEFAULT_GUARDIAN_ALIAS = "luna"
SUPPORTED_MAIN_ALIASES = ("luna", "terra", "sol")
_EXPECTED_APPROVAL_COMMANDS = {
    "touch guardian-approved.tmp",
    "/bin/bash -lc 'touch guardian-approved.tmp'",
}


class ModelDiagnosticError(RuntimeError):
    """The diagnostic stopped without exposing provider or response data."""


@dataclass(frozen=True)
class BinaryTarget:
    side: str
    path: Path
    sha256: str
    source_commit: str


@dataclass(frozen=True)
class Phase:
    side: str
    kind: str

    @property
    def name(self) -> str:
        return f"{self.side}-{self.kind}"


PHASES = (
    Phase("codex", "main"),
    Phase("codex", "approval"),
    Phase("rondo", "main"),
    Phase("rondo", "approval"),
)


def _binary_target(
    common_root: Path,
    side: str,
    *,
    manifest_path: Path | None = None,
) -> BinaryTarget:
    if manifest_path is not None:
        manifest = (
            manifest_path
            if manifest_path.is_absolute()
            else common_root / manifest_path
        )
    elif side == "codex":
        manifest = (
            common_root
            / "eval-data/bin/codex"
            / "rust-v0.147.0-be6e8eac029b183056b7e4402879f15d2c85f61b-x86_64-unknown-linux-musl-runtime-bundle"
            / "manifest.json"
        )
    elif side == "rondo":
        manifest = (
            common_root
            / "eval-data/bin/rondo"
            / "cb652e1418e06d53171755963ad9eb8075259ffc-x86_64-unknown-linux-musl-runtime-bundle"
            / "manifest.json"
        )
    else:
        raise ModelDiagnosticError("diagnostic side is invalid")
    if manifest.is_symlink() or not manifest.is_file():
        raise ModelDiagnosticError(f"{side} frozen manifest is unavailable")
    try:
        value = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ModelDiagnosticError(f"{side} frozen manifest is invalid") from exc
    if not isinstance(value, dict):
        raise ModelDiagnosticError(f"{side} frozen manifest is invalid")
    try:
        path = Path(value["path"])
        expected_sha256 = value["sha256"]
        source_commit = value["source_commit"]
    except (KeyError, TypeError) as exc:
        raise ModelDiagnosticError(f"{side} frozen manifest is incomplete") from exc
    if (
        path.is_symlink()
        or not path.is_file()
        or not isinstance(expected_sha256, str)
        or len(expected_sha256) != 64
        or not isinstance(source_commit, str)
        or len(source_commit) != 40
    ):
        raise ModelDiagnosticError(f"{side} frozen binary identity is invalid")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != expected_sha256:
        raise ModelDiagnosticError(f"{side} frozen binary digest differs from its manifest")
    return BinaryTarget(side, path, digest, source_commit)


def _load_frozen_model_catalog(
    paths: RepoPaths,
    target: BinaryTarget,
    *,
    main_model: str,
    guardian_model: str,
) -> dict[str, object]:
    return load_frozen_model_catalog(
        paths.common_root,
        source_commit=target.source_commit,
        main_model=main_model,
        guardian_model=guardian_model,
    ).to_dict()


def _private_directory(path: Path) -> None:
    if path.exists() or path.is_symlink():
        raise ModelDiagnosticError("diagnostic output already exists")
    path.mkdir(parents=True, mode=0o700)
    path.chmod(0o700)


def _write_auth(path: Path, key: str) -> None:
    if not key or "\n" in key or "\r" in key:
        raise ModelDiagnosticError("diagnostic credential is invalid")
    _atomic_private_json(path, {"OPENAI_API_KEY": key})


def _remove_generated_plugin_cache(codex_home: Path) -> None:
    temporary = codex_home / ".tmp"
    if temporary.is_symlink() or not temporary.is_dir():
        return
    for cache in temporary.iterdir():
        if cache.name != "plugins" and not cache.name.startswith("plugins-clone-"):
            continue
        if cache.is_symlink():
            cache.unlink()
        elif cache.is_dir():
            for attempt in range(5):
                try:
                    shutil.rmtree(cache)
                    break
                except FileNotFoundError:
                    break
                except OSError as exc:
                    if exc.errno not in {errno.EEXIST, errno.ENOTEMPTY}:
                        raise
                    if attempt == 4:
                        break
                    time.sleep(0.05)


def _prompt(kind: str) -> str:
    if kind == "main":
        return "Reply with exactly OK. Do not call tools."
    if kind == "approval":
        return (
            "Call the exec_command tool exactly once with these exact arguments: "
            '{"cmd":"touch guardian-approved.tmp","sandbox_permissions":'
            '"require_escalated","justification":"Harmless Guardian diagnostic"}. '
            "Do not emit an assistant or commentary message before the tool call. "
            "Do not call any other tool and do not modify any other path. After the "
            "command succeeds, reply with exactly DONE."
        )
    raise ModelDiagnosticError("diagnostic phase kind is invalid")


def _codex_command(
    target: BinaryTarget,
    *,
    base_url: str,
    phase: Phase,
    main_model: str,
    guardian_model: str,
    main_effort: str = EXPECTED_MAIN_EFFORT,
    guardian_effort: str = EXPECTED_GUARDIAN_EFFORT,
    model_catalog_json: Path | None = None,
) -> list[str]:
    overrides = [
        'approvals_reviewer="auto_review"',
        'approval_policy="on-request"',
        f'sandbox_mode={json.dumps("read-only" if phase.kind == "approval" else "workspace-write")}',
        "sandbox_workspace_write.network_access=true",
        "features.code_mode_host=true",
        'model_provider="rondo_model_diagnostic"',
        'model_providers.rondo_model_diagnostic.name="Configured Provider"',
        f"model_providers.rondo_model_diagnostic.base_url={json.dumps(base_url)}",
        'model_providers.rondo_model_diagnostic.wire_api="responses"',
        "model_providers.rondo_model_diagnostic.requires_openai_auth=true",
        "model_providers.rondo_model_diagnostic.supports_websockets=false",
        "model_providers.rondo_model_diagnostic.request_max_retries=0",
        "model_providers.rondo_model_diagnostic.stream_max_retries=0",
        f"model_reasoning_effort={json.dumps(main_effort)}",
        'service_tier="default"',
    ]
    if target.side == "rondo":
        overrides.extend(
            (
                f"auto_review.model={json.dumps(guardian_model)}",
                f"auto_review.reasoning_effort={json.dumps(guardian_effort)}",
            )
        )
    elif model_catalog_json is not None:
        overrides.append(f"model_catalog_json={json.dumps(str(model_catalog_json))}")
    command = [
        str(target.path),
        "exec",
        "--strict-config",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--model",
        main_model,
        "--json",
        "--enable",
        "unified_exec",
    ]
    for value in overrides:
        command.extend(("-c", value))
    command.extend(("--", _prompt(phase.kind)))
    return command


def _safe_environment(codex_home: Path) -> dict[str, str]:
    # Do not inherit ambient credentials, provider endpoints, proxy settings,
    # hooks, or tool configuration into the evaluated CLI and its children.
    return {
        "CODEX_HOME": str(codex_home),
        "HOME": str(codex_home),
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
    }


def _request_states(snapshot: dict[str, Any], run_id: str) -> list[dict[str, Any]]:
    runs = snapshot.get("runs")
    run = runs.get(run_id) if isinstance(runs, dict) else None
    requests = run.get("requests") if isinstance(run, dict) else None
    if not isinstance(requests, dict):
        return []
    return [
        {**value, "request_id": request_id}
        for request_id, value in requests.items()
        if isinstance(request_id, str) and isinstance(value, dict)
    ]


def _phase_succeeded(
    phase: Phase,
    *,
    returncode: int,
    snapshot: dict[str, Any],
    run_id: str,
    requests: list[dict[str, Any]],
) -> bool:
    runs = snapshot.get("runs")
    run = runs.get(run_id) if isinstance(runs, dict) else None
    states = _request_states(snapshot, run_id)
    if (
        returncode != 0
        or snapshot.get("reserved_usd") != "0.000000"
        or not isinstance(run, dict)
        or run.get("stopped") is not False
        or run.get("stop_reason") is not None
    ):
        return False
    expected_roles = ["main"] if phase.kind == "main" else ["main", "guardian", "main"]
    if [request.get("role") for request in requests] != expected_roles:
        return False
    if len(states) != len(requests):
        return False
    states_by_id = {state.get("request_id"): state for state in states}
    request_ids = [request.get("request_id") for request in requests]
    if (
        any(not isinstance(request_id, str) for request_id in request_ids)
        or len(set(request_ids)) != len(request_ids)
        or set(request_ids) != set(states_by_id)
    ):
        return False
    for request in requests:
        if (
            request.get("role_provenance") != "declared"
            or request.get("declared_role") != request.get("role")
            or request.get("inferred_role") != request.get("role")
            or request.get("contract_match") is not True
            or request.get("usage_valid") is not True
            or request.get("settlement_kind") != "usage_priced"
            or isinstance(request.get("attempt_count"), bool)
            or not isinstance(request.get("attempt_count"), int)
            or request["attempt_count"] < 1
        ):
            return False
        state = states_by_id[request["request_id"]]
        if (
            state.get("status") != "settled"
            or state.get("usage_valid") is not True
            or state.get("settlement_kind") != "usage_priced"
            or state.get("attempt_count") != request.get("attempt_count")
        ):
            return False
    return True


def _requests_from_metadata(path: Path) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return []
    requests = value.get("requests") if isinstance(value, dict) else None
    if not isinstance(requests, list):
        return []
    if not all(isinstance(request, dict) for request in requests):
        return []
    return [dict(request) for request in requests]


def _diagnostic_retryable(
    *,
    success: bool,
    snapshot: dict[str, Any],
    states: Iterable[dict[str, Any]],
) -> bool:
    values = list(states)
    return (
        not success
        and snapshot.get("reserved_usd") == "0.000000"
        and bool(values)
    )


def _outer_retry_delay_seconds(retry_count: int) -> int:
    if isinstance(retry_count, bool) or not isinstance(retry_count, int) or retry_count < 0:
        raise ModelDiagnosticError("diagnostic retry count is invalid")
    exponent = min(retry_count, 4)
    return min(OUTER_RETRY_MAX_SECONDS, OUTER_RETRY_BASE_SECONDS * (2**exponent))


def _max_attempts_for_retry_budget(
    *,
    provider_max_attempts: int,
    retry_count: int,
    max_retries: int,
    phase_attempt: int,
) -> int:
    """Return the bounded upstream attempts for the next CLI invocation.

    The first upstream attempt of the first process is not a retry. Every
    additional proxy attempt and every repeated CLI process consumes one shared
    campaign retry unit.
    """

    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 0
        for value in (provider_max_attempts, retry_count, max_retries, phase_attempt)
    ) or not 1 <= provider_max_attempts <= 5:
        raise ModelDiagnosticError("diagnostic retry budget is invalid")
    remaining = max_retries - retry_count - (1 if phase_attempt else 0)
    if remaining < 0:
        return 0
    return min(provider_max_attempts, remaining + 1)


def _redacted_cli_observation(
    raw: bytes, *, expected_final_message: str | None = None
) -> dict[str, object]:
    if len(raw) > MAX_CLI_JSONL_BYTES:
        raise ModelDiagnosticError("CLI JSONL exceeded the diagnostic size limit")
    event_types: list[str] = []
    command_events: list[dict[str, object]] = []
    agent_messages: list[tuple[int, str]] = []
    turn_completed_indexes: list[int] = []
    turn_failed = False
    for line in raw.splitlines():
        if not line:
            continue
        try:
            value = json.loads(line)
        except (UnicodeError, json.JSONDecodeError):
            raise ModelDiagnosticError("CLI emitted invalid diagnostic JSONL") from None
        if not isinstance(value, dict) or not isinstance(value.get("type"), str):
            raise ModelDiagnosticError("CLI diagnostic event is invalid")
        event_type = value["type"]
        event_types.append(event_type)
        event_index = len(event_types) - 1
        if event_type == "turn.completed":
            turn_completed_indexes.append(event_index)
        elif event_type == "turn.failed":
            turn_failed = True
        item = value.get("item")
        if (
            event_type == "item.completed"
            and isinstance(item, dict)
            and item.get("type") == "agent_message"
            and isinstance(item.get("text"), str)
        ):
            agent_messages.append((event_index, item["text"]))
        if (
            event_type in {"item.started", "item.completed"}
            and isinstance(item, dict)
            and item.get("type") == "command_execution"
        ):
            command = item.get("command")
            item_id = item.get("id")
            command_events.append(
                {
                    "event": event_type,
                    "sequence_index": event_index,
                    "expected_command": command in _EXPECTED_APPROVAL_COMMANDS,
                    "command_sha256": (
                        hashlib.sha256(command.encode()).hexdigest()
                        if isinstance(command, str)
                        else None
                    ),
                    "item_id_sha256": (
                        hashlib.sha256(item_id.encode()).hexdigest()
                        if isinstance(item_id, str) and item_id
                        else None
                    ),
                    "status": item.get("status"),
                    "exit_code": item.get("exit_code"),
                }
            )
    turn_succeeded = not turn_failed and len(turn_completed_indexes) == 1
    exact_final_message = (
        isinstance(expected_final_message, str)
        and len(agent_messages) == 1
        and agent_messages[0][1] == expected_final_message
        and turn_succeeded
        and agent_messages[0][0] < turn_completed_indexes[0]
    )
    approval_command_succeeded = (
        exact_final_message
        and len(command_events) == 2
        and command_events[0]["event"] == "item.started"
        and command_events[0]["status"] == "in_progress"
        and command_events[0]["exit_code"] is None
        and command_events[1]["event"] == "item.completed"
        and command_events[1]["status"] == "completed"
        and command_events[1]["exit_code"] == 0
        and command_events[0]["expected_command"] is True
        and command_events[1]["expected_command"] is True
        and command_events[0]["command_sha256"]
        == command_events[1]["command_sha256"]
        and command_events[0]["item_id_sha256"] is not None
        and command_events[0]["item_id_sha256"]
        == command_events[1]["item_id_sha256"]
        and command_events[0]["sequence_index"]
        < command_events[1]["sequence_index"]
        < agent_messages[0][0]
        < turn_completed_indexes[0]
    )
    return {
        "event_types": event_types,
        "command_events": command_events,
        "turn_succeeded": turn_succeeded,
        "exact_final_message": exact_final_message,
        "approval_command_succeeded": approval_command_succeeded,
    }


def _redacted_attempt(
    *,
    phase: Phase,
    target: BinaryTarget,
    snapshot: dict[str, Any],
    run_id: str,
    requests: list[dict[str, Any]],
    returncode: int,
    duration_seconds: float,
    cli_observation: dict[str, object],
    model_catalog_sha256: str | None,
) -> dict[str, object]:
    states = _request_states(snapshot, run_id)
    return {
        "phase": phase.name,
        "side": phase.side,
        "kind": phase.kind,
        "binary_sha256": target.sha256,
        "binary_source_commit": target.source_commit,
        "returncode": returncode,
        "duration_seconds": round(duration_seconds, 3),
        "cli_observation": cli_observation,
        "model_catalog_sha256": model_catalog_sha256,
        "roles": [request.get("role") for request in requests],
        "logical_request_count": len(states),
        "upstream_attempt_count": sum(
            int(value.get("attempt_count", 0)) for value in states
        ),
        "spent_usd": snapshot["spent_usd"],
        "reserved_usd": snapshot["reserved_usd"],
        "settlements": [
            {
                "status": value.get("status"),
                "charged_usd": value.get("charged_usd"),
                "usage_valid": value.get("usage_valid"),
                "attempt_count": value.get("attempt_count"),
                "settlement_kind": value.get("settlement_kind"),
            }
            for value in states
        ],
    }


def _run_phase_once(
    *,
    phase: Phase,
    target: BinaryTarget,
    provider: Any,
    api_key: str,
    attempt_root: Path,
    max_attempts: int,
    frozen_model_catalog: dict[str, object] | None = None,
    run_cap_usd: Decimal = RUN_CAP_USD,
    max_logical_requests: int | None = None,
    upstream_timeout_seconds: float = UPSTREAM_TIMEOUT_SECONDS,
    request_reservation_usd: Decimal = SHORT_REQUEST_RESERVATION_USD,
    unpriced_fallback_usd: Decimal | str | None = None,
) -> tuple[dict[str, object], bool, bool, int]:
    _private_directory(attempt_root)
    codex_home = attempt_root / "codex-home"
    workspace = attempt_root / "workspace"
    codex_home.mkdir(mode=0o700)
    workspace.mkdir(mode=0o700)
    run_id = f"{phase.name}-{attempt_root.name}"
    ledger_path = attempt_root / "budget.json"
    metadata_path = attempt_root / "api-metadata.json"
    auth_path = codex_home / "auth.json"
    model_catalog_path: Path | None = None
    model_catalog_sha256: str | None = None
    if frozen_model_catalog is not None:
        if target.side != "codex":
            raise ModelDiagnosticError("frozen model catalog was applied to RONDO")
        model_catalog_path = codex_home / "model-catalog.json"
        _atomic_private_json(model_catalog_path, frozen_model_catalog)
        model_catalog_sha256 = hashlib.sha256(model_catalog_path.read_bytes()).hexdigest()
    with PersistentBudgetLedger(
        ledger_path,
        batch_id=run_id,
        total_cap_usd=run_cap_usd,
        max_runs=1,
        default_run_cap_usd=run_cap_usd,
        unpriced_fallback_usd=unpriced_fallback_usd,
    ) as ledger:
        with LoopbackResponsesProxy(
            upstream_base_url=provider.base_url,
            api_key=api_key,
            ledger=ledger,
            run_id=run_id,
            metadata_path=metadata_path,
            main_model=provider.main_model,
            main_effort=provider.main_effort,
            main_pricing=provider.main_pricing,
            guardian_model=provider.guardian_model,
            guardian_pricing=provider.guardian_pricing,
            guardian_effort=provider.guardian_effort,
            max_attempts=max_attempts,
            retry_backoff_seconds=provider.retry_backoff_seconds,
            unbilled_retry_statuses=provider.unbilled_retry_statuses,
            request_reservation_usd=request_reservation_usd,
            max_guardian_logical_requests=1,
            max_logical_requests=max_logical_requests,
            timeout_seconds=upstream_timeout_seconds,
        ) as proxy:
            _write_auth(auth_path, proxy.downstream_api_key)
            started = time.monotonic()
            try:
                with tempfile.TemporaryFile(mode="w+b") as cli_stdout:
                    try:
                        completed = subprocess.run(
                            _codex_command(
                                target,
                                base_url=proxy.base_url,
                                phase=phase,
                                main_model=provider.main_model,
                                guardian_model=provider.guardian_model,
                                main_effort=provider.main_effort,
                                guardian_effort=provider.guardian_effort,
                                model_catalog_json=model_catalog_path,
                            ),
                            cwd=workspace,
                            env=_safe_environment(codex_home),
                            stdin=subprocess.DEVNULL,
                            stdout=cli_stdout,
                            stderr=subprocess.DEVNULL,
                            timeout=CLIENT_TIMEOUT_SECONDS,
                            check=False,
                        )
                        returncode = int(completed.returncode)
                    except subprocess.TimeoutExpired:
                        returncode = 124
                    cli_stdout.seek(0)
                    raw_cli_jsonl = cli_stdout.read(MAX_CLI_JSONL_BYTES + 1)
            finally:
                auth_path.unlink(missing_ok=True)
                _remove_generated_plugin_cache(codex_home)
            duration = time.monotonic() - started
        snapshot = ledger.snapshot()
    requests = _requests_from_metadata(metadata_path)
    cli_observation = _redacted_cli_observation(
        raw_cli_jsonl,
        expected_final_message="OK" if phase.kind == "main" else "DONE",
    )
    states = _request_states(snapshot, run_id)
    success = _phase_succeeded(
        phase,
        returncode=returncode,
        snapshot=snapshot,
        run_id=run_id,
        requests=requests,
    )
    success = success and cli_observation["exact_final_message"] is True
    if phase.kind == "main":
        success = success and cli_observation["command_events"] == []
    else:
        marker = workspace / "guardian-approved.tmp"
        success = (
            success
            and cli_observation["approval_command_succeeded"] is True
            and marker.is_file()
            and not marker.is_symlink()
            and marker.stat().st_size == 0
        )
    # This diagnostic has explicit, task-scoped authorization to repeat an
    # unknown or possibly billed failure.  Every such failure has already
    # consumed its conservative ledger debit, and the per-model 150 USD hard
    # cap is checked before another process is launched. Production benchmark
    # retry semantics remain unchanged.
    retryable = _diagnostic_retryable(
        success=success,
        snapshot=snapshot,
        states=states,
    )
    attempt = _redacted_attempt(
        phase=phase,
        target=target,
        snapshot=snapshot,
        run_id=run_id,
        requests=requests,
        returncode=returncode,
        duration_seconds=duration,
        cli_observation=cli_observation,
        model_catalog_sha256=model_catalog_sha256,
    )
    internal_retries = sum(
        max(0, int(value.get("attempt_count", 0)) - 1) for value in states
    )
    attempt.update(
        {
            "successful": success,
            "retryable": retryable,
            "internal_retries": internal_retries,
        }
    )
    _atomic_private_json(attempt_root / "receipt.json", attempt)
    return attempt, success, retryable, internal_retries


def _run_direct_codex_phase_once(
    *,
    phase: Phase,
    target: BinaryTarget,
    provider: Any,
    api_key: str,
    attempt_root: Path,
) -> tuple[dict[str, object], bool]:
    """Run one frozen Codex phase without the loopback proxy.

    Direct mode is a diagnostic control for provider/client compatibility. It
    deliberately records no response body and makes no usage-priced claim;
    every process consumes one full 5 USD conservative campaign debit.
    """

    if phase.side != "codex":
        raise ModelDiagnosticError("direct diagnostic only supports frozen Codex")
    _private_directory(attempt_root)
    codex_home = attempt_root / "codex-home"
    workspace = attempt_root / "workspace"
    codex_home.mkdir(mode=0o700)
    workspace.mkdir(mode=0o700)
    auth_path = codex_home / "auth.json"
    _write_auth(auth_path, api_key)
    started = time.monotonic()
    try:
        with tempfile.TemporaryFile(mode="w+b") as cli_stdout:
            try:
                completed = subprocess.run(
                    _codex_command(
                        target,
                        base_url=provider.base_url,
                        phase=phase,
                        main_model=provider.main_model,
                        guardian_model=provider.guardian_model,
                    ),
                    cwd=workspace,
                    env=_safe_environment(codex_home),
                    stdin=subprocess.DEVNULL,
                    stdout=cli_stdout,
                    stderr=subprocess.DEVNULL,
                    timeout=CLIENT_TIMEOUT_SECONDS,
                    check=False,
                )
                returncode = int(completed.returncode)
            except subprocess.TimeoutExpired:
                returncode = 124
            cli_stdout.seek(0)
            raw_cli_jsonl = cli_stdout.read(MAX_CLI_JSONL_BYTES + 1)
    finally:
        auth_path.unlink(missing_ok=True)
        _remove_generated_plugin_cache(codex_home)
    duration = time.monotonic() - started
    observation = _redacted_cli_observation(
        raw_cli_jsonl,
        expected_final_message="OK" if phase.kind == "main" else "DONE",
    )
    success = returncode == 0 and observation["exact_final_message"] is True
    if phase.kind == "main":
        success = success and observation["command_events"] == []
    else:
        marker = workspace / "guardian-approved.tmp"
        success = (
            success
            and observation["approval_command_succeeded"] is True
            and marker.is_file()
            and not marker.is_symlink()
            and marker.stat().st_size == 0
        )
    attempt: dict[str, object] = {
        "phase": phase.name,
        "side": phase.side,
        "kind": phase.kind,
        "binary_sha256": target.sha256,
        "binary_source_commit": target.source_commit,
        "returncode": returncode,
        "duration_seconds": round(duration, 3),
        "cli_observation": observation,
        "direct_upstream": True,
        "conservative_debit_usd": format(RUN_CAP_USD, "f"),
        "actual_usd": None,
    }
    _atomic_private_json(attempt_root / "receipt.json", attempt)
    return attempt, success


def run_direct_codex_campaign(
    paths: RepoPaths,
    *,
    output_root: Path,
    main_model_alias: str,
) -> dict[str, object]:
    """Run a direct frozen-Codex main+approval control under 150 USD."""

    if main_model_alias not in SUPPORTED_MAIN_ALIASES:
        raise ModelDiagnosticError("diagnostic main model alias is invalid")
    config = load_runtime_config(paths)
    provider = config.paid_provider_projection()
    paid_eval = config.paid_eval()
    if (
        paid_eval["main_model"] != main_model_alias
        or paid_eval["guardian_model"] != DEFAULT_GUARDIAN_ALIAS
        or provider.main_effort != EXPECTED_MAIN_EFFORT
        or provider.guardian_effort != EXPECTED_GUARDIAN_EFFORT
    ):
        raise ModelDiagnosticError(
            "active paid profile does not match the selected main model and Luna/low Guardian"
        )
    _secret_name, api_key = load_provider_secret(config)
    target = _binary_target(paths.common_root, "codex")
    _private_directory(output_root)
    profile: dict[str, object] = {
        "schema_version": 1,
        "campaign_id": f"direct-{main_model_alias}-cli-diagnostic-v1",
        "evidence_kind": "direct_cli_without_usage_ledger",
        "provider_profile_sha256": provider.profile_sha256,
        "provider_endpoint_sha256": hashlib.sha256(provider.base_url.encode()).hexdigest(),
        "main_model_alias": main_model_alias,
        "main_model": provider.main_model,
        "guardian_model_alias": DEFAULT_GUARDIAN_ALIAS,
        "guardian_model": provider.guardian_model,
        "main_reasoning_effort": EXPECTED_MAIN_EFFORT,
        "guardian_reasoning_effort": EXPECTED_GUARDIAN_EFFORT,
        "campaign_cap_usd": format(MODEL_CAMPAIGN_CAP_USD, "f"),
        "max_retries": MAX_RETRIES_PER_MODEL,
        "actual_usd": None,
    }
    _atomic_private_json(output_root / "profile.json", profile)
    attempts: list[dict[str, object]] = []
    conservative_debit = Decimal(0)
    retry_count = 0
    status = "completed"
    stopped_phase: str | None = None
    for phase in (Phase("codex", "main"), Phase("codex", "approval")):
        phase_attempt = 0
        while True:
            if conservative_debit + RUN_CAP_USD > MODEL_CAMPAIGN_CAP_USD:
                status = "budget_exhausted"
                stopped_phase = phase.name
                break
            attempt_root = output_root / f"{len(attempts) + 1:03d}-{phase.name}"
            attempt, success = _run_direct_codex_phase_once(
                phase=phase,
                target=target,
                provider=provider,
                api_key=api_key,
                attempt_root=attempt_root,
            )
            attempts.append(attempt)
            conservative_debit += RUN_CAP_USD
            retry_count += 1 if phase_attempt else 0
            _atomic_private_json(
                output_root / "receipt.json",
                {
                    **profile,
                    "status": "running",
                    "retry_count": retry_count,
                    "estimated_spent_usd": format(conservative_debit, "f"),
                    "attempts": attempts,
                },
            )
            if success:
                break
            if retry_count >= MAX_RETRIES_PER_MODEL:
                status = "failed"
                stopped_phase = phase.name
                break
            time.sleep(_outer_retry_delay_seconds(retry_count))
            phase_attempt += 1
        if status != "completed":
            break
    receipt = {
        **profile,
        "status": status,
        "stopped_phase": stopped_phase,
        "retry_count": retry_count,
        "estimated_spent_usd": format(conservative_debit, "f"),
        "attempts": attempts,
    }
    _atomic_private_json(output_root / "receipt.json", receipt)
    return receipt


def _selected_campaign_phases(
    *,
    start_side: str,
    phase_kind: str | None,
    plan014_canary: bool,
    formal_campaign_canary: bool = False,
) -> tuple[Phase, ...]:
    phases = (
        tuple(phase for phase in PHASES if phase.side == "codex")
        if plan014_canary or formal_campaign_canary
        else (
            PHASES
            if start_side == "codex"
            else tuple(phase for phase in PHASES if phase.side == "rondo")
        )
    )
    if phase_kind is not None:
        phases = tuple(phase for phase in phases if phase.kind == phase_kind)
    return phases


def _phase_budget_contract(
    phase: Phase,
    *,
    plan014_canary: bool,
    formal_request_reservation_usd: Decimal | None = None,
) -> tuple[Decimal, int | None]:
    if not plan014_canary:
        if formal_request_reservation_usd is None:
            return RUN_CAP_USD, None
        logical_requests = 1 if phase.kind == "main" else 3
        return formal_request_reservation_usd * logical_requests, logical_requests
    logical_requests = 1 if phase.kind == "main" else 3
    return Decimal(logical_requests), logical_requests


def _recover_unrecorded_formal_attempt(
    output_root: Path,
    *,
    attempts: list[dict[str, object]],
    request_reservation_usd: Decimal,
) -> tuple[dict[str, object] | None, int]:
    """Settle the one attempt directory a killed wire process did not publish."""

    indexed: dict[int, Path] = {}
    for child in output_root.iterdir():
        match = re.fullmatch(r"([0-9]{3})-(codex-(?:main|approval))", child.name)
        if match is None:
            continue
        if child.is_symlink() or not child.is_dir():
            raise ModelDiagnosticError("formal wire attempt directory is unsafe")
        indexed[int(match.group(1))] = child
    expected = len(attempts) + 1
    extras = sorted(index for index in indexed if index > len(attempts))
    if not extras:
        return None, 0
    if extras != [expected]:
        raise ModelDiagnosticError("formal wire attempt sequence is ambiguous")
    root = indexed[expected]
    phase_name = root.name[4:]
    phase = next(
        (item for item in PHASES if item.name == phase_name),
        None,
    )
    if phase is None or phase.side != "codex":
        raise ModelDiagnosticError("formal wire interrupted phase is invalid")
    attempt_receipt = root / "receipt.json"
    if attempt_receipt.is_file() and not attempt_receipt.is_symlink():
        try:
            value = json.loads(attempt_receipt.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ModelDiagnosticError("formal wire attempt receipt is invalid") from exc
        if not isinstance(value, dict) or value.get("phase") != phase.name:
            raise ModelDiagnosticError("formal wire attempt receipt differs")
        return value, int(value.get("internal_retries", 0)) + (
            1
            if any(
                item.get("phase") == phase.name
                and int(item.get("upstream_attempt_count", 0)) > 0
                for item in attempts
            )
            else 0
        )
    logical_requests = 1 if phase.kind == "main" else 3
    run_cap = request_reservation_usd * logical_requests
    ledger_path = root / "budget.json"
    if ledger_path.exists() or ledger_path.is_symlink():
        run_id = f"{phase.name}-{root.name}"
        with PersistentBudgetLedger(
            ledger_path,
            batch_id=run_id,
            total_cap_usd=run_cap,
            max_runs=1,
            default_run_cap_usd=run_cap,
            unpriced_fallback_usd="1.000000",
        ) as ledger:
            snapshot = ledger.snapshot()
        states = _request_states(snapshot, run_id)
        spent = Decimal(str(snapshot["spent_usd"]))
        internal_retries = sum(
            max(0, int(item.get("attempt_count", 0)) - 1) for item in states
        )
        settlements = [
            {
                "status": item.get("status"),
                "charged_usd": item.get("charged_usd"),
                "usage_valid": item.get("usage_valid"),
                "attempt_count": item.get("attempt_count"),
                "settlement_kind": item.get("settlement_kind"),
            }
            for item in states
        ]
    else:
        spent = Decimal("0.000000")
        internal_retries = 0
        states = []
        settlements = [
            {
                "status": "settled",
                "charged_usd": "0.000000",
                "usage_valid": False,
                "attempt_count": 0,
                "settlement_kind": "not_sent_unbilled",
            }
        ]
    recovered: dict[str, object] = {
        "phase": phase.name,
        "side": phase.side,
        "kind": phase.kind,
        "returncode": 125,
        "duration_seconds": 0.0,
        "logical_request_count": len(states),
        "upstream_attempt_count": sum(
            int(item.get("attempt_count", 0)) for item in states
        ),
        "spent_usd": f"{spent:.6f}",
        "reserved_usd": "0.000000",
        "settlements": settlements,
        "successful": False,
        "retryable": True,
        "internal_retries": internal_retries,
        "interrupted_recovery": True,
    }
    _atomic_private_json(attempt_receipt, recovered)
    return recovered, internal_retries + (
        1
        if states
        and any(
            item.get("phase") == phase.name
            and int(item.get("upstream_attempt_count", 0)) > 0
            for item in attempts
        )
        else 0
    )


def run_campaign(
    paths: RepoPaths,
    *,
    output_root: Path,
    prior_debit_usd: Decimal = Decimal(0),
    prior_retry_count: int = 0,
    start_side: str = "codex",
    phase_kind: str | None = None,
    main_model_alias: str,
    guardian_model_alias: str = DEFAULT_GUARDIAN_ALIAS,
    max_retries: int = MAX_RETRIES_PER_MODEL,
    plan014_canary: bool = False,
    formal_campaign_canary: bool = False,
    resume_existing: bool = False,
    p2_campaign_identity: object | None = None,
) -> dict[str, object]:
    if prior_debit_usd < 0 or prior_debit_usd >= MODEL_CAMPAIGN_CAP_USD:
        raise ModelDiagnosticError(
            "prior diagnostic debit is outside the campaign cap"
        )
    if (
        isinstance(max_retries, bool)
        or not isinstance(max_retries, int)
        or not 0 <= max_retries <= MAX_RETRIES_PER_MODEL
    ):
        raise ModelDiagnosticError("diagnostic max retries is invalid")
    if (
        isinstance(prior_retry_count, bool)
        or not isinstance(prior_retry_count, int)
        or not 0 <= prior_retry_count <= max_retries
    ):
        raise ModelDiagnosticError("prior diagnostic retry count is invalid")
    if start_side not in {"codex", "rondo"}:
        raise ModelDiagnosticError("diagnostic start side is invalid")
    if phase_kind not in {None, "main", "approval"}:
        raise ModelDiagnosticError("diagnostic phase kind is invalid")
    if main_model_alias not in SUPPORTED_MAIN_ALIASES:
        raise ModelDiagnosticError("diagnostic main model alias is invalid")
    if guardian_model_alias not in SUPPORTED_MAIN_ALIASES:
        raise ModelDiagnosticError("diagnostic Guardian model alias is invalid")
    if plan014_canary and (
        prior_debit_usd != 0
        or prior_retry_count != 0
        or start_side != "codex"
        or phase_kind is not None
        or max_retries != 0
    ):
        raise ModelDiagnosticError(
            "Plan 014 canary requires fresh frozen-Codex main+approval with zero retries"
        )
    if plan014_canary and formal_campaign_canary:
        raise ModelDiagnosticError("wire canary modes are mutually exclusive")
    if resume_existing and not formal_campaign_canary:
        raise ModelDiagnosticError("only a formal wire canary may resume in place")
    if formal_campaign_canary and (
        p2_campaign_identity is None
        or prior_debit_usd != 0
        or prior_retry_count != 0
        or start_side != "codex"
        or phase_kind is not None
    ):
        raise ModelDiagnosticError(
            "formal campaign canary requires a fresh P2 identity and Codex start"
        )
    if p2_campaign_identity is not None and not (
        plan014_canary or formal_campaign_canary
    ):
        raise ModelDiagnosticError("P2 identity is valid only for an exact-wire canary")
    config = load_runtime_config(paths)
    if formal_campaign_canary:
        try:
            provider = p2_campaign_identity.provider_projection(config)
        except (AttributeError, ValueError) as exc:
            raise ModelDiagnosticError("formal P2 canary identity is invalid") from exc
        if (
            provider.main_model != f"gpt-5.6-{main_model_alias}"
            or provider.guardian_model != f"gpt-5.6-{guardian_model_alias}"
        ):
            raise ModelDiagnosticError("formal wire model differs from its identity")
    else:
        provider = config.paid_provider_projection()
        paid_eval = config.paid_eval()
        if (
            paid_eval["main_model"] != main_model_alias
            or paid_eval["guardian_model"] != guardian_model_alias
            or provider.main_effort != EXPECTED_MAIN_EFFORT
            or provider.guardian_effort != EXPECTED_GUARDIAN_EFFORT
        ):
            raise ModelDiagnosticError(
                "active paid profile does not match the selected main/Guardian models and effort"
            )
    pair_identity = None
    campaign_identity = None
    if plan014_canary or formal_campaign_canary:
        if p2_campaign_identity is None:
            from .terminal_bench.pair import load_active_pair_identity

            pair_identity = load_active_pair_identity()
            pair_identity.validate_selected_profile(provider)
        else:
            campaign_identity = p2_campaign_identity
            try:
                campaign_identity.validate_provider(provider)
            except AttributeError as exc:
                raise ModelDiagnosticError("P2 canary identity is invalid") from exc
    _secret_name, api_key = load_provider_secret(config)
    targets = {}
    for side in ("codex", "rondo"):
        manifest_path = None
        if formal_campaign_canary:
            try:
                manifest_path = Path(
                    campaign_identity.bundles[side]["manifest_path"]
                )
            except (AttributeError, KeyError, TypeError) as exc:
                raise ModelDiagnosticError("formal wire bundle identity is invalid") from exc
        targets[side] = (
            _binary_target(
                paths.common_root,
                side,
                manifest_path=manifest_path,
            )
            if manifest_path is not None
            else _binary_target(paths.common_root, side)
        )
    if formal_campaign_canary:
        try:
            sources = {
                str(item["side"]): item
                for item in campaign_identity.catalog_identity["sources"]
            }
            shared_catalog = load_shared_model_catalog(
                paths.common_root,
                upstream_source_commit=str(sources["upstream"]["commit"]),
                rondo_source_commit=str(sources["rondo"]["commit"]),
                main_model=provider.main_model,
                guardian_model=provider.guardian_model,
                product=campaign_identity.product,
            )
            campaign_identity.validate_shared_model_catalog(shared_catalog.identity())
            frozen_model_catalog = shared_catalog.to_dict()
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ModelDiagnosticError("formal shared model catalog is invalid") from exc
    else:
        frozen_model_catalog = (
            _load_frozen_model_catalog(
                paths,
                targets["codex"],
                main_model=provider.main_model,
                guardian_model=provider.guardian_model,
            )
            if start_side == "codex"
            else None
        )
    frozen_model_catalog_sha256 = (
        hashlib.sha256(
            (
                json.dumps(
                    frozen_model_catalog,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode()
        ).hexdigest()
        if frozen_model_catalog is not None
        else None
    )
    if campaign_identity is not None and not formal_campaign_canary:
        campaign_identity.validate_frozen_model_catalog(
            source_commit=targets["codex"].source_commit,
            sha256=frozen_model_catalog_sha256,
            main_model=provider.main_model,
            guardian_model=provider.guardian_model,
        )
    upstream_timeout_seconds = (
        campaign_identity.upstream_timeout_seconds
        if campaign_identity is not None
        else UPSTREAM_TIMEOUT_SECONDS
    )
    formal_request_reservation_usd = None
    formal_campaign_cap_usd = None
    if formal_campaign_canary:
        formal_request_reservation_usd = max(
            maximum_usage_cost(provider.main_pricing),
            maximum_usage_cost(provider.guardian_pricing),
        ).quantize(Decimal("0.000001"))
        if (
            formal_request_reservation_usd
            != campaign_identity.maximum_legal_request_reservation_usd
        ):
            raise ModelDiagnosticError("formal wire reservation differs from identity")
        formal_campaign_cap_usd = (
            Decimal(str(campaign_identity.budget["task_budget_cap_usd"]))
            - Decimal(
                str(campaign_identity.budget["task_budget_prior_estimated_usd"])
            )
        )
    profile = {
        "schema_version": 1,
        "campaign_id": f"{main_model_alias}-cli-diagnostic-v1",
        "provider_profile_sha256": provider.profile_sha256,
        "provider_endpoint_sha256": hashlib.sha256(provider.base_url.encode()).hexdigest(),
        "main_model_alias": main_model_alias,
        "main_model": provider.main_model,
        "guardian_model_alias": guardian_model_alias,
        "guardian_model": provider.guardian_model,
        "main_reasoning_effort": provider.main_effort,
        "guardian_reasoning_effort": provider.guardian_effort,
        "codex_model_catalog_sha256": frozen_model_catalog_sha256,
        "codex_auto_review_model_override": (
            provider.guardian_model if frozen_model_catalog is not None else None
        ),
        "request_reservation_usd": format(
            formal_request_reservation_usd or SHORT_REQUEST_RESERVATION_USD,
            "f",
        ),
        "max_guardian_logical_requests": (
            campaign_identity.max_guardian_logical_requests
            if formal_campaign_canary
            else 1
        ),
        "campaign_cap_usd": format(
            PLAN014_CANARY_CAP_USD
            if plan014_canary
            else (formal_campaign_cap_usd or MODEL_CAMPAIGN_CAP_USD),
            "f",
        ),
        "plan014_canary": plan014_canary,
        "formal_campaign_canary": formal_campaign_canary,
        "pair_id": pair_identity.pair_id if pair_identity is not None else None,
        "pair_lock_sha256": (
            pair_identity.lock_sha256 if pair_identity is not None else None
        ),
        "p2_campaign_id": (
            campaign_identity.campaign_id if campaign_identity is not None else None
        ),
        "p2_campaign_lock_sha256": (
            campaign_identity.lock_sha256 if campaign_identity is not None else None
        ),
        "prior_diagnostic_debit_usd": format(prior_debit_usd, "f"),
        "prior_retry_count": prior_retry_count,
        "start_side": start_side,
        "phase_kind": phase_kind,
        "max_retries": max_retries,
        "actual_usd": None,
        "provider_upstream_timeout_seconds": upstream_timeout_seconds,
    }
    if resume_existing:
        if output_root.is_symlink() or not output_root.is_dir():
            raise ModelDiagnosticError("formal wire output is unavailable for resume")
        try:
            existing_profile = json.loads(
                (output_root / "profile.json").read_text(encoding="utf-8")
            )
            existing_receipt = json.loads(
                (output_root / "receipt.json").read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ModelDiagnosticError("formal wire resume state is invalid") from exc
        if existing_profile != profile or not isinstance(existing_receipt, dict):
            raise ModelDiagnosticError("formal wire resume profile drifted")
        if existing_receipt.get("status") == "completed":
            return existing_receipt
        if existing_receipt.get("status") != "running":
            raise ModelDiagnosticError("formal wire receipt is not resumable")
        raw_attempts = existing_receipt.get("attempts")
        if not isinstance(raw_attempts, list) or any(
            not isinstance(item, dict) for item in raw_attempts
        ):
            raise ModelDiagnosticError("formal wire attempts are invalid")
        attempts = list(raw_attempts)
        try:
            retry_count = int(existing_receipt["retry_count"])
            conservative_spent = Decimal(
                str(existing_receipt["estimated_spent_usd"])
            )
        except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
            raise ModelDiagnosticError("formal wire accounting is invalid") from exc
    else:
        _private_directory(output_root)
        _atomic_private_json(output_root / "profile.json", profile)
        attempts = []
        retry_count = prior_retry_count
        conservative_spent = prior_debit_usd
        _atomic_private_json(
            output_root / "receipt.json",
            {
                **profile,
                "status": "running",
                "retry_count": retry_count,
                "estimated_spent_usd": format(conservative_spent, "f"),
                "attempts": attempts,
            },
        )
    if formal_campaign_canary:
        assert formal_request_reservation_usd is not None
        recovered, retry_delta = _recover_unrecorded_formal_attempt(
            output_root,
            attempts=attempts,
            request_reservation_usd=formal_request_reservation_usd,
        )
        if recovered is not None:
            attempts.append(recovered)
            retry_count += retry_delta
            conservative_spent += Decimal(str(recovered["spent_usd"]))
            _atomic_private_json(
                output_root / "receipt.json",
                {
                    **profile,
                    "status": "running",
                    "retry_count": retry_count,
                    "estimated_spent_usd": format(conservative_spent, "f"),
                    "attempts": attempts,
                },
            )
    status = "completed"
    stopped_phase: str | None = None
    selected_phases = _selected_campaign_phases(
        start_side=start_side,
        phase_kind=phase_kind,
        plan014_canary=plan014_canary,
        formal_campaign_canary=formal_campaign_canary,
    )
    for phase in selected_phases:
        prior_phase_attempts = [
            item for item in attempts if item.get("phase") == phase.name
        ]
        if any(item.get("successful") is True for item in prior_phase_attempts):
            continue
        phase_attempt = (
            sum(
                1
                for item in prior_phase_attempts
                if int(item.get("upstream_attempt_count", 0)) > 0
            )
            if formal_campaign_canary
            else len(prior_phase_attempts)
        )
        phase_run_cap, phase_logical_request_cap = _phase_budget_contract(
            phase,
            plan014_canary=plan014_canary,
            formal_request_reservation_usd=formal_request_reservation_usd,
        )
        campaign_cap = (
            PLAN014_CANARY_CAP_USD
            if plan014_canary
            else (formal_campaign_cap_usd or MODEL_CAMPAIGN_CAP_USD)
        )
        while True:
            if conservative_spent + phase_run_cap > campaign_cap:
                status = "budget_exhausted"
                stopped_phase = phase.name
                break
            bounded_attempts = _max_attempts_for_retry_budget(
                provider_max_attempts=provider.max_attempts,
                retry_count=retry_count,
                max_retries=max_retries,
                phase_attempt=phase_attempt,
            )
            if bounded_attempts == 0:
                status = "failed"
                stopped_phase = phase.name
                break
            attempt_root = output_root / f"{len(attempts) + 1:03d}-{phase.name}"
            attempt, success, retryable, internal_retries = _run_phase_once(
                phase=phase,
                target=targets[phase.side],
                provider=provider,
                api_key=api_key,
                attempt_root=attempt_root,
                max_attempts=bounded_attempts,
                frozen_model_catalog=(
                    frozen_model_catalog if phase.side == "codex" else None
                ),
                run_cap_usd=phase_run_cap,
                max_logical_requests=phase_logical_request_cap,
                upstream_timeout_seconds=upstream_timeout_seconds,
                request_reservation_usd=(
                    formal_request_reservation_usd
                    or SHORT_REQUEST_RESERVATION_USD
                ),
                unpriced_fallback_usd=(
                    "1.000000" if formal_campaign_canary else None
                ),
            )
            attempts.append(attempt)
            conservative_spent += Decimal(str(attempt["spent_usd"]))
            retry_count += internal_retries + (1 if phase_attempt else 0)
            _atomic_private_json(
                output_root / "receipt.json",
                {
                    **profile,
                    "status": "running",
                    "retry_count": retry_count,
                    "estimated_spent_usd": format(conservative_spent, "f"),
                    "attempts": attempts,
                },
            )
            if retry_count > max_retries:
                status = "retry_limit_exceeded"
                stopped_phase = phase.name
                break
            if success:
                break
            if not retryable or retry_count >= max_retries:
                status = "failed"
                stopped_phase = phase.name
                break
            time.sleep(_outer_retry_delay_seconds(retry_count))
            phase_attempt += 1
        if status != "completed":
            break
    receipt = {
        **profile,
        "status": status,
        "stopped_phase": stopped_phase,
        "retry_count": retry_count,
        "estimated_spent_usd": format(conservative_spent, "f"),
        "attempts": attempts,
    }
    if plan014_canary and status == "completed" and (
        [attempt.get("phase") for attempt in attempts]
        != ["codex-main", "codex-approval"]
        or [attempt.get("logical_request_count") for attempt in attempts] != [1, 3]
        or any(
            attempt.get("upstream_attempt_count")
            != attempt.get("logical_request_count")
            for attempt in attempts
        )
        or conservative_spent > PLAN014_CANARY_CAP_USD
    ):
        receipt["status"] = "failed"
        receipt["stopped_phase"] = "canary_contract"
    _atomic_private_json(output_root / "receipt.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bounded frozen-Codex-then-RONDO configured-model diagnostic"
    )
    parser.add_argument(
        "--main-model-alias", choices=SUPPORTED_MAIN_ALIASES, required=True
    )
    parser.add_argument(
        "--guardian-model-alias",
        choices=SUPPORTED_MAIN_ALIASES,
        default=DEFAULT_GUARDIAN_ALIAS,
    )
    parser.add_argument(
        "--direct-upstream",
        action="store_true",
        help="run a frozen-Codex control without the loopback proxy",
    )
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--prior-debit-usd", type=Decimal, default=Decimal(0))
    parser.add_argument("--prior-retry-count", type=int, default=0)
    parser.add_argument(
        "--max-retries", type=int, default=MAX_RETRIES_PER_MODEL
    )
    parser.add_argument("--start-side", choices=("codex", "rondo"), default="codex")
    parser.add_argument("--phase-kind", choices=("main", "approval"))
    parser.add_argument(
        "--plan014-canary",
        action="store_true",
        help="run the fresh frozen-Codex four-request canary under the active pair lock",
    )
    args = parser.parse_args()
    try:
        paths = RepoPaths.discover(Path.cwd())
        default_name = (
            f"direct-{args.main_model_alias}-cli-diagnostic-v1"
            if args.direct_upstream
            else f"{args.main_model_alias}-cli-diagnostic-v1"
        )
        output_root = args.output_root or (
            paths.common_root / "eval-data/provider-probes" / default_name
        )
        if args.direct_upstream:
            if (
                args.prior_debit_usd != 0
                or args.prior_retry_count != 0
                or args.max_retries != MAX_RETRIES_PER_MODEL
                or args.start_side != "codex"
                or args.phase_kind is not None
                or args.guardian_model_alias != DEFAULT_GUARDIAN_ALIAS
                or args.plan014_canary
            ):
                raise ModelDiagnosticError(
                    "direct diagnostic does not accept continuation or phase selection"
                )
            receipt = run_direct_codex_campaign(
                paths,
                output_root=output_root,
                main_model_alias=args.main_model_alias,
            )
        else:
            receipt = run_campaign(
                paths,
                output_root=output_root,
                prior_debit_usd=args.prior_debit_usd,
                prior_retry_count=args.prior_retry_count,
                start_side=args.start_side,
                phase_kind=args.phase_kind,
                main_model_alias=args.main_model_alias,
                guardian_model_alias=args.guardian_model_alias,
                max_retries=args.max_retries,
                plan014_canary=args.plan014_canary,
            )
        print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
        return 0 if receipt["status"] == "completed" else 1
    except (
        ApiBudgetProxyError,
        ConfigError,
        ModelDiagnosticError,
        OSError,
        ValueError,
    ) as exc:
        reason = str(exc)
        if not reason or any(character in reason for character in "\r\n\0"):
            reason = "configured-model diagnostic failed"
        print(json.dumps({"status": "failed", "reason": reason}, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
