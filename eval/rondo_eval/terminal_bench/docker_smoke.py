"""Supervised real-Docker Terminal-Bench smoke with a loopback no-API model."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import re
import stat
import sys
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
from .results import (
    ParsedHarborResult,
    parse_single_task_result,
    validate_eval_harness_checkout,
)
from .pair import (
    PairIdentity,
    PairSequenceLedger,
    load_pair_identity,
    no_api_safe_summary_path,
    persist_no_api_safe_summary,
    validate_harbor_installation,
)
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
    HARBOR_EXECUTABLE,
    prepare_terminal_bench_run,
)


NO_API_SMOKE_BEARER = "rondo-terminal-bench-no-api-smoke"
NO_API_SMOKE_MODEL = "gpt-5.6-luna"
NO_API_SMOKE_CALL_ID = "rondo-code-mode-smoke-call"
NO_API_SMOKE_MARKER = "rondo_code_mode_smoke"
NO_API_SMOKE_CODE = (
    'text(JSON.stringify(await tools.exec_command({cmd:"printf '
    f'{NO_API_SMOKE_MARKER}'
    '"})));'
)
_MAX_REQUEST_BYTES = 8 * 1024 * 1024
_MAX_AGENT_JSON_BYTES = 16 * 1024 * 1024


class DockerNoApiSmokeError(ValueError):
    """Raised when the no-API smoke would leave its loopback-only contract."""

    def __init__(self, reason: str, *, samples: tuple[object, ...] = ()) -> None:
        super().__init__(reason)
        self.samples = samples


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
    agent_json_events: int
    tool_round_trip: bool
    pair_validation: bool = False

    @property
    def contract_satisfied(self) -> bool:
        accepted = [request for request in self.requests if request.accepted]
        return (
            len(accepted) == 2
            and len(accepted) == len(self.requests)
            and self.agent_json_events > 0
            and self.tool_round_trip
        )

    @property
    def passed(self) -> bool:
        return self.parsed.outcome is RunOutcome.COMPLETED and self.contract_satisfied

    def safe_summary(self) -> dict[str, object]:
        terminal_status = "completed" if self.passed else "failed"
        failure = None
        if terminal_status == "failed":
            failure = _trial_failure_diagnostic(self.parsed)
        summary: dict[str, object] = {
            "schema_version": 2,
            "side": self.prepared.spec.side.value,
            "terminal_status": terminal_status,
            "outcome": self.parsed.outcome.value,
            "task_outcome": self.parsed.task_outcome,
            "reward": self.parsed.reward,
            "fake_requests": len(self.requests),
            "fake_contract_hits": sum(request.accepted for request in self.requests),
            "fake_contract_satisfied": self.contract_satisfied,
            "agent_json_events": self.agent_json_events,
            "code_mode_tool_round_trip": self.tool_round_trip,
            "host_returncode": self.harbor.returncode,
            "pair_validation": self.pair_validation,
            "failure": failure,
            "artifacts": {
                "trial_result_sha256": _safe_artifact_sha256(
                    self.harbor.jobs_dir / "result.json"
                ),
                "trial_exception_sha256": _safe_artifact_sha256(
                    self.harbor.jobs_dir / "exception.txt"
                ),
                "watchdog_state": "parent_finalize_pending",
                "watchdog_summary_sha256": None,
            },
        }
        evidence = self.harbor.docker_evidence
        if evidence is None or not evidence.samples:
            summary["docker"] = {
                "state": "not_observed",
                "reason": "pre_daemon_failure",
                "cleanup": {
                    "state": "not_observed",
                    "container_count": None,
                    "network_count": None,
                    "volume_count": None,
                },
            }
        else:
            image = evidence.image_identity
            vhdx = evidence.desktop_vhdx
            metrics = evidence.container_metrics
            seccomp = evidence.effective_seccomp
            for item in (image, vhdx, metrics, seccomp):
                if item is not None:
                    item.validate()
            baseline, final = evidence.samples[0], evidence.samples[-1]
            runtime_facts = tuple(
                fact
                for sample in evidence.samples
                for fact in getattr(sample, "task_containers", ())
            )
            runtime = _runtime_projection(runtime_facts[0]) if runtime_facts else None
            cleanup = {
                "state": "verified_empty",
                "container_count": len(getattr(final, "task_container_ids", ())),
                "network_count": len(getattr(final, "task_networks", ())),
                "volume_count": len(getattr(final, "task_volumes", ())),
            }
            if any(
                cleanup[key] != 0
                for key in ("container_count", "network_count", "volume_count")
            ):
                cleanup["state"] = "unverified"
            summary["docker"] = {
                "state": "observed",
                "sample_count": len(evidence.samples),
                "baseline_total_bytes": baseline.docker_total_bytes,
                "final_total_bytes": final.docker_total_bytes,
                "baseline_task_bytes": baseline.task_bytes,
                "final_task_bytes": final.task_bytes,
                "baseline_data_root_free_bytes": baseline.data_root_filesystem_free_bytes,
                "final_data_root_free_bytes": final.data_root_filesystem_free_bytes,
                "image_identity": (
                    {
                        "image_reference": image.image_reference,
                        "image_id": image.image_id,
                    }
                    if image is not None
                    else None
                ),
                "desktop_vhdx": (
                    {
                        "baseline_bytes": vhdx.baseline_bytes,
                        "peak_bytes": vhdx.peak_bytes,
                        "final_bytes": vhdx.final_bytes,
                        "peak_growth_bytes": vhdx.peak_growth_bytes,
                    }
                    if vhdx is not None
                    else None
                ),
                "container_metrics": (
                    {
                        "container_id": metrics.container_id,
                        "cpu_usage_seconds": metrics.cpu_usage_seconds,
                        "peak_memory_bytes": metrics.peak_memory_bytes,
                    }
                    if metrics is not None
                    else None
                ),
                "effective_seccomp": (
                    {
                        "profile_kind": seccomp.profile_kind,
                        "profile_sha256": seccomp.profile_sha256,
                    }
                    if seccomp is not None
                    else None
                ),
                "runtime": runtime,
                "cleanup": cleanup,
            }
        return summary


def _safe_artifact_sha256(path: Path) -> str | None:
    try:
        metadata = path.lstat()
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size > 16 * 1024 * 1024
        ):
            return None
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


_ADAPTER_DIAGNOSTIC = re.compile(
    r"container command failed: stage=(install|run) "
    r"command_id=([a-z][a-z0-9_.-]{0,63}) "
    r"stderr=(empty|permission_denied|not_found|timeout|other_redacted)\Z"
)


def _trial_failure_diagnostic(parsed: ParsedHarborResult) -> dict[str, str]:
    exception = parsed.trial_result.get("exception_info")
    if isinstance(exception, dict):
        message = exception.get("exception_message", exception.get("message"))
        match = _ADAPTER_DIAGNOSTIC.fullmatch(message) if isinstance(message, str) else None
        if match is not None:
            return {
                "stage": f"adapter_{match.group(1)}",
                "command_id": match.group(2),
                "stderr_summary": match.group(3),
            }
    return {
        "stage": "result",
        "command_id": "no_api_contract",
        "stderr_summary": "empty",
    }


def _projection_sha256(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _runtime_projection(fact: object) -> dict[str, object]:
    # ``security_opt`` may carry Docker's expanded seccomp JSON.  Its identity
    # is recorded separately, so this projection retains only normalized NNP.
    security_opt = [
        "no-new-privileges:true"
        for value in getattr(fact, "security_opt")
        if value in {"no-new-privileges", "no-new-privileges:true"}
    ]
    mounts = [
        {
            "kind": item.kind,
            "destination": item.destination,
            "read_only": item.read_only,
            "tmpfs_options": list(item.tmpfs_options),
        }
        for item in sorted(getattr(fact, "mounts"), key=lambda item: item.destination)
    ]
    return {
        "privileged": getattr(fact, "privileged"),
        "cap_add": list(getattr(fact, "cap_add")),
        "cap_drop": list(getattr(fact, "cap_drop")),
        "security_opt": security_opt,
        "cgroupns_mode": getattr(fact, "cgroupns_mode"),
        "memory_bytes": getattr(fact, "memory_bytes"),
        "memory_swap_bytes": getattr(fact, "memory_swap_bytes"),
        "pids_limit": getattr(fact, "pids_limit"),
        "mounts_sha256": _projection_sha256(mounts),
        "networks_sha256": _projection_sha256(sorted(getattr(fact, "networks"))),
    }


def _docker_failure_from_samples(samples: tuple[object, ...]) -> dict[str, object]:
    if not samples:
        return {
            "state": "not_observed",
            "reason": "pre_daemon_failure",
            "cleanup": {
                "state": "not_observed",
                "container_count": None,
                "network_count": None,
                "volume_count": None,
            },
        }
    baseline, final = samples[0], samples[-1]
    facts = tuple(
        fact for sample in samples for fact in getattr(sample, "task_containers", ())
    )
    fact = facts[-1] if facts else None
    vhdx_values = [
        value
        for value in (
            getattr(sample, "docker_desktop_vhdx_bytes", None) for sample in samples
        )
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0
    ]
    metric_facts = tuple(
        metric
        for sample in samples
        for metric in getattr(sample, "task_container_metrics", ())
    )
    metric = metric_facts[-1] if metric_facts else None
    cleanup = {
        "state": "verified_empty",
        "container_count": len(getattr(final, "task_container_ids", ())),
        "network_count": len(getattr(final, "task_networks", ())),
        "volume_count": len(getattr(final, "task_volumes", ())),
    }
    if any(cleanup[key] for key in ("container_count", "network_count", "volume_count")):
        cleanup["state"] = "unverified"
    image = None
    seccomp = None
    if fact is not None:
        image = {
            "image_reference": getattr(fact, "image_reference"),
            "image_id": getattr(fact, "image_id"),
        }
        profile_sha = getattr(fact, "seccomp_profile_sha256", None)
        seccomp = {
            "profile_kind": "custom" if profile_sha is not None else "builtin",
            "profile_sha256": profile_sha,
        }
    return {
        "state": "observed_partial",
        "sample_count": len(samples),
        "baseline_total_bytes": getattr(baseline, "docker_total_bytes"),
        "final_total_bytes": getattr(final, "docker_total_bytes"),
        "baseline_task_bytes": getattr(baseline, "task_bytes"),
        "final_task_bytes": getattr(final, "task_bytes"),
        "baseline_data_root_free_bytes": getattr(
            baseline, "data_root_filesystem_free_bytes"
        ),
        "final_data_root_free_bytes": getattr(final, "data_root_filesystem_free_bytes"),
        "image_identity": image,
        "desktop_vhdx": (
            {
                "baseline_bytes": vhdx_values[0],
                "peak_bytes": max(vhdx_values),
                "final_bytes": vhdx_values[-1],
                "peak_growth_bytes": max(vhdx_values) - vhdx_values[0],
            }
            if len(vhdx_values) == len(samples)
            else None
        ),
        "container_metrics": (
            {
                "container_id": getattr(metric, "container_id"),
                "cpu_usage_seconds": getattr(metric, "cpu_usage_microseconds") / 1_000_000,
                "peak_memory_bytes": getattr(metric, "peak_memory_bytes"),
            }
            if metric is not None
            else None
        ),
        "effective_seccomp": seccomp,
        "runtime": _runtime_projection(fact) if fact is not None else None,
        "cleanup": cleanup,
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
        self._tool_round_trip = False

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

    @property
    def tool_round_trip(self) -> bool:
        with self._lock:
            return self._tool_round_trip

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
        try:
            payload = self._sse_response(value)
        except DockerNoApiSmokeError:
            self._record(handler, True, model, websocket, "tool_round_trip_mismatch")
            self._reject(handler, 400, "tool_round_trip_mismatch")
            return
        self._record(handler, True, model, websocket, None)
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

    def _sse_response(self, request: dict[str, object]) -> bytes:
        with self._lock:
            self._response_number += 1
            number = self._response_number
            if number == 1:
                if _find_custom_tool_output(request) is not None:
                    raise DockerNoApiSmokeError("first request already contains tool output")
            elif number == 2:
                output = _find_custom_tool_output(request)
                if output is None or not _contains_marker(output, NO_API_SMOKE_MARKER):
                    raise DockerNoApiSmokeError("second request lacks code-mode tool output")
                if isinstance(output, dict) and output.get("success") is False:
                    raise DockerNoApiSmokeError("code-mode tool output reports failure")
                self._tool_round_trip = True
            else:
                raise DockerNoApiSmokeError("no-API fake received an extra model round")
        response_id = f"resp-rondo-no-api-{number}"
        output_item = (
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "custom_tool_call",
                    "call_id": NO_API_SMOKE_CALL_ID,
                    "name": "exec",
                    "input": NO_API_SMOKE_CODE,
                },
            }
            if number == 1
            else {
                "type": "response.output_item.done",
                "item": {
                    "type": "message",
                    "role": "assistant",
                    "id": "msg-rondo-no-api-2",
                    "content": [{"type": "output_text", "text": "done"}],
                },
            }
        )
        events = (
            {"type": "response.created", "response": {"id": response_id}},
            output_item,
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
    pair_identity: PairIdentity,
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
    harbor: HostHarborResult | None = None
    try:
        with server:
            prepared = prepare_terminal_bench_run(
                config,
                replace(request, provider_transport_base_url=server.docker_base_url),
                materializer=materializer,
            )
            pair_identity.validate_prepared(prepared, mode="no_api")
            if (
                prepared.spec.websocket
                or prepared.spec.code_mode_host is not True
                or prepared.spec.sandbox_network_access is not True
                or prepared.spec.provider.main_model != NO_API_SMOKE_MODEL
            ):
                raise DockerNoApiSmokeError(
                    "no-API smoke projection differs from the frozen contract"
                )
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
            agent_json_events = (
                _validate_agent_codex_json(harbor.jobs_dir)
                if parsed.outcome is RunOutcome.COMPLETED
                else 0
            )
            observations = server.requests
    except Exception as exc:
        if getattr(exc, "samples", ()) or harbor is None or harbor.docker_evidence is None:
            raise
        raise DockerNoApiSmokeError(
            "no-API result validation failed after supervised execution",
            samples=tuple(harbor.docker_evidence.samples),
        ) from None
    return DockerNoApiSmokeResult(
        prepared=prepared,
        harbor=harbor,
        parsed=parsed,
        requests=observations,
        agent_json_events=agent_json_events,
        tool_round_trip=server.tool_round_trip,
    )


def _find_custom_tool_output(request: dict[str, object]) -> object | None:
    inputs = request.get("input")
    if not isinstance(inputs, list):
        return None
    matches = [
        item.get("output")
        for item in inputs
        if isinstance(item, dict)
        and item.get("type") == "custom_tool_call_output"
        and item.get("call_id") == NO_API_SMOKE_CALL_ID
    ]
    return matches[0] if len(matches) == 1 else None


def _contains_marker(value: object, marker: str) -> bool:
    if isinstance(value, str):
        return marker in value
    if isinstance(value, list):
        return any(_contains_marker(item, marker) for item in value)
    if isinstance(value, dict):
        return any(_contains_marker(item, marker) for item in value.values())
    return False


def _validate_agent_codex_json(jobs_dir: Path) -> int:
    """Reject incomplete or error-bearing Codex JSONL from the one-task smoke."""

    matches = list(jobs_dir.glob("agent/codex.txt"))
    if len(matches) != 1:
        raise DockerNoApiSmokeError("no-API smoke requires exactly one agent codex JSONL")
    path = matches[0]
    try:
        agent_dir = path.parent
        if agent_dir.is_symlink() or not stat.S_ISDIR(agent_dir.lstat().st_mode):
            raise DockerNoApiSmokeError("agent codex JSONL directory is unsafe")
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > _MAX_AGENT_JSON_BYTES:
            raise DockerNoApiSmokeError("agent codex JSONL is unsafe")
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise DockerNoApiSmokeError("agent codex JSONL is unreadable") from exc

    event_count = 0
    completed = False
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise DockerNoApiSmokeError("agent codex JSONL contains malformed output") from exc
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            raise DockerNoApiSmokeError("agent codex JSONL contains an invalid event")
        event_count += 1
        event_type = event["type"]
        item = event.get("item")
        if (
            event_type in {"error", "turn.failed"}
            or (
                event_type in {"item.started", "item.updated", "item.completed"}
                and isinstance(item, dict)
                and item.get("type") == "error"
            )
        ):
            raise DockerNoApiSmokeError("agent codex JSONL contains an error event")
        if event_type == "turn.completed":
            completed = True
    if not completed:
        raise DockerNoApiSmokeError("agent codex JSONL lacks turn completion")
    return event_count


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m rondo_eval.terminal_bench.docker_smoke"
    )
    parser.add_argument("--side", required=True, choices=[side.value for side in Side])
    parser.add_argument("--binary-manifest", required=True, type=Path)
    parser.add_argument("--docker-host-volume", required=True, type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument(
        "--pair-validation",
        action="store_true",
        help="consume the tracked RONDO-then-Codex no-API pair sequence",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        paths = RepoPaths.discover(Path.cwd())
        side = Side(args.side)
        pair_identity = load_pair_identity()
        no_api_mode = pair_identity.mode("no_api")
        sequence_path = (
            paths.common_root
            / "eval-data"
            / "pairs"
            / f"{pair_identity.pair_id}-no-api.json"
        )
        if args.pair_validation and (sequence_path.exists() or sequence_path.is_symlink()):
            with PairSequenceLedger(
                sequence_path,
                identity=pair_identity,
                mode="no_api",
            ) as sequence:
                recovered = sequence.reconcile_no_api_summary(requested_side=side)
            if recovered is not None:
                print(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "status": "recovered",
                            "pair_id": pair_identity.pair_id,
                            "run_id": recovered["run_id"],
                            "side": recovered["side"],
                            "requested_side": recovered["requested_side"],
                            "recovered_side": recovered["recovered_side"],
                            "terminal_status": recovered["status"],
                            "no_api_summary_sha256": recovered["no_api_summary_sha256"],
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                )
                return 0 if recovered["status"] == "completed" else INFRA_ERROR
        eval_harness_commit = validate_eval_harness_checkout(common_root=paths.common_root)
        config = load_runtime_config(paths)
        manifest = _load_manifest(args.binary_manifest, paths.common_root)
        seccomp_profile = pair_identity.validate_no_api_seccomp(
            project_root=paths.worktree_root
        )
        pair_identity.validate_manifest(
            common_root=paths.common_root,
            side=side,
            manifest_path=args.binary_manifest,
            manifest=manifest,
        )
        validate_harbor_installation(pair_identity, executable=HARBOR_EXECUTABLE)
        smoke_id = f"tb-no-api-{side.value}-{uuid.uuid4().hex[:12]}"
        work_root = paths.common_root / "eval-data" / "work" / smoke_id
        if work_root.exists() or work_root.is_symlink():
            raise DockerNoApiSmokeError("no-API smoke work directory already exists")
        work_root.mkdir(parents=True, mode=0o700)
        request = TerminalBenchRequest(
            side=side,
            batch_id=no_api_mode.batch_id,
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
            seccomp_profile_path=str(seccomp_profile),
            seccomp_profile_source_sha256=pair_identity.no_api_seccomp.source_sha256,
            seccomp_profile_effective_sha256=pair_identity.no_api_seccomp.effective_sha256,
            require_container_metrics=True,
        )
        proof = lease_from_watchdog()
        counter = DockerCliCounter(
            host_data_root=args.docker_host_volume,
            desktop_host_probe=PowerShellDockerDesktopHostProbe(),
        )
        if args.pair_validation:
            with PairSequenceLedger(
                sequence_path,
                identity=pair_identity,
                mode="no_api",
            ) as sequence:
                sequence.claim(
                    side=side,
                    run_id=smoke_id,
                    eval_harness_commit=eval_harness_commit,
                )
                try:
                    result = asyncio.run(
                        run_docker_no_api_smoke(
                            config,
                            request,
                            counter=counter,
                            lock_guard=proof.guard,
                            lease=proof.lease,
                            pair_identity=pair_identity,
                        )
                    )
                except Exception as exc:
                    failure_summary = _early_failure_summary(side=side, exc=exc)
                    summary_sha256 = persist_no_api_safe_summary(
                        no_api_safe_summary_path(
                            sequence_path,
                            identity=pair_identity,
                            run_id=smoke_id,
                        ),
                        identity=pair_identity,
                        side=side,
                        run_id=smoke_id,
                        eval_harness_commit=eval_harness_commit,
                        summary=failure_summary,
                    )
                    sequence.finish(
                        run_id=smoke_id,
                        completed=False,
                        eval_harness_commit=eval_harness_commit,
                        no_api_summary_sha256=summary_sha256,
                    )
                    raise
                result = replace(result, pair_validation=True)
                summary_sha256 = persist_no_api_safe_summary(
                    no_api_safe_summary_path(
                        sequence_path,
                        identity=pair_identity,
                        run_id=smoke_id,
                    ),
                    identity=pair_identity,
                    side=side,
                    run_id=smoke_id,
                    eval_harness_commit=eval_harness_commit,
                    summary=result.safe_summary(),
                )
                sequence.finish(
                    run_id=smoke_id,
                    completed=result.passed,
                    eval_harness_commit=eval_harness_commit,
                    no_api_summary_sha256=summary_sha256,
                )
        else:
            result = asyncio.run(
                run_docker_no_api_smoke(
                    config,
                    request,
                    counter=counter,
                    lock_guard=proof.guard,
                    lease=proof.lease,
                    pair_identity=pair_identity,
                )
            )
        print(json.dumps(result.safe_summary(), sort_keys=True, separators=(",", ":")))
        return _smoke_exit_code(result)
    except (DockerSupervisionError, RuntimeBridgeError) as exc:
        _print_safe_cli_error(exc, exit_code=INFRA_ERROR)
        return INFRA_ERROR
    except (
        ConfigError,
        DockerNoApiSmokeError,
        TerminalBenchRunError,
        OSError,
        ValueError,
    ) as exc:
        _print_safe_cli_error(exc, exit_code=EVIDENCE_ERROR)
        return EVIDENCE_ERROR


def _print_safe_cli_error(exc: BaseException, *, exit_code: int) -> None:
    reason = str(exc)
    if not reason or "\x00" in reason or "\n" in reason or "\r" in reason:
        reason = "no-API smoke failed without a safe single-line reason"
    print(
        json.dumps(
            {
                "schema_version": 1,
                "status": "error",
                "exit_code": exit_code,
                "error_type": type(exc).__name__,
                "reason": reason,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ),
        file=sys.stderr,
    )


def _early_failure_summary(*, side: Side, exc: BaseException) -> dict[str, object]:
    diagnostic_match = _ADAPTER_DIAGNOSTIC.fullmatch(str(exc))
    samples = tuple(getattr(exc, "samples", ()))
    if diagnostic_match is not None:
        stage = f"adapter_{diagnostic_match.group(1)}"
        command_id = diagnostic_match.group(2)
        stderr_summary = diagnostic_match.group(3)
    elif isinstance(exc, DockerSupervisionError):
        stage = "docker_supervision"
        command_id = "supervised_host"
        stderr_summary = "other_redacted"
    elif samples:
        stage = "result"
        command_id = "post_supervision_validation"
        stderr_summary = "other_redacted"
    elif isinstance(exc, TerminalBenchRunError):
        stage = "harbor"
        command_id = "harbor_trial"
        stderr_summary = "other_redacted"
    else:
        stage = "prepare"
        command_id = "no_api_prepare"
        stderr_summary = "other_redacted"
    return {
        "schema_version": 2,
        "side": side.value,
        "terminal_status": "failed",
        "outcome": RunOutcome.INFRA_FAILED.value,
        "task_outcome": None,
        "reward": 0.0,
        "fake_requests": 0,
        "fake_contract_hits": 0,
        "fake_contract_satisfied": False,
        "agent_json_events": 0,
        "code_mode_tool_round_trip": False,
        "host_returncode": 70,
        "pair_validation": True,
        "failure": {
            "stage": stage,
            "command_id": command_id,
            "stderr_summary": stderr_summary,
        },
        "docker": _docker_failure_from_samples(samples),
        "artifacts": {
            "trial_result_sha256": None,
            "trial_exception_sha256": None,
            "watchdog_state": "parent_finalize_pending",
            "watchdog_summary_sha256": None,
        },
    }


def _smoke_exit_code(result: DockerNoApiSmokeResult) -> int:
    if result.passed:
        return 0
    if result.parsed.outcome is RunOutcome.INFRA_FAILED:
        return INFRA_ERROR
    return EVIDENCE_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
