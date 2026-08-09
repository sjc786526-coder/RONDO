"""Supervised real-Docker Terminal-Bench smoke with a loopback no-API model."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import threading
import uuid
from dataclasses import dataclass, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable, Protocol

from ..config import ConfigError, RepoPaths, RuntimeConfig, load_runtime_config
from ..contracts import RunOutcome, Side
from ..docker_supervisor import (
    DockerCounter,
    DockerSupervisionError,
    HeavyLockGuard,
    HeavyLockLease,
)
from ..exit_codes import EVIDENCE_ERROR, INFRA_ERROR
from ..runtime_bridge import (
    DockerCliCounter,
    PowerShellDockerDesktopHostProbe,
    RuntimeBridgeError,
    lease_from_watchdog,
)
from .__main__ import _load_manifest
from .freeze import FIX_GIT_IMAGE_DIGEST
from .results import ParsedHarborResult, parse_single_task_result
from .runner import (
    DockerSupervisedHostHarborExecutor,
    HostHarborExecutor,
    HostHarborResult,
    InjectedHostHarborBackend,
    PreparedTerminalBenchRun,
    TaskMaterializer,
    TerminalBenchRequest,
    TerminalBenchRunError,
    UnifiedTerminalBenchRunner,
    prepare_terminal_bench_run,
)


NO_API_SMOKE_BEARER = "rondo-terminal-bench-no-api-smoke"
NO_API_SMOKE_MODEL = "gpt-5.6-luna"
_MAX_REQUEST_BYTES = 8 * 1024 * 1024


class DockerNoApiSmokeError(ValueError):
    """Raised when the no-API smoke would leave its loopback-only contract."""


@dataclass(frozen=True)
class SmokeRequestObservation:
    method: str
    path: str
    authorized: bool
    model: str | None
    websocket: bool
    accepted: bool
    rejection: str | None


@dataclass(frozen=True)
class DockerNoApiSmokeResult:
    prepared: PreparedTerminalBenchRun
    harbor: HostHarborResult
    parsed: ParsedHarborResult
    requests: tuple[SmokeRequestObservation, ...]

    @property
    def contract_satisfied(self) -> bool:
        accepted = [request for request in self.requests if request.accepted]
        return bool(accepted) and len(accepted) == len(self.requests)

    @property
    def passed(self) -> bool:
        return self.parsed.outcome is RunOutcome.COMPLETED and self.contract_satisfied

    def safe_summary(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "side": self.prepared.spec.side.value,
            "outcome": self.parsed.outcome.value,
            "task_outcome": self.parsed.task_outcome,
            "reward": self.parsed.reward,
            "fake_requests": len(self.requests),
            "fake_contract_hits": sum(request.accepted for request in self.requests),
            "fake_contract_satisfied": self.contract_satisfied,
            "host_returncode": self.harbor.returncode,
        }


class HostExecutorFactory(Protocol):
    def __call__(
        self,
        *,
        counter: DockerCounter,
        lock_guard: HeavyLockGuard,
        lease: HeavyLockLease,
    ) -> HostHarborExecutor: ...


class LocalResponsesFakeServer:
    """One loopback listener that accepts only the frozen no-API request shape."""

    def __init__(
        self,
        *,
        bind_host: str = "127.0.0.1",
        bearer: str = NO_API_SMOKE_BEARER,
    ) -> None:
        if bind_host != "127.0.0.1":
            raise DockerNoApiSmokeError("no-API fake must bind only to 127.0.0.1")
        if bearer != NO_API_SMOKE_BEARER:
            raise DockerNoApiSmokeError("no-API fake bearer differs from the fixed contract")
        self._bind_host = bind_host
        self._bearer = bearer
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._requests: list[SmokeRequestObservation] = []
        self._response_number = 0

    @property
    def loopback_base_url(self) -> str:
        port = self._port()
        return f"http://127.0.0.1:{port}/v1"

    @property
    def docker_base_url(self) -> str:
        port = self._port()
        return f"http://host.docker.internal:{port}/v1"

    @property
    def requests(self) -> tuple[SmokeRequestObservation, ...]:
        with self._lock:
            return tuple(self._requests)

    def __enter__(self) -> LocalResponsesFakeServer:
        return self.start()

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def start(self) -> LocalResponsesFakeServer:
        if self._server is not None:
            raise DockerNoApiSmokeError("no-API fake is already running")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # noqa: N802
                owner._handle_post(self)

            def do_GET(self) -> None:  # noqa: N802
                owner._reject_method(self)

            def do_PUT(self) -> None:  # noqa: N802
                owner._reject_method(self)

            def do_DELETE(self) -> None:  # noqa: N802
                owner._reject_method(self)

            def do_HEAD(self) -> None:  # noqa: N802
                owner._reject_method(self)

            def do_OPTIONS(self) -> None:  # noqa: N802
                owner._reject_method(self)

            def do_PATCH(self) -> None:  # noqa: N802
                owner._reject_method(self)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer((self._bind_host, 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="rondo-terminal-bench-no-api-fake",
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
                raise DockerNoApiSmokeError("no-API fake did not stop")

    def _port(self) -> int:
        if self._server is None:
            raise DockerNoApiSmokeError("no-API fake is not running")
        host, port = self._server.server_address[:2]
        if host != "127.0.0.1" or not isinstance(port, int) or not 1 <= port <= 65535:
            raise DockerNoApiSmokeError("no-API fake listener is not loopback-only")
        return port

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        websocket = "websocket" in handler.headers.get("Upgrade", "").lower()
        authorization = handler.headers.get_all("Authorization", [])
        authorized = authorization == [f"Bearer {self._bearer}"]
        if websocket:
            self._record(handler, authorized, None, websocket, "websocket_disabled")
            self._reject(handler, 400, "websocket_disabled")
            return
        if handler.path != "/v1/responses":
            self._record(handler, authorized, None, websocket, "responses_path_required")
            self._reject(handler, 404, "responses_path_required")
            return
        if not authorized:
            self._record(handler, False, None, websocket, "unauthorized")
            self._reject(handler, 401, "unauthorized")
            return
        try:
            length = int(handler.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if not 0 < length <= _MAX_REQUEST_BYTES:
            self._record(handler, True, None, websocket, "request_size_invalid")
            self._reject(handler, 413, "request_size_invalid")
            return
        body = handler.rfile.read(length)
        try:
            value = json.loads(body)
        except (UnicodeError, json.JSONDecodeError):
            value = None
        model = value.get("model") if isinstance(value, dict) else None
        if (
            not isinstance(value, dict)
            or model != NO_API_SMOKE_MODEL
            or value.get("stream") is not True
        ):
            self._record(handler, True, model, websocket, "request_contract_mismatch")
            self._reject(handler, 400, "request_contract_mismatch")
            return
        self._record(handler, True, model, websocket, None)
        payload = self._sse_response()
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

    def _reject_method(self, handler: BaseHTTPRequestHandler) -> None:
        self._record(handler, False, None, False, "post_required")
        self._reject(handler, 405, "post_required")

    def _record(
        self,
        handler: BaseHTTPRequestHandler,
        authorized: bool,
        model: str | None,
        websocket: bool,
        rejection: str | None,
    ) -> None:
        observation = SmokeRequestObservation(
            method=handler.command,
            path=handler.path,
            authorized=authorized,
            model=model,
            websocket=websocket,
            accepted=rejection is None,
            rejection=rejection,
        )
        with self._lock:
            self._requests.append(observation)

    def _sse_response(self) -> bytes:
        with self._lock:
            self._response_number += 1
            number = self._response_number
        response_id = f"resp-rondo-no-api-{number}"
        events = (
            {
                "type": "response.created",
                "response": {"id": response_id},
            },
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "message",
                    "role": "assistant",
                    "id": f"msg-rondo-no-api-{number}",
                    "content": [{"type": "output_text", "text": "done"}],
                },
            },
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


async def run_docker_no_api_smoke(
    config: RuntimeConfig,
    request: TerminalBenchRequest,
    *,
    counter: DockerCounter,
    lock_guard: HeavyLockGuard,
    lease: HeavyLockLease,
    materializer: TaskMaterializer | None = None,
    executor_factory: HostExecutorFactory = DockerSupervisedHostHarborExecutor,
    server_factory: Callable[[], LocalResponsesFakeServer] = LocalResponsesFakeServer,
) -> DockerNoApiSmokeResult:
    """Run the real Harbor/Docker chain while serving every model call locally."""

    if request.provider_transport_base_url is not None:
        raise DockerNoApiSmokeError("no-API smoke rejects caller-supplied provider transport")
    if not math.isfinite(request.budget_usd) or request.budget_usd <= 0:
        raise DockerNoApiSmokeError("no-API smoke RunSpec budget field is invalid")
    server = server_factory()
    with server:
        prepared = prepare_terminal_bench_run(
            config,
            replace(request, provider_transport_base_url=server.docker_base_url),
            materializer=materializer,
        )
        if prepared.spec.websocket or prepared.spec.provider.main_model != NO_API_SMOKE_MODEL:
            raise DockerNoApiSmokeError("no-API smoke projection differs from the frozen contract")
        executor = executor_factory(
            counter=counter,
            lock_guard=lock_guard,
            lease=lease,
        )
        backend = InjectedHostHarborBackend(
            executor,
            getenv=lambda name: (
                NO_API_SMOKE_BEARER
                if name == prepared.spec.provider.api_key_env
                else None
            ),
        )
        harbor = await UnifiedTerminalBenchRunner(backend).run(prepared)
        parsed = parse_single_task_result(
            harbor.jobs_dir,
            host_returncode=harbor.returncode,
        )
        observations = server.requests
    return DockerNoApiSmokeResult(
        prepared=prepared,
        harbor=harbor,
        parsed=parsed,
        requests=observations,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m rondo_eval.terminal_bench.docker_smoke"
    )
    parser.add_argument("--side", required=True, choices=[side.value for side in Side])
    parser.add_argument("--binary-manifest", required=True, type=Path)
    parser.add_argument("--docker-host-volume", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        paths = RepoPaths.discover(Path.cwd())
        config = load_runtime_config(paths)
        side = Side(args.side)
        manifest = _load_manifest(args.binary_manifest, paths.common_root)
        smoke_id = f"tb-no-api-{side.value}-{uuid.uuid4().hex[:12]}"
        work_root = paths.common_root / "eval-data" / "work" / smoke_id
        if work_root.exists() or work_root.is_symlink():
            raise DockerNoApiSmokeError("no-API smoke work directory already exists")
        work_root.mkdir(parents=True, mode=0o700)
        request = TerminalBenchRequest(
            side=side,
            batch_id="p1-no-api-smoke",
            binary=manifest,
            image_digest=FIX_GIT_IMAGE_DIGEST,
            source_checkout=str(
                paths.common_root
                / "eval-data"
                / "sources"
                / "terminal-bench-2-1-ffccbe05"
            ),
            staging_root=str(work_root / "staging"),
            docker_task_id=smoke_id,
            memory_bytes=2 * 1024**3,
            memory_swap_bytes=3 * 1024**3,
            pids_limit=256,
            provider_transport_base_url=None,
            timeout_seconds=args.timeout_seconds,
            max_retries=0,
            budget_usd=5.0,
        )
        proof = lease_from_watchdog()
        counter = DockerCliCounter(
            host_data_root=args.docker_host_volume,
            desktop_host_probe=PowerShellDockerDesktopHostProbe(),
        )
        result = asyncio.run(
            run_docker_no_api_smoke(
                config,
                request,
                counter=counter,
                lock_guard=proof.guard,
                lease=proof.lease,
            )
        )
        print(json.dumps(result.safe_summary(), sort_keys=True, separators=(",", ":")))
        return _smoke_exit_code(result)
    except (DockerSupervisionError, RuntimeBridgeError):
        return INFRA_ERROR
    except (ConfigError, DockerNoApiSmokeError, TerminalBenchRunError, OSError, ValueError):
        return EVIDENCE_ERROR


def _smoke_exit_code(result: DockerNoApiSmokeResult) -> int:
    if result.passed:
        return 0
    if result.parsed.outcome is RunOutcome.INFRA_FAILED:
        return INFRA_ERROR
    return EVIDENCE_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
