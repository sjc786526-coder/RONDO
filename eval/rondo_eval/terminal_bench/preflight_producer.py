"""Produce the stub preflight receipts a fair-comparison campaign cannot start without.

This drives both frozen binaries through the real Harbor/Docker chain against a
loopback stub that answers every model call locally and can reach no provider.
The task-independent partitions of the two sides' first requests are compared,
and only if they agree is a receipt frozen and written for the paid runner to
consume.

Zero upstream requests and zero cost: the stub is the only endpoint the
containers can reach, and it terminates each turn immediately.  Running this is
a Docker task and is therefore separately authorized from the paid campaign.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import threading
import uuid
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from harbor.models.verifier.result import VerifierResult
from harbor.verifier.base import BaseVerifier

from ..api_budget_proxy import _inspect_request
from ..config import RepoPaths, load_runtime_config
from ..contracts import Side
from ..docker_supervisor import (
    DockerCounter,
    DockerSupervisionError,
    HeavyLockGuard,
    HeavyLockLease,
)
from ..runtime_bridge import (
    DockerCliCounter,
    PowerShellDockerDesktopHostProbe,
    lease_from_watchdog,
)
from ..fair_comparison import (
    FairComparisonError,
    PreflightReceipt,
    compare_task_independent,
    preflight_receipt_from_stub_run,
    task_independent_contract,
)
from .baseline import CampaignIdentity, RUN_CAP_USD, load_campaign_identity
from .baseline_cli import (
    _load_and_validate_manifests,
    preflight_receipt_path,
)
from .live import campaign_terminal_bench_request, project_shared_model_catalog
from .materialize import validate_frozen_task_source
from .pair import load_historical_pair_identity, validate_harbor_installation
from .results import validate_eval_harness_checkout
from .runner import (
    HARBOR_EXECUTABLE,
    DockerSupervisedHostHarborExecutor,
    HostHarborExecutor,
    InjectedHostHarborBackend,
    PREFLIGHT_STUB_VERIFIER_IMPORT,
    TaskMaterializer,
    UnifiedTerminalBenchRunner,
    prepare_terminal_bench_run,
)
from .tasksets import FrozenTask


PREFLIGHT_STUB_BEARER = "rondo-terminal-bench-preflight-stub"
_MAX_REQUEST_BYTES = 16 * 1024 * 1024
_MAX_STUB_ROUNDS = 4


class PreflightProductionError(RuntimeError):
    """The receipt cannot be produced without guessing or reaching upstream."""


class PreflightNoopVerifier(BaseVerifier):
    """Finish a stub trial without running task tests after capture completes."""

    async def verify(self) -> VerifierResult:
        return VerifierResult(rewards={"reward": 0})


class PreflightCaptureServer:
    """A loopback stub that records request bodies and ends every turn.

    It exists to make the frozen binaries emit exactly the request they would
    send upstream, and then stop.  It never opens an outbound connection.
    """

    def __init__(self, *, bind_host: str = "127.0.0.1") -> None:
        if bind_host != "127.0.0.1":
            raise PreflightProductionError("preflight stub must bind only to 127.0.0.1")
        self._bind_host = bind_host
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._bodies: list[bytes] = []
        self._rejections: list[str] = []

    @property
    def docker_base_url(self) -> str:
        return f"http://host.docker.internal:{self._port()}/v1"

    @property
    def bodies(self) -> tuple[bytes, ...]:
        with self._lock:
            return tuple(self._bodies)

    @property
    def rejections(self) -> tuple[str, ...]:
        with self._lock:
            return tuple(self._rejections)

    def __enter__(self) -> "PreflightCaptureServer":
        return self.start()

    def __exit__(self, _type: object, _value: object, _traceback: object) -> None:
        self.close()

    def start(self) -> "PreflightCaptureServer":
        if self._server is not None:
            raise PreflightProductionError("preflight stub is already running")
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # noqa: N802
                owner._handle_post(self)

            def do_GET(self) -> None:  # noqa: N802
                owner._reject(self, 405, "post_required")

            def do_PUT(self) -> None:  # noqa: N802
                owner._reject(self, 405, "post_required")

            def do_DELETE(self) -> None:  # noqa: N802
                owner._reject(self, 405, "post_required")

            def do_HEAD(self) -> None:  # noqa: N802
                owner._reject(self, 405, "post_required")

            def do_OPTIONS(self) -> None:  # noqa: N802
                owner._reject(self, 405, "post_required")

            def do_PATCH(self) -> None:  # noqa: N802
                owner._reject(self, 405, "post_required")

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer((self._bind_host, 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="rondo-preflight-capture-stub",
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
                raise PreflightProductionError("preflight stub did not stop")

    def _port(self) -> int:
        if self._server is None:
            raise PreflightProductionError("preflight stub is not running")
        host, port = self._server.server_address[:2]
        if host != "127.0.0.1" or not isinstance(port, int) or not 1 <= port <= 65535:
            raise PreflightProductionError("preflight stub listener is not loopback-only")
        return port

    def _handle_post(self, handler: BaseHTTPRequestHandler) -> None:
        if "websocket" in handler.headers.get("Upgrade", "").lower():
            self._record_rejection("websocket_disabled")
            self._reject(handler, 400, "websocket_disabled")
            return
        if handler.path != "/v1/responses":
            self._record_rejection("responses_path_required")
            self._reject(handler, 404, "responses_path_required")
            return
        if handler.headers.get_all("Authorization", []) != [
            f"Bearer {PREFLIGHT_STUB_BEARER}"
        ]:
            self._record_rejection("unauthorized")
            self._reject(handler, 401, "unauthorized")
            return
        try:
            length = int(handler.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if not 0 < length <= _MAX_REQUEST_BYTES:
            self._record_rejection("request_size_invalid")
            self._reject(handler, 413, "request_size_invalid")
            return
        body = handler.rfile.read(length)
        try:
            value = json.loads(body)
        except (UnicodeError, json.JSONDecodeError):
            value = None
        if not isinstance(value, dict) or value.get("stream") is not True:
            self._record_rejection("request_contract_mismatch")
            self._reject(handler, 400, "request_contract_mismatch")
            return
        with self._lock:
            if len(self._bodies) >= _MAX_STUB_ROUNDS:
                self._rejections.append("stub_round_limit")
                self._reject(handler, 429, "stub_round_limit")
                return
            self._bodies.append(body)
            number = len(self._bodies)
        payload = _terminal_sse(number)
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

    def _record_rejection(self, code: str) -> None:
        with self._lock:
            self._rejections.append(code)

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


def _terminal_sse(number: int) -> bytes:
    """Drive one bounded main -> Guardian -> main approval trajectory."""

    response_id = f"resp-rondo-preflight-{number}"
    if number == 1:
        output = {
            "type": "function_call",
            "name": "exec_command",
            "call_id": "call-rondo-preflight-approval",
            "arguments": json.dumps(
                {
                    "cmd": "true",
                    "sandbox_permissions": "require_escalated",
                    "justification": "Freeze the Guardian preflight contract.",
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
    elif number == 2:
        output = {
            "type": "message",
            "role": "assistant",
            "id": "msg-rondo-preflight-guardian",
            "content": [
                {
                    "type": "output_text",
                    "text": json.dumps(
                        {
                            "risk_level": "low",
                            "user_authorization": "high",
                            "outcome": "allow",
                            "rationale": "The preflight command is inert.",
                        },
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                }
            ],
        }
    else:
        output = {
            "type": "message",
            "role": "assistant",
            "id": f"msg-rondo-preflight-{number}",
            "content": [{"type": "output_text", "text": "preflight"}],
        }
    events = (
        {"type": "response.created", "response": {"id": response_id}},
        {
            "type": "response.output_item.done",
            "item": output,
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
    return "".join(
        f"event: {event['type']}\ndata: "
        f"{json.dumps(event, sort_keys=True, separators=(',', ':'))}\n\n"
        for event in events
    ).encode("utf-8")


async def capture_side_requests(
    config: object,
    *,
    identity: CampaignIdentity,
    side: Side,
    task: FrozenTask,
    binary: Any,
    paths: RepoPaths,
    seccomp_profile: Path,
    counter: DockerCounter,
    lock_guard: HeavyLockGuard,
    lease: HeavyLockLease,
    materializer: TaskMaterializer | None = None,
    executor_factory: Callable[..., HostHarborExecutor] = (
        DockerSupervisedHostHarborExecutor
    ),
    server_factory: Callable[[], PreflightCaptureServer] = PreflightCaptureServer,
) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Run one side and return its exact approval request trajectory."""

    provider = identity.provider_projection(config)
    identity.validate_provider(provider)
    validate_frozen_task_source(
        paths.common_root / "eval-data/sources/terminal-bench-2-1-ffccbe05",
        task,
    )
    stub_id = f"tb-preflight-{side.value}-{uuid.uuid4().hex[:12]}"
    work_root = paths.common_root / "eval-data" / "work" / stub_id
    if work_root.exists() or work_root.is_symlink():
        raise PreflightProductionError("preflight work directory already exists")
    work_root.mkdir(parents=True, mode=0o700)
    server = server_factory()
    with server:
        request = replace(
            campaign_terminal_bench_request(
                identity=identity,
                side=side,
                task=task,
                binary=binary,
                common_root=paths.common_root,
                work_root=work_root,
                docker_task_id=stub_id,
                seccomp_profile=seccomp_profile,
                budget_usd=float(RUN_CAP_USD),
            ),
            stub_verifier=True,
            delete_environment=False,
        )
        projected = project_shared_model_catalog(
            config,
            replace(request, provider_transport_base_url=server.docker_base_url),
            campaign_identity=identity,
            main_model=provider.main_model,
            guardian_model=provider.guardian_model,
            catalog_path=work_root / "shared-model-catalog.json",
        )
        prepared = prepare_terminal_bench_run(
            config,
            projected,
            materializer=materializer,
        )
        _validate_stub_projection(
            prepared,
            request=projected,
            identity=identity,
            task=task,
            provider=provider,
        )
        executor = executor_factory(
            counter=counter,
            lock_guard=lock_guard,
            lease=lease,
        )
        backend = InjectedHostHarborBackend(
            executor,
            getenv=lambda name: (
                PREFLIGHT_STUB_BEARER
                if name == prepared.spec.provider.api_key_env
                else None
            ),
        )
        await UnifiedTerminalBenchRunner(backend).run(prepared)
        bodies = server.bodies
        rejections = server.rejections
    if rejections:
        raise PreflightProductionError(
            f"preflight stub rejected a request: {rejections[0]}"
        )
    return _request_trace(bodies, provider=provider)


def _validate_stub_projection(
    prepared: object,
    *,
    request: Any,
    identity: CampaignIdentity,
    task: FrozenTask,
    provider: object,
) -> None:
    """Fail unless the stub run carries the same frozen facts as a paid slot.

    A receipt frozen from a differently projected request would certify a
    symmetry the paid run never has, so every fact the projection depends on is
    checked here rather than assumed.  The image and provider land on the
    prepared RunSpec; the seccomp and catalog bindings stay on the request.
    """

    spec = getattr(prepared, "spec", None)
    if spec is None:
        raise PreflightProductionError("preflight projection is incomplete")
    command = getattr(prepared, "command", None)
    if (
        command is None
        or getattr(command, "stub_verifier", None) is not True
        or getattr(command, "delete_environment", None) is not False
        or "--verifier" not in getattr(command, "argv", ())
        or PREFLIGHT_STUB_VERIFIER_IMPORT not in getattr(command, "argv", ())
        or "--no-delete" not in getattr(command, "argv", ())
        or "--delete" in getattr(command, "argv", ())
    ):
        raise PreflightProductionError(
            "preflight projection did not preserve the stub verifier boundary"
        )
    if (
        spec.task_id != task.task_id
        or spec.task_image_digest != task.image_digest
        or (
            identity.enforces_fair_comparison
            and spec.effective_product()
            is not (identity.product if spec.side is Side.RONDO else None)
        )
        or spec.provider.main_model != provider.main_model
        or spec.provider.guardian_model != provider.guardian_model
        or spec.provider.main_effort != provider.main_effort
        or spec.provider.guardian_effort != provider.guardian_effort
    ):
        raise PreflightProductionError(
            "preflight projection differs from the frozen campaign facts"
        )
    if (
        request.seccomp_profile_source_sha256
        != identity.no_api_seccomp["source_sha256"]
        or request.seccomp_profile_effective_sha256
        != identity.no_api_seccomp["effective_sha256"]
    ):
        raise PreflightProductionError(
            "preflight run does not carry the frozen seccomp profile"
        )
    if request.frozen_model_catalog_sha256 != str(identity.catalog_identity["sha256"]):
        raise PreflightProductionError(
            "preflight run does not carry the shared model catalog"
        )


def _request_trace(
    bodies: tuple[bytes, ...],
    *,
    provider: object,
) -> tuple[tuple[str, dict[str, Any]], ...]:
    """Require and return the exact approval request trajectory."""

    observed: list[tuple[str, dict[str, Any]]] = []
    for body in bodies:
        metadata = _inspect_request(
            body,
            None,
            main_model=provider.main_model,
            main_effort=provider.main_effort,
            guardian_model=provider.guardian_model,
            guardian_effort=provider.guardian_effort,
        )
        role = str(metadata["role"])
        observed.append((role, json.loads(body)))
    roles = tuple(role for role, _request in observed)
    if roles != ("main", "guardian", "main"):
        raise PreflightProductionError(
            "preflight run did not complete the controlled main-Guardian-main trajectory"
        )
    first_main = observed[0][1]
    final_main = observed[2][1]
    reasons = compare_task_independent(
        task_independent_contract(first_main),
        task_independent_contract(final_main),
    )
    if reasons:
        raise PreflightProductionError(
            "preflight main request contract drifted after Guardian: "
            + ";".join(reasons)
        )
    return tuple(observed)


def produce_preflight_receipts(
    paths: RepoPaths,
    *,
    identity: CampaignIdentity,
    seccomp_profile: Path,
    manifests: dict[Side, Any],
    counter: DockerCounter,
    lock_guard: HeavyLockGuard,
    lease: HeavyLockLease,
    config: object,
    capture: Callable[..., Any] | None = None,
) -> list[Path]:
    """Freeze and write one receipt per campaign task, both sides proved."""

    if not identity.enforces_fair_comparison:
        raise PreflightProductionError(
            "only fair-comparison campaigns consume preflight receipts"
        )
    run_capture = capture or (
        lambda **kwargs: asyncio.run(capture_side_requests(config, **kwargs))
    )
    pending: list[tuple[Path, PreflightReceipt]] = []
    for task in identity.catalog.tasks:
        requests_by_side = {
            side: run_capture(
                identity=identity,
                side=side,
                task=task,
                binary=manifests[side],
                paths=paths,
                seccomp_profile=seccomp_profile,
                counter=counter,
                lock_guard=lock_guard,
                lease=lease,
            )
            for side in (Side.RONDO, Side.CODEX)
        }
        try:
            receipt = preflight_receipt_from_stub_run(
                campaign_id=identity.campaign_id,
                campaign_lock_sha256=identity.lock_sha256,
                task_id=task.task_id,
                bundle_manifest_sha256={
                    side: str(bundle["manifest_sha256"])
                    for side, bundle in identity.bundles.items()
                },
                requests_by_side=requests_by_side,
            )
        except FairComparisonError as exc:
            raise PreflightProductionError(
                f"{task.task_id} is asymmetric on the stub: {';'.join(exc.reasons)}"
            ) from exc
        destination = preflight_receipt_path(paths, identity, task.task_id)
        pending.append((destination, receipt))
    for destination, receipt in pending:
        _require_receipt_publishable(destination, _receipt_bytes(receipt))
    for destination, receipt in pending:
        _atomic_receipt(destination, receipt)
    return [destination for destination, _receipt in pending]


def _atomic_receipt(path: Path, receipt: PreflightReceipt) -> None:
    """Write one receipt without ever leaving a partial file in place."""

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    encoded = _receipt_bytes(receipt)
    if _require_receipt_publishable(path, encoded):
        return
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        if temporary.exists() and not temporary.is_symlink():
            temporary.unlink()
        raise


def _receipt_bytes(receipt: PreflightReceipt) -> bytes:
    return (json.dumps(receipt.to_dict(), sort_keys=True, indent=2) + "\n").encode(
        "utf-8"
    )


def _require_receipt_publishable(path: Path, encoded: bytes) -> bool:
    """Return whether an identical receipt exists; reject every conflict."""

    if path.is_symlink():
        raise PreflightProductionError("preflight receipt path is a symlink")
    if path.exists():
        try:
            existing = path.read_bytes()
        except OSError as exc:
            raise PreflightProductionError(
                "preflight receipt already exists but cannot be verified"
            ) from exc
        if existing == encoded:
            return True
        raise PreflightProductionError(
            "preflight receipt already exists with different bytes"
        )
    return False


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m rondo_eval.terminal_bench.preflight_producer"
    )
    parser.add_argument("--docker-host-volume", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        paths = RepoPaths.discover(Path.cwd())
        identity = load_campaign_identity(paths)
        config = load_runtime_config(paths)
        expected_harness_commit = identity.comparison_conditions.eval_harness_commit
        eval_harness_commit = validate_eval_harness_checkout(
            common_root=paths.common_root,
            expected_commit=expected_harness_commit,
        )
        identity.require_declared_conditions(
            eval_harness_commit=eval_harness_commit
        )
        validate_harbor_installation(
            load_historical_pair_identity(), executable=HARBOR_EXECUTABLE
        )
        seccomp_profile = identity.validate_runtime_seccomp(
            project_root=paths.worktree_root
        )
        manifests = _load_and_validate_manifests(paths, identity)
        proof = lease_from_watchdog()
        counter = DockerCliCounter(
            host_data_root=args.docker_host_volume,
            desktop_host_probe=PowerShellDockerDesktopHostProbe(),
        )
        written = produce_preflight_receipts(
            paths,
            identity=identity,
            seccomp_profile=seccomp_profile,
            manifests=manifests,
            counter=counter,
            lock_guard=proof.guard,
            lease=proof.lease,
            config=config,
        )
    except (PreflightProductionError, DockerSupervisionError, ValueError) as exc:
        print(json.dumps({"status": "blocked", "reason": str(exc)}, sort_keys=True))
        return 3
    print(
        json.dumps(
            {
                "status": "frozen",
                "campaign_id": identity.campaign_id,
                "official_api_requests": 0,
                "actual_usd": 0.0,
                "receipts": [path.name for path in written],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
