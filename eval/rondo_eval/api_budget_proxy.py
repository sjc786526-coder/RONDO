"""Loopback-only Responses proxy with fail-closed API budget accounting.

The runner must opt in to this proxy explicitly.  It accepts a validated official
OpenAI base URL and an API key already loaded into memory; neither value is read
from disk here.  Request bodies are forwarded, but only redacted shape metadata
and the request-body digest are persisted.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import secrets
import socket
import stat
import threading
import uuid
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_UP
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


OFFICIAL_MODEL = "gpt-5.6-luna"
PRICE_SNAPSHOT_DATE = "2026-08-10"
PRICE_SOURCE_URL = "https://developers.openai.com/api/docs/models/gpt-5.6-luna"
INPUT_USD_PER_MILLION = Decimal("0.20")
CACHED_INPUT_USD_PER_MILLION = Decimal("0.02")
OUTPUT_USD_PER_MILLION = Decimal("1.20")
LONG_CONTEXT_THRESHOLD = 272_000
LONG_INPUT_MULTIPLIER = Decimal("2")
LONG_OUTPUT_MULTIPLIER = Decimal("1.5")
CACHE_WRITE_MULTIPLIER = Decimal("1.25")
MAX_INPUT_TOKENS = 1_050_000
MAX_OUTPUT_TOKENS = 128_000
BATCH_CAP_USD = Decimal("20.00")
RUN_CAP_USD = Decimal("5.00")
MAX_BENCHMARK_RUNS = 4
_MONEY_QUANTUM = Decimal("0.000001")
_MAX_REQUEST_BYTES = 16 * 1024 * 1024
_MAX_RESPONSE_BYTES = 64 * 1024 * 1024
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_HOSTED_TOOL_TYPES = {
    "web_search",
    "web_search_preview",
    "file_search",
    "computer",
    "computer_use_preview",
    "code_interpreter",
    "image_generation",
    "local_shell",
    "shell",
    "mcp",
}
_RETRY_HEADERS = (
    "x-stainless-retry-count",
    "x-retry-count",
    "x-rondo-eval-attempt",
)
_LITE_HEADER = "x-openai-internal-codex-responses-lite"
GUARDIAN_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "risk_level": {
            "type": "string",
            "enum": ["low", "medium", "high", "critical"],
        },
        "user_authorization": {
            "type": "string",
            "enum": ["unknown", "low", "medium", "high"],
        },
        "outcome": {"type": "string", "enum": ["allow", "deny"]},
        "rationale": {"type": "string"},
    },
    "required": ["outcome"],
}
_METADATA_LOCKS_GUARD = threading.Lock()
_METADATA_LOCKS: dict[str, threading.Lock] = {}


class ApiBudgetProxyError(ValueError):
    """Raised when the proxy or its persistent state is unsafe or invalid."""


class BudgetStopped(ApiBudgetProxyError):
    """Raised before forwarding when an authorization limit is exhausted."""


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    cached_input_tokens: int
    cache_write_input_tokens: int
    output_tokens: int

    def validate(self) -> None:
        values = (
            self.input_tokens,
            self.cached_input_tokens,
            self.cache_write_input_tokens,
            self.output_tokens,
        )
        if any(isinstance(value, bool) or not isinstance(value, int) for value in values):
            raise ApiBudgetProxyError("usage token counts must be integers")
        if any(value < 0 for value in values):
            raise ApiBudgetProxyError("usage token counts must be non-negative")
        if self.cached_input_tokens + self.cache_write_input_tokens > self.input_tokens:
            raise ApiBudgetProxyError("usage input-token details exceed input tokens")
        if self.input_tokens > MAX_INPUT_TOKENS or self.output_tokens > MAX_OUTPUT_TOKENS:
            raise ApiBudgetProxyError("usage exceeds the frozen request bounds")


@dataclass(frozen=True)
class Settlement:
    charged_usd: Decimal
    usage_valid: bool
    run_stopped: bool


def price_usage(usage: Usage) -> Decimal:
    """Price one Luna request using the frozen Standard rates."""

    usage.validate()
    long_context = usage.input_tokens > LONG_CONTEXT_THRESHOLD
    input_multiplier = LONG_INPUT_MULTIPLIER if long_context else Decimal(1)
    output_multiplier = LONG_OUTPUT_MULTIPLIER if long_context else Decimal(1)
    uncached = usage.input_tokens - usage.cached_input_tokens - usage.cache_write_input_tokens
    input_cost = (
        Decimal(uncached) * INPUT_USD_PER_MILLION
        + Decimal(usage.cached_input_tokens) * CACHED_INPUT_USD_PER_MILLION
        + Decimal(usage.cache_write_input_tokens)
        * INPUT_USD_PER_MILLION
        * CACHE_WRITE_MULTIPLIER
    ) * input_multiplier
    output_cost = Decimal(usage.output_tokens) * OUTPUT_USD_PER_MILLION * output_multiplier
    return ((input_cost + output_cost) / Decimal(1_000_000)).quantize(
        _MONEY_QUANTUM, rounding=ROUND_UP
    )


MAX_REQUEST_RESERVATION_USD = price_usage(
    Usage(
        input_tokens=MAX_INPUT_TOKENS,
        cached_input_tokens=0,
        cache_write_input_tokens=MAX_INPUT_TOKENS,
        output_tokens=MAX_OUTPUT_TOKENS,
    )
)


class PersistentBudgetLedger:
    """Thread-safe, atomically persisted budget state for one benchmark batch."""

    def __init__(
        self,
        path: Path,
        *,
        batch_id: str,
        total_cap_usd: Decimal | str = BATCH_CAP_USD,
        max_runs: int = MAX_BENCHMARK_RUNS,
        default_run_cap_usd: Decimal | str = RUN_CAP_USD,
    ):
        _require_safe_id(batch_id, "batch id")
        self.path = Path(path)
        self.batch_id = batch_id
        self.total_cap = _money(total_cap_usd)
        self.default_run_cap = _money(default_run_cap_usd)
        self.max_runs = max_runs
        if self.total_cap <= 0 or self.total_cap > BATCH_CAP_USD:
            raise ApiBudgetProxyError("batch cap exceeds the authorized 20 USD maximum")
        if self.default_run_cap <= 0 or self.default_run_cap > RUN_CAP_USD:
            raise ApiBudgetProxyError("run cap exceeds the authorized 5 USD maximum")
        if not isinstance(max_runs, int) or isinstance(max_runs, bool) or not 1 <= max_runs <= 4:
            raise ApiBudgetProxyError("benchmark run count exceeds the authorized maximum of four")
        self._lock = threading.RLock()
        self._closed = False
        self._prepare_parent()
        self._lock_path = self.path.with_name(f".{self.path.name}.lock")
        self._lock_fd = self._acquire_process_lock()
        try:
            if _path_present(self.path):
                self._state = self._read_state()
                self._recover_reserved_requests()
            else:
                self._state = {
                    "schema_version": 1,
                    "batch_id": self.batch_id,
                    "total_cap_usd": _money_text(self.total_cap),
                    "max_runs": self.max_runs,
                    "default_run_cap_usd": _money_text(self.default_run_cap),
                    "runs": {},
                }
                self._persist()
        except Exception:
            self.close()
            raise

    def __enter__(self) -> PersistentBudgetLedger:
        return self

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def close(self) -> None:
        if getattr(self, "_closed", True):
            return
        self._closed = True
        try:
            import fcntl

            fcntl.flock(self._lock_fd, fcntl.LOCK_UN)
        finally:
            os.close(self._lock_fd)

    def ensure_run(self, run_id: str, *, cap_usd: Decimal | str | None = None) -> None:
        self._register_run(run_id, cap_usd=cap_usd, reject_existing=False)

    def claim_run(self, run_id: str, *, cap_usd: Decimal | str | None = None) -> None:
        """Consume one benchmark invocation slot, rejecting every reused run id."""

        self._register_run(run_id, cap_usd=cap_usd, reject_existing=True)

    def _register_run(
        self,
        run_id: str,
        *,
        cap_usd: Decimal | str | None,
        reject_existing: bool,
    ) -> None:
        _require_safe_id(run_id, "run id")
        cap = self.default_run_cap if cap_usd is None else _money(cap_usd)
        if cap <= 0 or cap > self.default_run_cap:
            raise ApiBudgetProxyError("run cap exceeds the configured per-run maximum")
        with self._lock:
            self._assert_open()
            runs = self._state["runs"]
            if run_id in runs:
                if reject_existing:
                    raise BudgetStopped("benchmark run id was already consumed")
                if Decimal(runs[run_id]["cap_usd"]) != cap:
                    raise ApiBudgetProxyError("existing run cap differs from the requested cap")
                return
            if len(runs) >= self.max_runs:
                raise BudgetStopped("benchmark run limit is exhausted")
            runs[run_id] = {
                "cap_usd": _money_text(cap),
                "spent_usd": _money_text(Decimal(0)),
                "stopped": False,
                "stop_reason": None,
                "requests": {},
            }
            self._persist()

    def reserve(
        self,
        run_id: str,
        request_id: str,
        amount_usd: Decimal | str = MAX_REQUEST_RESERVATION_USD,
    ) -> Decimal:
        _require_safe_id(run_id, "run id")
        _require_safe_id(request_id, "request id")
        amount = _money(amount_usd)
        if amount <= 0 or amount > MAX_REQUEST_RESERVATION_USD:
            raise ApiBudgetProxyError("request reservation exceeds the frozen maximum")
        with self._lock:
            self._assert_open()
            run = self._require_run(run_id)
            if run["stopped"]:
                raise BudgetStopped("benchmark run is stopped")
            if request_id in run["requests"]:
                raise BudgetStopped("request id was already used; retries are disabled")
            run_spent = Decimal(run["spent_usd"])
            run_reserved = _reserved_total(run)
            batch_spent, batch_reserved = self._totals()
            if run_spent + run_reserved + amount > Decimal(run["cap_usd"]):
                raise BudgetStopped("request reservation would exceed the run cost cap")
            if batch_spent + batch_reserved + amount > self.total_cap:
                raise BudgetStopped("request reservation would exceed the batch cost cap")
            run["requests"][request_id] = {
                "status": "reserved",
                "reserved_usd": _money_text(amount),
                "charged_usd": None,
                "usage_valid": None,
            }
            self._persist()
            return amount

    def settle(self, run_id: str, request_id: str, usage: Usage | None) -> Settlement:
        with self._lock:
            self._assert_open()
            run = self._require_run(run_id)
            request_state = run["requests"].get(request_id)
            if not isinstance(request_state, dict) or request_state.get("status") != "reserved":
                raise ApiBudgetProxyError("request has no active reservation")
            reserved = Decimal(request_state["reserved_usd"])
            usage_valid = True
            try:
                if usage is None:
                    raise ApiBudgetProxyError("response usage is missing")
                charged = price_usage(usage)
                if charged > reserved:
                    raise ApiBudgetProxyError("response usage exceeds the request reservation")
            except ApiBudgetProxyError:
                charged = reserved
                usage_valid = False
                run["stopped"] = True
                run["stop_reason"] = "missing_or_invalid_usage"
            request_state["status"] = "settled"
            request_state["charged_usd"] = _money_text(charged)
            request_state["usage_valid"] = usage_valid
            run["spent_usd"] = _money_text(Decimal(run["spent_usd"]) + charged)
            self._persist()
            return Settlement(charged, usage_valid, bool(run["stopped"]))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._assert_open()
            spent, reserved = self._totals()
            return {
                "schema_version": 1,
                "batch_id": self.batch_id,
                "total_cap_usd": _money_text(self.total_cap),
                "max_runs": self.max_runs,
                "default_run_cap_usd": _money_text(self.default_run_cap),
                "run_slots_used": len(self._state["runs"]),
                "spent_usd": _money_text(spent),
                "reserved_usd": _money_text(reserved),
                "remaining_uncommitted_usd": _money_text(self.total_cap - spent - reserved),
                "runs": json.loads(json.dumps(self._state["runs"])),
            }

    def _prepare_parent(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.parent.is_symlink() or not self.path.parent.is_dir():
            raise ApiBudgetProxyError("budget ledger parent is unsafe")
        if _path_present(self.path) and (self.path.is_symlink() or not self.path.is_file()):
            raise ApiBudgetProxyError("budget ledger path is unsafe")

    def _acquire_process_lock(self) -> int:
        if _path_present(self._lock_path) and self._lock_path.is_symlink():
            raise ApiBudgetProxyError("budget ledger lock path is unsafe")
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self._lock_path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        try:
            import fcntl

            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (ImportError, OSError) as exc:
            os.close(descriptor)
            raise ApiBudgetProxyError("budget ledger is already active or cannot be locked") from exc
        return descriptor

    def _read_state(self) -> dict[str, Any]:
        if self.path.is_symlink() or not self.path.is_file():
            raise ApiBudgetProxyError("budget ledger path is unsafe")
        if stat.S_IMODE(self.path.stat().st_mode) != 0o600:
            raise ApiBudgetProxyError("budget ledger must have mode 0600")
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ApiBudgetProxyError("budget ledger is invalid") from exc
        _validate_state(
            value,
            batch_id=self.batch_id,
            total_cap=self.total_cap,
            max_runs=self.max_runs,
            default_run_cap=self.default_run_cap,
        )
        return value

    def _recover_reserved_requests(self) -> None:
        recovered = False
        for run in self._state["runs"].values():
            for request_state in run["requests"].values():
                if request_state["status"] != "reserved":
                    continue
                charged = Decimal(request_state["reserved_usd"])
                request_state["status"] = "settled"
                request_state["charged_usd"] = _money_text(charged)
                request_state["usage_valid"] = False
                run["spent_usd"] = _money_text(Decimal(run["spent_usd"]) + charged)
                run["stopped"] = True
                run["stop_reason"] = "interrupted_request"
                recovered = True
        if recovered:
            self._persist()

    def _persist(self) -> None:
        encoded = (json.dumps(self._state, sort_keys=True, separators=(",", ":")) + "\n").encode()
        temporary = self.path.with_name(
            f".{self.path.name}.tmp-{os.getpid()}-{threading.get_ident()}"
        )
        if _path_present(temporary):
            raise ApiBudgetProxyError("budget ledger temporary path already exists")
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(temporary, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
            _fsync_directory(self.path.parent)
        except Exception:
            if temporary.is_file() and not temporary.is_symlink():
                temporary.unlink()
            raise

    def _require_run(self, run_id: str) -> dict[str, Any]:
        run = self._state["runs"].get(run_id)
        if not isinstance(run, dict):
            raise ApiBudgetProxyError("benchmark run is not registered")
        return run

    def _totals(self) -> tuple[Decimal, Decimal]:
        spent = sum(
            (Decimal(run["spent_usd"]) for run in self._state["runs"].values()),
            Decimal(0),
        )
        reserved = sum(
            (_reserved_total(run) for run in self._state["runs"].values()), Decimal(0)
        )
        return spent, reserved

    def _assert_open(self) -> None:
        if self._closed:
            raise ApiBudgetProxyError("budget ledger is closed")


class RedactedMetadataStore:
    """Small atomic JSON store containing only bounded, non-secret observations."""

    def __init__(self, path: Path, *, secrets_to_exclude: tuple[str, ...]):
        if not secrets_to_exclude or any(not secret for secret in secrets_to_exclude):
            raise ApiBudgetProxyError("in-memory secrets are required for redaction")
        self.path = Path(path)
        self._secrets = tuple(secret.encode() for secret in secrets_to_exclude)
        lock_key = str(self.path.absolute())
        with _METADATA_LOCKS_GUARD:
            self._lock = _METADATA_LOCKS.setdefault(lock_key, threading.Lock())
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.parent.is_symlink() or not self.path.parent.is_dir():
            raise ApiBudgetProxyError("metadata parent is unsafe")
        if _path_present(self.path) and (self.path.is_symlink() or not self.path.is_file()):
            raise ApiBudgetProxyError("metadata path is unsafe")

    def append(self, observation: Mapping[str, Any]) -> None:
        expected = {
            "request_id",
            "body_sha256",
            "role",
            "model",
            "reasoning_effort",
            "stream",
            "shape",
            "contract_match",
            "upstream_status",
            "usage_valid",
            "charged_usd",
        }
        if set(observation) != expected:
            raise ApiBudgetProxyError("metadata observation differs from schema v1")
        encoded_observation = json.dumps(
            dict(observation), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
        if any(secret in encoded_observation for secret in self._secrets):
            raise ApiBudgetProxyError("secret appeared in redacted metadata")
        with self._lock:
            if _path_present(self.path):
                if self.path.is_symlink() or not self.path.is_file():
                    raise ApiBudgetProxyError("metadata path is unsafe")
                if stat.S_IMODE(self.path.stat().st_mode) != 0o600:
                    raise ApiBudgetProxyError("metadata file must have mode 0600")
                try:
                    state = json.loads(self.path.read_text(encoding="utf-8"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise ApiBudgetProxyError("metadata file is invalid") from exc
                if not isinstance(state, dict) or set(state) != {"schema_version", "requests"}:
                    raise ApiBudgetProxyError("metadata file differs from schema v1")
                if state["schema_version"] != 1 or not isinstance(state["requests"], list):
                    raise ApiBudgetProxyError("metadata file differs from schema v1")
            else:
                state = {"schema_version": 1, "requests": []}
            state["requests"].append(dict(observation))
            _atomic_private_json(self.path, state)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


class _UrllibTransport:
    """No-retry/no-redirect HTTP transport; endpoint override is test-only."""

    def __init__(self, *, endpoint_override: str | None = None):
        if endpoint_override is not None:
            parsed = urlsplit(endpoint_override)
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
                raise ApiBudgetProxyError("test upstream override must be loopback HTTP")
        self._endpoint_override = endpoint_override
        self._opener = build_opener(_NoRedirect())

    def open(
        self,
        official_endpoint: str,
        *,
        body: bytes,
        headers: Mapping[str, str],
        timeout: float,
    ) -> Any:
        endpoint = self._endpoint_override or official_endpoint
        request = Request(endpoint, data=body, headers=dict(headers), method="POST")
        return self._opener.open(request, timeout=timeout)


class _LoopbackServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class LoopbackResponsesProxy:
    """Short-lived local HTTP proxy for a single registered benchmark run."""

    def __init__(
        self,
        *,
        upstream_base_url: str,
        api_key: str,
        ledger: PersistentBudgetLedger,
        run_id: str,
        metadata_path: Path,
        timeout_seconds: float = 120.0,
        _transport: _UrllibTransport | None = None,
    ):
        self.upstream_endpoint = _official_responses_endpoint(upstream_base_url)
        if not api_key or "\r" in api_key or "\n" in api_key:
            raise ApiBudgetProxyError("an in-memory API key is required")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ApiBudgetProxyError("proxy timeout must be positive")
        _require_safe_id(run_id, "run id")
        ledger.ensure_run(run_id)
        self._api_key = api_key
        self._downstream_api_key = "rondo-eval-" + secrets.token_urlsafe(32)
        self._ledger = ledger
        self._run_id = run_id
        self._metadata = RedactedMetadataStore(
            metadata_path,
            secrets_to_exclude=(api_key, self._downstream_api_key),
        )
        self._timeout = timeout_seconds
        self._transport = _transport or _UrllibTransport()
        self._server: _LoopbackServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise ApiBudgetProxyError("loopback proxy is not running")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}/v1"

    @property
    def downstream_api_key(self) -> str:
        """Return the ephemeral key that the runner injects into the child only."""

        return self._downstream_api_key

    @property
    def docker_base_url(self) -> str:
        """Return the Docker Desktop bridge for the same loopback listener.

        The listener remains bound to 127.0.0.1.  RONDO's B1 doctor verifies
        that Docker Desktop's ``host.docker.internal`` forwarder reaches that
        loopback socket before a paid run is permitted.
        """

        if self._server is None:
            raise ApiBudgetProxyError("loopback proxy is not running")
        host, port = self._server.server_address[:2]
        if host != "127.0.0.1" or not isinstance(port, int) or port <= 0:
            raise ApiBudgetProxyError("loopback proxy address is invalid")
        return f"http://host.docker.internal:{port}/v1"

    def __enter__(self) -> LoopbackResponsesProxy:
        return self.start()

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def start(self) -> LoopbackResponsesProxy:
        if self._server is not None:
            raise ApiBudgetProxyError("loopback proxy is already running")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # noqa: N802
                owner._handle(self)

            def do_GET(self) -> None:  # noqa: N802
                owner._reject_non_post(self)

            def do_PUT(self) -> None:  # noqa: N802
                owner._reject_non_post(self)

            def do_DELETE(self) -> None:  # noqa: N802
                owner._reject_non_post(self)

            def do_HEAD(self) -> None:  # noqa: N802
                owner._reject_non_post(self)

            def do_OPTIONS(self) -> None:  # noqa: N802
                owner._reject_non_post(self)

            def do_PATCH(self) -> None:  # noqa: N802
                owner._reject_non_post(self)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = _LoopbackServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="rondo-api-budget-proxy",
            daemon=True,
        )
        self._thread.start()
        return self

    def close(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=5)

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        if not self._authenticate(handler):
            self._reject(handler, 401, "unauthorized")
            return
        if handler.path != "/v1/responses":
            self._reject(handler, 404, "responses_path_required")
            return
        if "websocket" in handler.headers.get("Upgrade", "").lower():
            self._reject(handler, 400, "websocket_disabled")
            return
        for name in _RETRY_HEADERS:
            value = handler.headers.get(name)
            if value is not None and value.strip() not in {"", "0"}:
                self._reject(handler, 409, "retries_disabled")
                return
        try:
            length = int(handler.headers.get("Content-Length", ""))
        except ValueError:
            self._reject(handler, 411, "content_length_required")
            return
        if length <= 0 or length > _MAX_REQUEST_BYTES:
            self._reject(handler, 413, "request_size_invalid")
            return
        body = handler.rfile.read(length)
        if len(body) != length:
            self._reject(handler, 400, "request_body_incomplete")
            return
        # Consume the bounded request body before rejecting a malformed Lite
        # routing header. Closing a socket with unread request bytes can reset
        # the connection before the client receives the structured error body.
        try:
            forward_lite_header = _validated_lite_header(handler.headers)
        except ApiBudgetProxyError:
            self._reject(handler, 400, "invalid_lite_header")
            return
        request_id = handler.headers.get("X-RONDO-Eval-Request-Id") or uuid.uuid4().hex
        role = handler.headers.get("X-RONDO-Eval-Role", "unknown").strip().lower()
        try:
            _require_safe_id(request_id, "request id")
            request_metadata = _inspect_request(body, role)
            self._ledger.reserve(self._run_id, request_id)
        except BudgetStopped:
            self._reject(handler, 429, "budget_stopped")
            return
        except ApiBudgetProxyError:
            self._reject(handler, 400, "request_rejected")
            return

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": handler.headers.get("Accept", "application/json"),
            "User-Agent": "rondo-eval-budget-proxy/1",
        }
        if forward_lite_header:
            headers[_LITE_HEADER] = "true"
        for name in ("OpenAI-Beta", "OpenAI-Organization", "OpenAI-Project"):
            value = handler.headers.get(name)
            if value:
                headers[name] = value
        try:
            upstream = self._transport.open(
                self.upstream_endpoint,
                body=body,
                headers=headers,
                timeout=self._timeout,
            )
            self._relay(handler, upstream, request_id, request_metadata)
        except HTTPError as response:
            self._relay(handler, response, request_id, request_metadata)
        except (OSError, URLError, TimeoutError, socket.timeout):
            settlement = self._ledger.settle(self._run_id, request_id, None)
            self._save_observation(request_id, request_metadata, 0, settlement)
            self._reject(handler, 502, "upstream_unavailable")
        except Exception:
            settlement = self._ledger.settle(self._run_id, request_id, None)
            self._save_observation(request_id, request_metadata, 0, settlement)
            self._reject(handler, 502, "upstream_failure")

    def _authenticate(self, handler: BaseHTTPRequestHandler) -> bool:
        values = handler.headers.get_all("Authorization", [])
        provided = values[0] if len(values) == 1 else ""
        expected = f"Bearer {self._downstream_api_key}"
        return hmac.compare_digest(provided.encode("utf-8"), expected.encode("utf-8"))

    def _reject_non_post(self, handler: BaseHTTPRequestHandler) -> None:
        if not self._authenticate(handler):
            self._reject(handler, 401, "unauthorized")
            return
        self._reject(handler, 405, "method_not_allowed")

    def _relay(
        self,
        handler: BaseHTTPRequestHandler,
        upstream: Any,
        request_id: str,
        request_metadata: dict[str, Any],
    ) -> None:
        status = int(getattr(upstream, "status", getattr(upstream, "code", 502)))
        content_type = upstream.headers.get("Content-Type", "application/json")
        usage: Usage | None = None
        if content_type.lower().split(";", 1)[0].strip() == "text/event-stream":
            handler.send_response(status)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Connection", "close")
            handler.end_headers()
            handler.close_connection = True
            collector = _SseUsageCollector()
            total = 0
            writable = True
            while True:
                chunk = upstream.read(8192)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_RESPONSE_BYTES:
                    usage = None
                    break
                collector.feed(chunk)
                if writable:
                    try:
                        handler.wfile.write(chunk)
                        handler.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        writable = False
            collector.finish()
            usage = collector.usage
            upstream.close()
            settlement = self._ledger.settle(self._run_id, request_id, usage)
            self._save_observation(request_id, request_metadata, status, settlement)
        else:
            response_body = upstream.read(_MAX_RESPONSE_BYTES + 1)
            if len(response_body) <= _MAX_RESPONSE_BYTES:
                usage = _usage_from_json_bytes(response_body)
            upstream.close()
            settlement = self._ledger.settle(self._run_id, request_id, usage)
            self._save_observation(request_id, request_metadata, status, settlement)
            handler.send_response(status)
            handler.send_header("Content-Type", content_type)
            handler.send_header("Content-Length", str(len(response_body)))
            handler.send_header("Connection", "close")
            handler.end_headers()
            handler.close_connection = True
            try:
                handler.wfile.write(response_body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    def _save_observation(
        self,
        request_id: str,
        request_metadata: Mapping[str, Any],
        status: int,
        settlement: Settlement,
    ) -> None:
        observation = dict(request_metadata)
        observation.update(
            {
                "request_id": request_id,
                "upstream_status": status,
                "usage_valid": settlement.usage_valid,
                "charged_usd": _money_text(settlement.charged_usd),
            }
        )
        self._metadata.append(observation)

    @staticmethod
    def _reject(handler: BaseHTTPRequestHandler, status: int, code: str) -> None:
        body = json.dumps({"error": {"code": code}}, separators=(",", ":")).encode()
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(body)))
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.close_connection = True
        try:
            handler.wfile.write(body)
            handler.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


def milestone_metadata_ready(metadata_path: Path) -> bool:
    """Return true only when every persisted request has a verified role."""

    try:
        value = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    requests = value.get("requests") if isinstance(value, dict) else None
    return bool(requests) and all(
        isinstance(item, dict)
        and item.get("role") in {"main", "guardian"}
        and item.get("contract_match") is True
        and item.get("usage_valid") is True
        for item in requests
    )


def _validated_lite_header(headers: Any) -> bool:
    values = headers.get_all(_LITE_HEADER, [])
    if not values:
        return False
    if values != ["true"]:
        raise ApiBudgetProxyError("Lite routing header must be exactly true")
    return True


def _inspect_request(body: bytes, declared_role: str) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ApiBudgetProxyError("request body must be JSON") from exc
    if not isinstance(value, dict):
        raise ApiBudgetProxyError("request body must be a JSON object")
    model = value.get("model")
    if model != OFFICIAL_MODEL:
        raise ApiBudgetProxyError("request model differs from the frozen Luna contract")
    stream = value.get("stream", False)
    if not isinstance(stream, bool):
        raise ApiBudgetProxyError("stream must be boolean")
    tools = value.get("tools", [])
    if not isinstance(tools, list):
        raise ApiBudgetProxyError("tools must be an array")
    tool_types: list[str] = []
    for tool in tools:
        if not isinstance(tool, dict) or not isinstance(tool.get("type"), str):
            raise ApiBudgetProxyError("tool declarations must have string types")
        tool_type = tool["type"]
        if tool_type in _HOSTED_TOOL_TYPES:
            raise ApiBudgetProxyError("hosted tools are disabled")
        tool_types.append(tool_type)
    reasoning = value.get("reasoning", {})
    if reasoning is None:
        reasoning = {}
    if not isinstance(reasoning, dict):
        raise ApiBudgetProxyError("reasoning must be an object")
    effort = reasoning.get("effort")
    if effort is not None and not isinstance(effort, str):
        raise ApiBudgetProxyError("reasoning effort must be a string")
    inferred_role = "guardian" if _has_guardian_output_schema(value) else "main"
    if declared_role in {"main", "guardian"}:
        if declared_role != inferred_role:
            raise ApiBudgetProxyError("declared request role conflicts with request shape")
        role = declared_role
    elif declared_role == "unknown":
        role = inferred_role
    else:
        raise ApiBudgetProxyError("declared request role is invalid")
    contract_match = model == OFFICIAL_MODEL and (
        role == "main" or (role == "guardian" and effort == "low")
    )
    if role == "guardian" and not contract_match:
        raise ApiBudgetProxyError("guardian request is not Luna with low reasoning effort")
    input_value = value.get("input")
    if isinstance(input_value, list):
        input_kind = "array"
        input_items = len(input_value)
    elif isinstance(input_value, str):
        input_kind = "string"
        input_items = 1
    elif input_value is None:
        input_kind = "missing"
        input_items = 0
    else:
        input_kind = "other"
        input_items = 1
    return {
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "role": role,
        "model": model,
        "reasoning_effort": effort,
        "stream": stream,
        "shape": {
            "input_kind": input_kind,
            "input_items": input_items,
            "instructions_present": "instructions" in value,
            "tools_count": len(tools),
            "tool_types": sorted(tool_types),
            "previous_response_id_present": "previous_response_id" in value,
        },
        "contract_match": contract_match,
    }


def _has_guardian_output_schema(value: Mapping[str, Any]) -> bool:
    text = value.get("text")
    if not isinstance(text, dict):
        return False
    output_format = text.get("format")
    if not isinstance(output_format, dict):
        return False
    return output_format.get("schema") == GUARDIAN_OUTPUT_SCHEMA


def _usage_from_json_bytes(body: bytes) -> Usage | None:
    try:
        value = json.loads(body)
    except (UnicodeError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    usage = value.get("usage")
    if usage is None and isinstance(value.get("response"), dict):
        usage = value["response"].get("usage")
    try:
        return _parse_usage(usage)
    except ApiBudgetProxyError:
        return None


def _parse_usage(value: object) -> Usage:
    if not isinstance(value, dict):
        raise ApiBudgetProxyError("response usage is missing")
    details = value.get("input_tokens_details", {})
    if details is None:
        details = {}
    if not isinstance(details, dict):
        raise ApiBudgetProxyError("input token details are invalid")
    cached = details.get("cached_tokens", value.get("cached_input_tokens", 0))
    cache_write = details.get(
        "cache_write_tokens",
        value.get("cache_write_input_tokens", value.get("cache_creation_input_tokens", 0)),
    )
    usage = Usage(
        input_tokens=value.get("input_tokens"),
        cached_input_tokens=cached,
        cache_write_input_tokens=cache_write,
        output_tokens=value.get("output_tokens"),
    )
    usage.validate()
    return usage


class _SseUsageCollector:
    def __init__(self) -> None:
        self._buffer = bytearray()
        self.usage: Usage | None = None

    def feed(self, chunk: bytes) -> None:
        self._buffer.extend(chunk)
        if len(self._buffer) > _MAX_RESPONSE_BYTES:
            self._buffer.clear()
            self.usage = None
            return
        normalized = bytes(self._buffer).replace(b"\r\n", b"\n")
        events = normalized.split(b"\n\n")
        self._buffer = bytearray(events.pop())
        for event in events:
            self._consume(event)

    def finish(self) -> None:
        if self._buffer:
            self._consume(bytes(self._buffer).replace(b"\r\n", b"\n"))
            self._buffer.clear()

    def _consume(self, event: bytes) -> None:
        data = b"\n".join(
            line[5:].lstrip() for line in event.splitlines() if line.startswith(b"data:")
        )
        if not data or data == b"[DONE]":
            return
        parsed = _usage_from_json_bytes(data)
        if parsed is not None:
            self.usage = parsed


def _official_responses_endpoint(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "api.openai.com"
        or parsed.port not in {None, 443}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/v1"
    ):
        raise ApiBudgetProxyError("upstream must be the official credential-free OpenAI /v1 URL")
    return "https://api.openai.com/v1/responses"


def _money(value: Decimal | str | int) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ApiBudgetProxyError("money value is invalid") from exc
    if not amount.is_finite() or amount < 0:
        raise ApiBudgetProxyError("money value must be finite and non-negative")
    return amount.quantize(_MONEY_QUANTUM, rounding=ROUND_UP)


def _money_text(value: Decimal) -> str:
    return format(value.quantize(_MONEY_QUANTUM), "f")


def _require_safe_id(value: object, label: str) -> None:
    if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
        raise ApiBudgetProxyError(f"{label} is invalid")


def _reserved_total(run: Mapping[str, Any]) -> Decimal:
    return sum(
        (
            Decimal(request["reserved_usd"])
            for request in run["requests"].values()
            if request["status"] == "reserved"
        ),
        Decimal(0),
    )


def _validate_state(
    value: object,
    *,
    batch_id: str,
    total_cap: Decimal,
    max_runs: int,
    default_run_cap: Decimal,
) -> None:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "batch_id",
        "total_cap_usd",
        "max_runs",
        "default_run_cap_usd",
        "runs",
    }:
        raise ApiBudgetProxyError("budget ledger differs from schema v1")
    if (
        value["schema_version"] != 1
        or value["batch_id"] != batch_id
        or value["total_cap_usd"] != _money_text(total_cap)
        or value["max_runs"] != max_runs
        or value["default_run_cap_usd"] != _money_text(default_run_cap)
        or not isinstance(value["runs"], dict)
        or len(value["runs"]) > max_runs
    ):
        raise ApiBudgetProxyError("budget ledger does not match the authorized batch")
    total_spent = Decimal(0)
    total_reserved = Decimal(0)
    for run_id, run in value["runs"].items():
        _require_safe_id(run_id, "run id")
        if not isinstance(run, dict) or set(run) != {
            "cap_usd",
            "spent_usd",
            "stopped",
            "stop_reason",
            "requests",
        }:
            raise ApiBudgetProxyError("budget run state differs from schema v1")
        cap = _money(run["cap_usd"])
        spent = _money(run["spent_usd"])
        if cap <= 0 or cap > default_run_cap or spent > cap:
            raise ApiBudgetProxyError("budget run totals are invalid")
        if not isinstance(run["stopped"], bool) or not isinstance(run["requests"], dict):
            raise ApiBudgetProxyError("budget run state is invalid")
        if run["stop_reason"] is not None and not isinstance(run["stop_reason"], str):
            raise ApiBudgetProxyError("budget stop reason is invalid")
        settled_total = Decimal(0)
        for request_id, request in run["requests"].items():
            _require_safe_id(request_id, "request id")
            if not isinstance(request, dict) or set(request) != {
                "status",
                "reserved_usd",
                "charged_usd",
                "usage_valid",
            }:
                raise ApiBudgetProxyError("budget request state differs from schema v1")
            reserved = _money(request["reserved_usd"])
            if reserved <= 0 or reserved > MAX_REQUEST_RESERVATION_USD:
                raise ApiBudgetProxyError("budget reservation is invalid")
            if request["status"] == "reserved":
                if request["charged_usd"] is not None or request["usage_valid"] is not None:
                    raise ApiBudgetProxyError("active budget reservation is invalid")
                total_reserved += reserved
            elif request["status"] == "settled":
                charged = _money(request["charged_usd"])
                if charged > reserved or not isinstance(request["usage_valid"], bool):
                    raise ApiBudgetProxyError("settled budget request is invalid")
                settled_total += charged
            else:
                raise ApiBudgetProxyError("budget request status is invalid")
        if spent != settled_total or spent + _reserved_total(run) > cap:
            raise ApiBudgetProxyError("budget run exceeds its cap")
        total_spent += spent
    if total_spent + total_reserved > total_cap:
        raise ApiBudgetProxyError("budget ledger exceeds its batch cap")


def _path_present(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _atomic_private_json(path: Path, value: object) -> None:
    encoded = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{threading.get_ident()}")
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
    except Exception:
        if temporary.is_file() and not temporary.is_symlink():
            temporary.unlink()
        raise


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
