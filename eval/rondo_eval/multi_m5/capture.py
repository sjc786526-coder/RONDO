"""Local Responses capture proxy: stub answers, or forwards to loopback upstream.

Stub and forward share the same listener, body capture, and JSONL writer so a
paid gate 1 run cannot silently grow a second capture path. Request bodies are
kept whole (F5). The listener binds 127.0.0.1 only. Forwarding is also
loopback-only; this module never opens a public or paid endpoint.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .loopback import LOOPBACK_BEARER, LOOPBACK_MODEL

_MAX_REQUEST_BYTES = 8 * 1024 * 1024
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024

RequestHandler = Callable[[dict[str, Any]], bytes]


class CaptureError(RuntimeError):
    """The capture proxy left its offline contract."""


class CaptureProxy:
    """Record every Responses body. Stub locally, or forward on loopback."""

    def __init__(
        self,
        *,
        mode: str,
        handler: RequestHandler | None = None,
        upstream_base_url: str | None = None,
        bearer: str = LOOPBACK_BEARER,
        model: str = LOOPBACK_MODEL,
        capture_path: Path | None = None,
        bind_host: str = "127.0.0.1",
    ) -> None:
        if bind_host != "127.0.0.1":
            raise CaptureError("capture proxy must bind only to 127.0.0.1")
        if mode not in {"stub", "forward"}:
            raise CaptureError("capture mode must be stub or forward")
        if mode == "stub":
            if handler is None:
                raise CaptureError("stub mode requires a request handler")
            if upstream_base_url is not None:
                raise CaptureError("stub mode must not take an upstream")
        else:
            if handler is not None:
                raise CaptureError("forward mode must not take a stub handler")
            _require_loopback_base_url(upstream_base_url)
        self.mode = mode
        self._handler = handler
        self._upstream = upstream_base_url.rstrip("/") if upstream_base_url else None
        self._bearer = bearer
        self._model = model
        self._bind_host = bind_host
        self._capture_path = capture_path
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.bodies: list[dict[str, Any]] = []

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._port()}/v1"

    def jsonl(self) -> str:
        with self._lock:
            return "".join(
                json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n"
                for body in self.bodies
            )

    def __enter__(self) -> CaptureProxy:
        return self.start()

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def start(self) -> CaptureProxy:
        if self._server is not None:
            raise CaptureError("capture proxy is already running")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # noqa: N802
                owner._handle_post(self)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer((self._bind_host, 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="rondo-multi-m5-capture",
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
            if thread.is_alive():
                raise CaptureError("capture proxy did not stop")

    def _port(self) -> int:
        if self._server is None:
            raise CaptureError("capture proxy is not running")
        host, port = self._server.server_address[:2]
        if host != "127.0.0.1" or not isinstance(port, int):
            raise CaptureError("capture proxy listener is not loopback-only")
        return port

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        authorization = handler.headers.get_all("Authorization", [])
        if authorization != [f"Bearer {self._bearer}"]:
            _reject(handler, 401, "unauthorized")
            return
        if handler.path != "/v1/responses":
            _reject(handler, 404, "responses_path_required")
            return
        try:
            length = int(handler.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if not 0 < length <= _MAX_REQUEST_BYTES:
            _reject(handler, 413, "request_size_invalid")
            return
        raw = handler.rfile.read(length)
        try:
            value = json.loads(raw)
        except (UnicodeError, json.JSONDecodeError):
            _reject(handler, 400, "json_invalid")
            return
        if not isinstance(value, dict) or value.get("model") != self._model:
            _reject(handler, 400, "request_contract_mismatch")
            return
        self._record(value)
        try:
            if self.mode == "stub":
                assert self._handler is not None
                payload = self._handler(value)
            else:
                payload = self._forward(raw, handler.headers)
        except CaptureError as exc:
            _reject(handler, 400, str(exc))
            return
        if not isinstance(payload, (bytes, bytearray)) or len(payload) > _MAX_RESPONSE_BYTES:
            _reject(handler, 500, "response_invalid")
            return
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-cache")
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.close_connection = True
        try:
            handler.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _record(self, body: dict[str, Any]) -> None:
        line = json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n"
        with self._lock:
            self.bodies.append(body)
            if self._capture_path is None:
                return
            path = self._capture_path
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if path.exists() and (path.is_symlink() or not path.is_file()):
                raise CaptureError("capture jsonl path is unsafe")
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
                handle.flush()

    def _forward(self, raw: bytes, headers: Any) -> bytes:
        parsed = urlsplit(self._upstream or "")
        host, port = parsed.hostname, parsed.port
        if host != "127.0.0.1" or not isinstance(port, int):
            raise CaptureError("forward upstream is not loopback")
        connection = HTTPConnection("127.0.0.1", port, timeout=30)
        try:
            forwarded = {
                "Authorization": headers.get("Authorization", ""),
                "Content-Type": "application/json",
                "Content-Length": str(len(raw)),
            }
            connection.request("POST", "/v1/responses", body=raw, headers=forwarded)
            response = connection.getresponse()
            payload = response.read(_MAX_RESPONSE_BYTES + 1)
            if response.status != 200 or len(payload) > _MAX_RESPONSE_BYTES:
                raise CaptureError("forward upstream rejected the request")
            return payload
        finally:
            connection.close()


def _require_loopback_base_url(value: str | None) -> None:
    if not isinstance(value, str) or not value:
        raise CaptureError("forward mode requires a loopback upstream")
    parsed = urlsplit(value)
    if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port is None:
        raise CaptureError("forward upstream must be http://127.0.0.1:<port>/v1")
    if parsed.path not in {"", "/v1", "/v1/"}:
        raise CaptureError("forward upstream path must be /v1")


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
    except (BrokenPipeError, ConnectionResetError):
        pass
