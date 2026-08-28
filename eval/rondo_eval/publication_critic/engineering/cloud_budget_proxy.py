"""Plan 097 loopback chat-completions proxy with a persistent RMB cap."""

import copy
import hmac
import json
import math
import os
import secrets
import socket
import stat
import tempfile
import threading
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Self
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from ..cloud_quality.contract import CloudQualityError
from ..cloud_quality.cost import usage_cost_rmb


DEFAULT_CAP_RMB = Decimal("12")
ATTEMPT_RESERVATION_RMB = Decimal("1")
MAX_REQUEST_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 256 * 1024

_MAX_CAP_RMB = Decimal("30")
_MAX_LEDGER_BYTES = 1024 * 1024
_MAX_PROMPT_TOKENS = 500_000
_MAX_COMPLETION_TOKENS = 32_768
_SCHEMA = "rondo-publication-critic-plan097-cloud-budget-v1"
_ATTEMPT_FIELDS = {
    "attempt",
    "state",
    "usage",
    "actual_charge_rmb",
    "conservative_charge_rmb",
}


class CloudBudgetProxyError(RuntimeError):
    """The proxy or its body-free ledger is unsafe."""


class BudgetCapExceeded(CloudBudgetProxyError):
    """Another upstream attempt cannot fit its 1 RMB reservation."""


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args: object, **_kwargs: object) -> None:
        return None


class _LoopbackServer(ThreadingHTTPServer):
    daemon_threads = False
    block_on_close = True
    allow_reuse_address = False


class _PersistentLedger:
    def __init__(self, path: Path, cap_rmb: Decimal) -> None:
        if not path.is_absolute():
            raise CloudBudgetProxyError("ledger_path_must_be_absolute")
        self.path = path
        self.cap_rmb = cap_rmb
        self._lock = threading.Lock()
        self._document = self._load_or_create()

    def reserve(self) -> int:
        with self._lock:
            attempts = self._document["attempts"]
            if _charged(attempts) + ATTEMPT_RESERVATION_RMB > self.cap_rmb:
                raise BudgetCapExceeded("budget_cap_exceeded")
            row = {
                "attempt": len(attempts) + 1,
                "state": "reserved",
                "usage": None,
                "actual_charge_rmb": None,
                "conservative_charge_rmb": "1",
            }
            updated = {**self._document, "attempts": [*attempts, row]}
            self._persist(updated)
            self._document = updated
            return row["attempt"]

    def settle(self, attempt: int, usage: dict[str, int] | None) -> None:
        try:
            actual = usage_cost_rmb(usage) if usage is not None else None
        except CloudQualityError:
            usage = None
            actual = None
        if actual is not None and actual > ATTEMPT_RESERVATION_RMB:
            usage = None
            actual = None
        with self._lock:
            attempts = copy.deepcopy(self._document["attempts"])
            if not 1 <= attempt <= len(attempts):
                raise CloudBudgetProxyError("ledger_attempt_missing")
            row = attempts[attempt - 1]
            if row["attempt"] != attempt or row["state"] != "reserved":
                raise CloudBudgetProxyError("ledger_attempt_not_reserved")
            if usage is None or actual is None:
                row.update(
                    state="unknown_usage_charged",
                    usage=None,
                    actual_charge_rmb=None,
                    conservative_charge_rmb="1",
                )
            else:
                charge = _decimal_text(actual)
                row.update(
                    state="usage_priced",
                    usage=usage,
                    actual_charge_rmb=charge,
                    conservative_charge_rmb=charge,
                )
            updated = {**self._document, "attempts": attempts}
            self._persist(updated)
            self._document = updated

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            attempts = copy.deepcopy(self._document["attempts"])
            charged = _charged(attempts)
        return {
            "schema": _SCHEMA,
            "cap_rmb": _decimal_text(self.cap_rmb),
            "conservative_charged_rmb": _decimal_text(charged),
            "remaining_rmb": _decimal_text(self.cap_rmb - charged),
            "attempts": attempts,
        }

    def _load_or_create(self) -> dict[str, Any]:
        if self.path.exists() or self.path.is_symlink():
            metadata = self.path.lstat()
            if (
                self.path.is_symlink()
                or not self.path.is_file()
                or stat.S_IMODE(metadata.st_mode) != 0o600
                or not 0 < metadata.st_size <= _MAX_LEDGER_BYTES
            ):
                raise CloudBudgetProxyError("ledger_file_unsafe")
            try:
                document = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise CloudBudgetProxyError("ledger_file_invalid") from exc
            _validate_document(document, self.cap_rmb)
            return document
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.parent.is_symlink() or not self.path.parent.is_dir():
            raise CloudBudgetProxyError("ledger_parent_unsafe")
        document = {
            "schema": _SCHEMA,
            "cap_rmb": _decimal_text(self.cap_rmb),
            "attempts": [],
        }
        self._persist(document)
        return document

    def _persist(self, document: dict[str, Any]) -> None:
        encoded = (
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode()
        if len(encoded) > _MAX_LEDGER_BYTES:
            raise CloudBudgetProxyError("ledger_file_too_large")
        descriptor, name = tempfile.mkstemp(
            dir=self.path.parent, prefix=f".{self.path.name}.", suffix=".tmp"
        )
        temporary = Path(name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as handle:
                descriptor = -1
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            temporary.unlink(missing_ok=True)


class CloudBudgetProxy:
    """Single-purpose proxy for Plan 097 DeepSeek scorer attempts."""

    def __init__(
        self,
        *,
        upstream_endpoint: str,
        upstream_api_key: str,
        ledger_path: Path,
        cap_rmb: Decimal | str = DEFAULT_CAP_RMB,
        timeout_seconds: float = 90.0,
        _opener: Any | None = None,
    ) -> None:
        self._upstream_endpoint = _upstream_endpoint(upstream_endpoint)
        if (
            not isinstance(upstream_api_key, str)
            or not upstream_api_key
            or len(upstream_api_key) > 8192
            or "\r" in upstream_api_key
            or "\n" in upstream_api_key
        ):
            raise CloudBudgetProxyError("upstream_api_key_invalid")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 180
        ):
            raise CloudBudgetProxyError("timeout_invalid")
        self._upstream_api_key = upstream_api_key
        self._downstream_api_key = "rondo-plan097-" + secrets.token_urlsafe(32)
        self._ledger = _PersistentLedger(Path(ledger_path), _cap(cap_rmb))
        self._timeout = float(timeout_seconds)
        self._opener = _opener or build_opener(_NoRedirect())
        self._server: _LoopbackServer | None = None
        self._thread: threading.Thread | None = None
        self._closing = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._started = False

    @property
    def base_url(self) -> str:
        if self._server is None:
            raise CloudBudgetProxyError("proxy_not_running")
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def downstream_api_key(self) -> str:
        return self._downstream_api_key

    def snapshot(self) -> dict[str, Any]:
        return self._ledger.snapshot()

    def __enter__(self) -> Self:
        return self.start()

    def __exit__(self, _kind: object, _value: object, _traceback: object) -> None:
        self.close()

    def start(self) -> Self:
        if self._started:
            raise CloudBudgetProxyError("proxy_already_started")
        self._started = True
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def setup(self) -> None:
                super().setup()
                self.connection.settimeout(min(owner._timeout, 15.0))

            def do_POST(self) -> None:  # noqa: N802
                owner._handle(self)

            def _non_post(self) -> None:
                owner._reject_non_post(self)

            do_GET = do_PUT = do_DELETE = do_PATCH = do_HEAD = do_OPTIONS = _non_post

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = _LoopbackServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="rondo-plan097-cloud-budget-proxy",
            daemon=True,
        )
        self._thread.start()
        return self

    def close(self) -> None:
        self._closing.set()
        with self._lifecycle_lock:
            pass
        server, thread = self._server, self._thread
        self._server = None
        self._thread = None
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join()

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        if not self._authenticate(handler):
            self._reject(handler, 401, "unauthorized")
            return
        if handler.path != "/chat/completions":
            self._reject(handler, 404, "chat_completions_path_required")
            return
        if handler.headers.get("Transfer-Encoding") is not None:
            self._reject(handler, 400, "transfer_encoding_disabled")
            return
        lengths = handler.headers.get_all("Content-Length", [])
        try:
            length = int(lengths[0]) if len(lengths) == 1 else -1
        except ValueError:
            length = -1
        if not 0 < length <= MAX_REQUEST_BYTES:
            self._reject(handler, 413, "request_size_invalid")
            return
        content_type = handler.headers.get("Content-Type", "")
        if content_type.lower().split(";", 1)[0].strip() != "application/json":
            self._reject(handler, 415, "json_required")
            return
        body = handler.rfile.read(length)
        try:
            request_value = json.loads(body) if len(body) == length else None
        except (UnicodeError, json.JSONDecodeError):
            request_value = None
        if not isinstance(request_value, dict) or request_value.get("stream") is True:
            self._reject(handler, 400, "non_stream_json_object_required")
            return
        try:
            with self._lifecycle_lock:
                if self._closing.is_set():
                    self._reject(handler, 503, "proxy_closing")
                    return
                attempt = self._ledger.reserve()
                try:
                    upstream = self._opener.open(
                        Request(
                            self._upstream_endpoint,
                            data=body,
                            headers={
                                "Accept": "application/json",
                                "Authorization": f"Bearer {self._upstream_api_key}",
                                "Content-Type": "application/json",
                            },
                            method="POST",
                        ),
                        timeout=self._timeout,
                    )
                except HTTPError as response:
                    upstream = response
        except BudgetCapExceeded:
            self._reject(handler, 429, "budget_cap_exceeded")
            return
        except CloudBudgetProxyError:
            self._reject(handler, 503, "ledger_unavailable")
            return
        except (OSError, URLError, TimeoutError, socket.timeout):
            self._settle_unknown(attempt)
            self._reject(handler, 502, "upstream_unavailable")
            return
        try:
            status = int(getattr(upstream, "status", getattr(upstream, "code", 502)))
            response_body = _read_bounded(upstream)
            content_type = upstream.headers.get("Content-Type", "application/json")
        except (CloudBudgetProxyError, OSError, TypeError, ValueError, TimeoutError):
            self._settle_unknown(attempt)
            self._reject(handler, 502, "upstream_response_invalid")
            return
        finally:
            upstream.close()
        try:
            self._ledger.settle(attempt, _response_usage(response_body))
        except CloudBudgetProxyError:
            self._reject(handler, 502, "ledger_settlement_failed")
            return
        if not 100 <= status <= 599:
            self._reject(handler, 502, "upstream_status_invalid")
            return
        _send(handler, status, response_body, content_type)

    def _settle_unknown(self, attempt: int) -> None:
        try:
            self._ledger.settle(attempt, None)
        except CloudBudgetProxyError:
            pass

    def _authenticate(self, handler: BaseHTTPRequestHandler) -> bool:
        values = handler.headers.get_all("Authorization", [])
        provided = values[0] if len(values) == 1 else ""
        return hmac.compare_digest(provided, f"Bearer {self._downstream_api_key}")

    def _reject_non_post(self, handler: BaseHTTPRequestHandler) -> None:
        status = 405 if self._authenticate(handler) else 401
        self._reject(handler, status, "method_not_allowed" if status == 405 else "unauthorized")

    @staticmethod
    def _reject(handler: BaseHTTPRequestHandler, status: int, code: str) -> None:
        body = json.dumps({"error": {"code": code}}, separators=(",", ":")).encode()
        _send(handler, status, body, "application/json")


def _validate_document(document: Any, cap: Decimal) -> None:
    if not isinstance(document, dict) or set(document) != {"schema", "cap_rmb", "attempts"}:
        raise CloudBudgetProxyError("ledger_schema_invalid")
    if document["schema"] != _SCHEMA or document["cap_rmb"] != _decimal_text(cap):
        raise CloudBudgetProxyError("ledger_identity_invalid")
    attempts = document["attempts"]
    if not isinstance(attempts, list):
        raise CloudBudgetProxyError("ledger_attempts_invalid")
    for expected, row in enumerate(attempts, start=1):
        if not isinstance(row, dict) or set(row) != _ATTEMPT_FIELDS:
            raise CloudBudgetProxyError("ledger_attempt_invalid")
        if row["attempt"] != expected or row["state"] not in {
            "reserved", "usage_priced", "unknown_usage_charged"
        }:
            raise CloudBudgetProxyError("ledger_attempt_invalid")
        conservative = _stored_decimal(row["conservative_charge_rmb"])
        if row["state"] == "usage_priced":
            usage = _usage(row["usage"])
            actual = _stored_decimal(row["actual_charge_rmb"])
            if usage != row["usage"]:
                raise CloudBudgetProxyError("ledger_attempt_invalid")
            try:
                expected_charge = usage_cost_rmb(usage)
            except CloudQualityError as exc:
                raise CloudBudgetProxyError("ledger_attempt_invalid") from exc
            if actual != expected_charge or actual != conservative:
                raise CloudBudgetProxyError("ledger_attempt_invalid")
        elif row["usage"] is not None or row["actual_charge_rmb"] is not None or conservative != 1:
            raise CloudBudgetProxyError("ledger_attempt_invalid")
    if _charged(attempts) > cap:
        raise CloudBudgetProxyError("ledger_cap_exceeded")


def _read_bounded(upstream: Any) -> bytes:
    raw_length = upstream.headers.get("Content-Length")
    if raw_length is not None:
        try:
            length = int(raw_length)
        except ValueError as exc:
            raise CloudBudgetProxyError("upstream_content_length_invalid") from exc
        if not 0 <= length <= MAX_RESPONSE_BYTES:
            raise CloudBudgetProxyError("upstream_response_too_large")
    body = upstream.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise CloudBudgetProxyError("upstream_response_too_large")
    return body


def _send(
    handler: BaseHTTPRequestHandler, status: int, body: bytes, content_type: str
) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Connection", "close")
    handler.end_headers()
    handler.close_connection = True
    try:
        handler.wfile.write(body)
        handler.wfile.flush()
    except (BrokenPipeError, ConnectionResetError):
        pass


def _response_usage(body: bytes) -> dict[str, int] | None:
    try:
        value = json.loads(body)
    except (UnicodeError, json.JSONDecodeError):
        return None
    return _usage(value.get("usage")) if isinstance(value, dict) else None


def _usage(value: Any) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    prompt = value.get("prompt_tokens")
    completion = value.get("completion_tokens")
    hit_value = value.get("prompt_cache_hit_tokens", value.get("cache_hit_tokens"))
    miss_value = value.get("prompt_cache_miss_tokens", value.get("cache_miss_tokens"))
    if not _count(prompt) or not _count(completion):
        return None
    if prompt > _MAX_PROMPT_TOKENS or completion > _MAX_COMPLETION_TOKENS:
        return None
    if hit_value is None and miss_value is None:
        hit, miss = 0, prompt
    else:
        if hit_value is not None and not _count(hit_value):
            return None
        if miss_value is not None and not _count(miss_value):
            return None
        hit = hit_value or 0
        miss = miss_value or 0
        if hit + miss > prompt:
            return None
        miss += prompt - hit - miss
    total = value.get("total_tokens")
    if total is not None and (not _count(total) or total != prompt + completion):
        return None
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cache_hit_tokens": hit,
        "cache_miss_tokens": miss,
    }


def _upstream_endpoint(value: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or "\\" in value
        or any(ord(character) < 0x20 for character in value)
    ):
        raise CloudBudgetProxyError("upstream_endpoint_invalid")
    try:
        parsed = urlsplit(value)
        parsed.port
    except ValueError as exc:
        raise CloudBudgetProxyError("upstream_endpoint_invalid") from exc
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") != "/chat/completions"
    ):
        raise CloudBudgetProxyError("upstream_endpoint_invalid")
    return value


def _cap(value: Decimal | str) -> Decimal:
    try:
        cap = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CloudBudgetProxyError("cap_invalid") from exc
    if isinstance(value, bool) or not cap.is_finite() or not 0 < cap <= _MAX_CAP_RMB:
        raise CloudBudgetProxyError("cap_invalid")
    return cap


def _stored_decimal(value: Any) -> Decimal:
    try:
        amount = Decimal(value) if isinstance(value, str) else Decimal("NaN")
    except InvalidOperation as exc:
        raise CloudBudgetProxyError("ledger_charge_invalid") from exc
    if not amount.is_finite() or amount < 0 or value != _decimal_text(amount):
        raise CloudBudgetProxyError("ledger_charge_invalid")
    return amount


def _charged(attempts: list[dict[str, Any]]) -> Decimal:
    return sum(
        (Decimal(row["conservative_charge_rmb"]) for row in attempts),
        start=Decimal("0"),
    )


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")


def _count(value: Any) -> bool:
    return type(value) is int and value >= 0
