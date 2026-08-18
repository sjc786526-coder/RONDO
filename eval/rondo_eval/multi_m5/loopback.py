"""No-API loopback: frozen Multi binary must register and call team_publish."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping

from ..config import RepoPaths
from ..contracts import Product, Side
from .archive import archive_record
from .command import build_multi_exec_command, team_capability_overrides
from .load import M5ContractError, RuntimeIdentity, load_runtime_identity
from .store import scratch_root


LOOPBACK_BEARER = "rondo-multi-m5-loopback"
LOOPBACK_MODEL = "gpt-5.6-sol"
LOOPBACK_CALL_ID = "m5-team-publish-1"
LOOPBACK_PROVIDER = "rondo_eval_provider"
REQUIRED_TOOL_NAMES = (
    "team_publish",
    "team_update",
    "team_route",
    "team_evidence",
    "spawn_agent",
)
_MAX_REQUEST_BYTES = 8 * 1024 * 1024


class LoopbackError(RuntimeError):
    """The no-API Multi drill left its loopback contract."""


class TeamPublishFakeServer:
    """Loopback Responses stub: first turn calls team_publish, second turn ends."""

    def __init__(self, *, bind_host: str = "127.0.0.1", bearer: str = LOOPBACK_BEARER) -> None:
        if bind_host != "127.0.0.1":
            raise LoopbackError("loopback fake must bind only to 127.0.0.1")
        self._bind_host = bind_host
        self._bearer = bearer
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.bodies: list[dict[str, Any]] = []
        self._response_number = 0
        self.tool_round_trip = False
        self.missing_tools: tuple[str, ...] = ()

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._port()}/v1"

    def __enter__(self) -> TeamPublishFakeServer:
        return self.start()

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def start(self) -> TeamPublishFakeServer:
        if self._server is not None:
            raise LoopbackError("loopback fake is already running")
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
            name="rondo-multi-m5-loopback",
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
                raise LoopbackError("loopback fake did not stop")

    def _port(self) -> int:
        if self._server is None:
            raise LoopbackError("loopback fake is not running")
        host, port = self._server.server_address[:2]
        if host != "127.0.0.1" or not isinstance(port, int):
            raise LoopbackError("loopback fake listener is not loopback-only")
        return port

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        authorization = handler.headers.get_all("Authorization", [])
        if authorization != [f"Bearer {self._bearer}"]:
            self._reject(handler, 401, "unauthorized")
            return
        if handler.path != "/v1/responses":
            self._reject(handler, 404, "responses_path_required")
            return
        try:
            length = int(handler.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if not 0 < length <= _MAX_REQUEST_BYTES:
            self._reject(handler, 413, "request_size_invalid")
            return
        try:
            value = json.loads(handler.rfile.read(length))
        except (UnicodeError, json.JSONDecodeError):
            self._reject(handler, 400, "json_invalid")
            return
        if not isinstance(value, dict) or value.get("model") != LOOPBACK_MODEL:
            self._reject(handler, 400, "request_contract_mismatch")
            return
        try:
            payload = self._sse_response(value)
        except LoopbackError as exc:
            self._reject(handler, 400, str(exc))
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

    def _sse_response(self, request: dict[str, Any]) -> bytes:
        with self._lock:
            self._response_number += 1
            number = self._response_number
            self.bodies.append(request)
            if number == 1:
                names = collect_registered_tool_names(request)
                missing = tuple(name for name in REQUIRED_TOOL_NAMES if name not in names)
                self.missing_tools = missing
                if missing:
                    raise LoopbackError("required team tools were not registered")
                if _function_call_output(request) is not None:
                    raise LoopbackError("first request already contains tool output")
            elif number == 2:
                output = _function_call_output(request)
                if output is None or output.get("call_id") != LOOPBACK_CALL_ID:
                    raise LoopbackError("second request lacks team_publish output")
                self.tool_round_trip = True
            else:
                raise LoopbackError("loopback fake received an extra model round")
        response_id = f"resp-m5-loopback-{number}"
        item = (
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "call_id": LOOPBACK_CALL_ID,
                    "namespace": "collaboration",
                    "name": "team_publish",
                    "arguments": json.dumps(
                        {
                            "title": "loopback checkpoint",
                            "summary": "frozen Multi binary called team_publish",
                        },
                        separators=(",", ":"),
                    ),
                },
            }
            if number == 1
            else {
                "type": "response.output_item.done",
                "item": {
                    "type": "message",
                    "role": "assistant",
                    "id": "msg-m5-loopback-2",
                    "content": [{"type": "output_text", "text": "published"}],
                },
            }
        )
        events = (
            {"type": "response.created", "response": {"id": response_id}},
            item,
            {
                "type": "response.completed",
                "response": {
                    "id": response_id,
                    "usage": {
                        "input_tokens": 0,
                        "input_tokens_details": None,
                        "output_tokens": 0,
                        "output_tokens_details": None,
                        "total_tokens": 0,
                    },
                },
            },
        )
        text = "".join(
            f"event: {event['type']}\ndata: "
            f"{json.dumps(event, sort_keys=True, separators=(',', ':'))}\n\n"
            for event in events
        )
        return text.encode("utf-8")

    def _reject(self, handler: BaseHTTPRequestHandler, status: int, code: str) -> None:
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


def collect_tool_names(tools: object) -> set[str]:
    names: set[str] = set()
    _walk_tools(tools, names)
    return names


def collect_code_mode_tool_names(request: Mapping[str, Any]) -> set[str]:
    """Names the host registered for Code Mode when tools are not on the Responses body."""

    metadata = request.get("client_metadata")
    if not isinstance(metadata, dict):
        return set()
    raw = metadata.get("x-codex-turn-metadata")
    if not isinstance(raw, str) or not raw:
        return set()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return set()
    tools = payload.get("code_mode_tool_names") if isinstance(payload, dict) else None
    if not isinstance(tools, dict):
        return set()
    names: set[str] = set()
    for item in tools.values():
        if isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name:
                names.add(name)
    return names


def collect_registered_tool_names(request: Mapping[str, Any]) -> set[str]:
    return collect_tool_names(request.get("tools")) | collect_code_mode_tool_names(request)


def team_capability_command_items() -> tuple[str, ...]:
    return team_capability_overrides()


def team_capability_command_fragment() -> str:
    return team_capability_command_items()[0]


def build_loopback_command(
    binary: Path,
    *,
    base_url: str,
    instruction: str,
) -> list[str]:
    return build_multi_exec_command(
        binary,
        base_url=base_url,
        instruction=instruction,
        model=LOOPBACK_MODEL,
        effort="medium",
    )


def run_frozen_multi_team_publish_loopback(
    *,
    common_root: Path | None = None,
    identity: RuntimeIdentity | None = None,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    """Run the frozen Multi binary against a local SSE stub. No paid API."""

    paths = RepoPaths.discover(Path.cwd()) if common_root is None else None
    root = common_root or paths.common_root
    runtime = identity or load_runtime_identity(require_frozen=True, common_root=root)
    bundle = (root / runtime.bundle_relpath).resolve()
    binary = bundle / "codex"
    _require_executable(binary)
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    if digest != runtime.codex_sha256:
        raise LoopbackError("frozen Multi binary digest differs from the runtime lock")
    instruction = (
        "Publish one team checkpoint with team_publish titled loopback checkpoint, "
        "then stop. Do not spawn anyone."
    )
    scratch = scratch_root(root)
    with tempfile.TemporaryDirectory(prefix="rondo-m5-loopback-", dir=scratch) as raw:
        home = Path(raw) / "codex-home"
        workspace = Path(raw) / "workspace"
        home.mkdir(mode=0o700)
        workspace.mkdir(mode=0o700)
        (home / "auth.json").write_text(
            json.dumps({"OPENAI_API_KEY": LOOPBACK_BEARER}, separators=(",", ":")),
            encoding="utf-8",
        )
        os.chmod(home / "auth.json", 0o600)
        with TeamPublishFakeServer() as server:
            command = build_loopback_command(
                binary, base_url=server.base_url, instruction=instruction
            )
            env = {
                "CODEX_HOME": str(home),
                "HOME": str(home),
                "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                "LANG": "C.UTF-8",
                "LC_ALL": "C.UTF-8",
                "NO_PROXY": "127.0.0.1,localhost",
                "no_proxy": "127.0.0.1,localhost",
                "OPENAI_API_KEY": LOOPBACK_BEARER,
            }
            completed = subprocess.run(
                command,
                cwd=workspace,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=timeout_seconds,
                check=False,
            )
            if not server.tool_round_trip:
                registered = (
                    sorted(collect_registered_tool_names(server.bodies[0]))
                    if server.bodies
                    else []
                )
                detail = completed.stderr.decode("utf-8", "replace")[-2000:]
                raise LoopbackError(
                    "frozen Multi binary did not complete a team_publish round-trip: "
                    f"rc={completed.returncode} missing_tools={server.missing_tools} "
                    f"registered_tools={registered} requests={len(server.bodies)} "
                    f"stderr={detail}"
                )
    record = archive_record(
        evidence_kind="loopback",
        gate=1,
        lock_id="multi-m5-runtime-v1",
        side=Side.RONDO,
        product=Product.RONDO_MULTI,
        source_commit=runtime.source_commit,
        binary_sha256=digest,
        outcome="completed",
        counts_as_effective=False,
        extra={
            "loopback_tool_round_trip": True,
            "registered_tools": sorted(collect_registered_tool_names(server.bodies[0])),
            "ignored_evidence": [],
        },
    )
    return {
        "record": record,
        "request_count": len(server.bodies),
        "missing_tools": server.missing_tools,
        "returncode": completed.returncode,
    }


def _walk_tools(value: object, names: set[str]) -> None:
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str) and name:
            names.add(name)
        for item in value.values():
            _walk_tools(item, names)
    elif isinstance(value, list):
        for item in value:
            _walk_tools(item, names)


def _function_call_output(request: Mapping[str, Any]) -> dict[str, Any] | None:
    for item in _input_items(request):
        if not isinstance(item, dict):
            continue
        if item.get("type") == "function_call_output" and item.get("call_id") == LOOPBACK_CALL_ID:
            return item
        if item.get("call_id") == LOOPBACK_CALL_ID and "output" in item:
            return item
    return None


def _input_items(request: Mapping[str, Any]) -> list[Any]:
    value = request.get("input")
    if isinstance(value, list):
        return list(value)
    if isinstance(value, dict):
        nested = value.get("input")
        if isinstance(nested, list):
            return list(nested)
    return []


def _require_executable(path: Path) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise M5ContractError("frozen Multi binary is unavailable") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise M5ContractError("frozen Multi binary must be a regular file")
    if not os.access(path, os.X_OK):
        raise M5ContractError("frozen Multi binary is not executable")
