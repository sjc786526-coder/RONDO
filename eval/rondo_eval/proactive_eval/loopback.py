"""No-API common-V2 loopback for both frozen comparison binaries."""

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
from typing import Any

from ..contracts import Product, Side, common_multi_agent_v2_override_items
from ..frozen_model_catalog import load_shared_model_catalog
from ..multi_m5.bundle import load_side_manifest
from ..multi_m5.load import load_runtime_identity
from ..multi_m5.loopback import collect_registered_tool_names
from ..multi_m5.store import scratch_root
from ..multi_m5.trace import find_trace_bundle
from ..team_lens.model import dump_team_view
from ..team_lens.reducer import reduce_bundle
from ..team_lens.report import render_report
from .contract import (
    COMMON_V2_TOOL_NAMES,
    CampaignContract,
    ContractError,
    require_common_v2_tool_projections,
)


_BEARER = "offline-loopback-only"
_REQUIRED_TOOLS = COMMON_V2_TOOL_NAMES
_MAX_REQUEST_BYTES = 8 * 1024 * 1024


class LoopbackError(RuntimeError):
    """Raised without exposing request or response bodies."""


class _Server:
    def __init__(
        self, *, policy: str, model: str, effort: str, run_prefix: str = "plan049"
    ) -> None:
        self.policy = policy
        self.model = model
        self.effort = effort
        self.run_prefix = run_prefix
        self.server: ThreadingHTTPServer | None = None
        self.thread: threading.Thread | None = None
        self.request_count = 0
        self.registered_tools: set[str] = set()
        self.policy_matched = False

    @property
    def base_url(self) -> str:
        if self.server is None:
            raise LoopbackError("loopback server is not running")
        return f"http://127.0.0.1:{self.server.server_address[1]}/v1"

    def __enter__(self):
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self) -> None:  # noqa: N802
                owner._post(self)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def __exit__(self, _type, _value, _traceback) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
        if self.thread is not None:
            self.thread.join(timeout=5)

    def _post(self, handler: BaseHTTPRequestHandler) -> None:
        if (
            handler.path != "/v1/responses"
            or handler.headers.get("Authorization") != f"Bearer {_BEARER}"
        ):
            self._reject(handler, 401)
            return
        try:
            length = int(handler.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if not 0 < length <= _MAX_REQUEST_BYTES:
            self._reject(handler, 413)
            return
        try:
            request = json.loads(handler.rfile.read(length))
        except (UnicodeError, json.JSONDecodeError):
            self._reject(handler, 400)
            return
        reasoning = request.get("reasoning") if isinstance(request, dict) else None
        if (
            not isinstance(request, dict)
            or request.get("model") != self.model
            or not isinstance(reasoning, dict)
            or reasoning.get("effort") != self.effort
        ):
            self._reject(handler, 400)
            return
        self.request_count += 1
        self.registered_tools = collect_registered_tool_names(request)
        self.policy_matched = _contains_exact_string(request, self.policy)
        if not _REQUIRED_TOOLS.issubset(self.registered_tools) or not self.policy_matched:
            self._reject(handler, 422)
            return
        response_id = f"resp-{self.run_prefix}-loopback-{self.request_count}"
        events = (
            {"type": "response.created", "response": {"id": response_id}},
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "message",
                    "role": "assistant",
                    "id": f"msg-{self.run_prefix}-loopback-{self.request_count}",
                    "content": [{"type": "output_text", "text": "loopback complete"}],
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
        payload = "".join(
            f"event: {event['type']}\ndata: {json.dumps(event, sort_keys=True, separators=(',', ':'))}\n\n"
            for event in events
        ).encode("utf-8")
        handler.send_response(200)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.close_connection = True
        try:
            handler.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    @staticmethod
    def _reject(handler: BaseHTTPRequestHandler, status: int) -> None:
        payload = b'{"error":{"code":"loopback_contract_rejected"}}'
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Connection", "close")
        handler.end_headers()
        handler.close_connection = True
        handler.wfile.write(payload)


def run_common_v2_loopback(
    contract: CampaignContract,
    *,
    common_root: Path,
    namespace: str,
    timeout_seconds: int = 120,
) -> dict[str, Any]:
    runtime = load_runtime_identity(require_frozen=True, common_root=common_root)
    ignored_root = Path(str(contract.lock["artifacts"]["ignored_root"]))
    output_root = Path(common_root) / ignored_root / "loopback" / namespace
    if output_root.exists():
        raise LoopbackError("loopback namespace already exists")
    output_root.mkdir(parents=True, mode=0o700)
    catalog_path: Path | None = None
    catalog_identity: dict[str, Any] | None = None
    if str(contract.lock.get("plan")) == "050":
        shared = load_shared_model_catalog(
            common_root,
            upstream_source_commit=str(runtime.baseline["source_commit"]),
            rondo_source_commit=str(runtime.source_commit),
            main_model=str(contract.lock["provider"]["root_model"]),
            guardian_model=str(contract.lock["provider"]["guardian_model"]),
            product=Product.RONDO_MULTI,
        )
        catalog_path = output_root / "shared-model-catalog.json"
        shared.write_private(catalog_path)
        catalog_identity = shared.identity()
    results: dict[str, Any] = {}
    for side in (Side.CODEX, Side.RONDO):
        manifest = load_side_manifest(runtime, side, common_root=common_root)
        binary = Path(manifest.path)
        _require_binary(binary, manifest.sha256)
        side_root = output_root / side.value
        trace_root = side_root / "rollout-trace"
        trace_root.mkdir(parents=True, mode=0o700)
        scratch = scratch_root(common_root)
        with tempfile.TemporaryDirectory(
            prefix=f"plan{contract.lock['plan']}-loopback-{side.value}-",
            dir=scratch,
        ) as raw:
            home = Path(raw) / "home"
            workspace = Path(raw) / "workspace"
            home.mkdir(mode=0o700)
            workspace.mkdir(mode=0o700)
            (home / "auth.json").write_text(
                json.dumps({"OPENAI_API_KEY": _BEARER}, separators=(",", ":")),
                "utf-8",
            )
            os.chmod(home / "auth.json", 0o600)
            with _Server(
                policy=contract.policy,
                model=str(contract.lock["provider"]["root_model"]),
                effort=str(contract.lock["provider"]["root_effort"]),
                run_prefix=f"plan{contract.lock['plan']}",
            ) as server:
                command = _command(
                    contract,
                    binary,
                    side,
                    server.base_url,
                    model_catalog_path=catalog_path,
                )
                completed = subprocess.run(
                    command,
                    cwd=workspace,
                    env={
                        "CODEX_HOME": str(home),
                        "HOME": str(home),
                        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
                        "LANG": "C.UTF-8",
                        "LC_ALL": "C.UTF-8",
                        "NO_PROXY": "127.0.0.1,localhost",
                        "no_proxy": "127.0.0.1,localhost",
                        "OPENAI_API_KEY": _BEARER,
                        "CODEX_ROLLOUT_TRACE_ROOT": str(trace_root),
                    },
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=timeout_seconds,
                    check=False,
                )
                if (
                    completed.returncode != 0
                    or server.request_count != 1
                    or not server.policy_matched
                    or not _REQUIRED_TOOLS.issubset(server.registered_tools)
                ):
                    raise LoopbackError(
                        f"{side.value} common-V2 loopback failed: "
                        f"returncode={completed.returncode} requests={server.request_count} "
                        f"policy_matched={server.policy_matched}"
                    )
        bundle = find_trace_bundle(trace_root)
        view = reduce_bundle(
            bundle,
            "codex" if side is Side.CODEX else "rondo-multi",
        )
        view_bytes = dump_team_view(view)
        report_bytes = render_report(view)
        (side_root / "team_view.json").write_bytes(view_bytes)
        (side_root / "team_report.html").write_bytes(report_bytes)
        results[side.value] = {
            "binary_sha256": manifest.sha256,
            "request_count": 1,
            "policy_sha256": contract.policy_sha256,
            "policy_matched": True,
            "registered_tool_projection": sorted(server.registered_tools),
            "team_state": None if side is Side.CODEX else True,
            "team_view_sha256": hashlib.sha256(view_bytes).hexdigest(),
            "team_report_sha256": hashlib.sha256(report_bytes).hexdigest(),
            "trace_bundle_count": 1,
            "command_projection": _command_projection(
                contract, model_catalog_identity=catalog_identity
            ),
        }
    try:
        require_common_v2_tool_projections(
            results["codex"]["registered_tool_projection"],
            results["rondo"]["registered_tool_projection"],
        )
    except ContractError as exc:
        raise LoopbackError(str(exc)) from exc
    summary = {
        "schema_version": 2,
        "evidence_kind": "loopback",
        "identity_class": "rehearsal",
        "lock_id": contract.lock_id,
        "lock_sha256": contract.lock_sha256,
        "policy_sha256": contract.policy_sha256,
        "namespace": namespace,
        "sides": results,
    }
    _write_or_verify(
        output_root / "loopback.json",
        (json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        ),
    )
    return summary


def _command(
    contract: CampaignContract,
    binary: Path,
    side: Side,
    base_url: str,
    *,
    model_catalog_path: Path | None = None,
) -> list[str]:
    product = None if side is Side.CODEX else Product.RONDO_MULTI
    provider = contract.lock["provider"]
    execution = contract.lock["execution"]
    overrides = (
        'approvals_reviewer="auto_review"',
        f'approval_policy={json.dumps(execution["approval_policy"])}',
        f'sandbox_mode={json.dumps(execution["sandbox_mode"])}',
        "sandbox_workspace_write.network_access=true",
        "features.code_mode_host=true",
        'model_provider="rondo_eval_provider"',
        'model_providers.rondo_eval_provider.name="Configured Provider"',
        f"model_providers.rondo_eval_provider.base_url={json.dumps(base_url)}",
        'model_providers.rondo_eval_provider.wire_api="responses"',
        "model_providers.rondo_eval_provider.requires_openai_auth=true",
        "model_providers.rondo_eval_provider.supports_websockets=false",
        "model_providers.rondo_eval_provider.request_max_retries=0",
        "model_providers.rondo_eval_provider.stream_max_retries=0",
        f'model_reasoning_effort={json.dumps(provider["root_effort"])}',
        *(
            (f"model_catalog_json={json.dumps(str(model_catalog_path))}",)
            if model_catalog_path is not None
            else ()
        ),
        *common_multi_agent_v2_override_items(
            side,
            product,
            subagent_model=str(provider["member_model"]),
            subagent_effort=str(provider["member_effort"]),
            max_concurrency=int(execution["max_concurrent_threads_per_session"]),
        ),
        f"developer_instructions={json.dumps(contract.policy)}",
    )
    command = [
        str(binary),
        "exec",
        "--strict-config",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--model",
        str(provider["root_model"]),
        "--json",
        "--enable",
        "unified_exec",
    ]
    for item in overrides:
        command.extend(("-c", item))
    command.extend(("--", "Finish this local loopback turn without changing files."))
    return command


def _command_projection(
    contract: CampaignContract,
    *,
    model_catalog_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Body-free statement of the exact model and concurrency CLI projection.

    The loopback makes one Root request. Member and Guardian values are proven
    as command/config projection here; no synthetic member or Guardian request
    is claimed.
    """

    provider = contract.lock["provider"]
    execution = contract.lock["execution"]
    value = {
        "root_model": provider["root_model"],
        "root_effort": provider["root_effort"],
        "member_model": provider["member_model"],
        "member_effort": provider["member_effort"],
        "guardian_model": provider["guardian_model"],
        "guardian_effort": provider["guardian_effort"],
        "max_concurrent_threads_per_session": execution[
            "max_concurrent_threads_per_session"
        ],
        "provider_request_concurrency": execution["provider_request_concurrency"],
        "approval_policy": execution["approval_policy"],
        "sandbox_mode": execution["sandbox_mode"],
        "root_request_observed": True,
        "member_request_observed": False,
        "guardian_request_observed": False,
    }
    if model_catalog_identity is not None:
        if (
            model_catalog_identity.get("main_model") != provider["root_model"]
            or model_catalog_identity.get("guardian_model")
            != provider["guardian_model"]
            or model_catalog_identity.get("override_target_slug")
            != provider["root_model"]
        ):
            raise LoopbackError("shared model catalog projection differs")
        value.update(
            {
                "model_catalog_sha256": model_catalog_identity["sha256"],
                "guardian_projection_source": "shared_model_catalog_override",
            }
        )
    return value


def _contains_exact_string(value: object, expected: str) -> bool:
    if value == expected:
        return True
    if isinstance(value, dict):
        return any(_contains_exact_string(item, expected) for item in value.values())
    if isinstance(value, list):
        return any(_contains_exact_string(item, expected) for item in value)
    return False


def _require_binary(path: Path, expected_sha256: str) -> None:
    metadata = path.lstat()
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or not os.access(path, os.X_OK)
        or hashlib.sha256(path.read_bytes()).hexdigest() != expected_sha256
    ):
        raise LoopbackError("frozen loopback binary identity differs")


def _write_or_verify(path: Path, payload: bytes) -> None:
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise LoopbackError("Plan 049 loopback summary drifted")
        return
    path.write_bytes(payload)
