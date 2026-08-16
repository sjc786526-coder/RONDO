"""Task-only b10333 glue for the Plan 037 formal paired run.

This module deliberately does not reuse the production launcher identity or
qualification route.  It consumes a source-validated ``BuiltPairReceipt``,
derives every model/adapter argument from ``ResolvedDeployment``, runs at most
one side at a time, and leaves terminal durability to ``paired_outputs``.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import hashlib
import json
import os
import stat
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, ContextManager, Iterator, Mapping, Protocol, Sequence

from ..evidence import (
    STATIC_DECISION_SCHEMA,
    STATIC_DECISION_SCHEMA_NAME,
    STATIC_INSTRUCTIONS,
    STATIC_PAYLOAD_SCHEMA_VERSION,
    EvidenceError,
    PolicyIdentity,
    StaticApprovalPayload,
    validate_static_payload,
)
from . import client as local_client
from . import cross_eval, launcher, model_backed, paired_outputs


MODEL_ALIAS = "rondo-l6-paired-approval"
HOST = "127.0.0.1"
FROZEN_SERVER_SHA256 = paired_outputs.FROZEN_RUNTIME_SERVER_SHA256
STARTUP_TIMEOUT_SECONDS = 600.0
REQUEST_TIMEOUT_SECONDS = 180.0
_MAX_RESPONSE_BYTES = 1_048_576


class L6B10333PairError(RuntimeError):
    """Stable failure from the task-only paired b10333 boundary."""


class L6B10333RequestTimeout(RuntimeError):
    """A request reached its explicit per-sample deadline."""


class SideTransport(Protocol):
    def post(self, request: Mapping[str, Any]) -> Any: ...


SessionFactory = Callable[
    ...,
    ContextManager[SideTransport],
]


@dataclass(frozen=True)
class FormalPairArtifacts:
    outputs_path: Path
    pair_receipt_path: Path
    pair_evidence_path: Path
    log_dir: Path
    side_output_count: int
    outputs_sha256: str
    pair_receipt_sha256: str
    pair_evidence_sha256: str


@dataclass(frozen=True)
class SmokeArtifacts:
    receipt_path: Path
    log_dir: Path
    status: str
    sample_count: int
    terminal_count: int
    receipt_sha256: str


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _require_frozen_contract() -> None:
    expected_sampling = {
        "context_size": 12288,
        "max_output_tokens": 512,
        "temperature": 0.0,
        "top_p": 1.0,
        "seed": 42,
    }
    if (
        paired_outputs.FORMAL_SAMPLING_CONTRACT != expected_sampling
        or model_backed.QUALIFIED_CONTEXT_SIZE != 12288
        or model_backed.QUALIFIED_MAX_OUTPUT_TOKENS != 512
        or launcher.CHAT_TEMPLATE_SHA256 != paired_outputs.FROZEN_CHAT_SHA256
        or STATIC_PAYLOAD_SCHEMA_VERSION != 3
        or STATIC_DECISION_SCHEMA_NAME != "rondo_static_approval_v1"
        or cross_eval._canonical_sha256(STATIC_DECISION_SCHEMA)
        != "9d6eb425b9e73af31970c3e88f4b8cbeeaea9b41170d9b9b03d6611fa9cec212"
    ):
        raise L6B10333PairError("formal_pair_contract_drift")


def _actual_path(path: Path, *, executable: bool = False) -> Path:
    if not isinstance(path, Path):
        raise L6B10333PairError("formal_pair_path_invalid")
    try:
        info = os.lstat(path)
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise L6B10333PairError("formal_pair_path_missing") from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or (executable and not os.access(resolved, os.X_OK))
    ):
        raise L6B10333PairError("formal_pair_path_invalid")
    return resolved


def _component_path(
    deployment: paired_outputs.ResolvedDeployment,
    value: Mapping[str, Any],
) -> Path:
    return (
        deployment.manifest_path.parent
        / paired_outputs._component_relative_path(value["relative_path"])
    ).resolve(strict=True)


def _revalidate_resolved_deployment(
    deployment: paired_outputs.ResolvedDeployment,
) -> None:
    if (
        not isinstance(deployment, paired_outputs.ResolvedDeployment)
        or deployment.side not in paired_outputs.LOCAL_SIDE_ORDER
        or deployment.deployment_mode not in paired_outputs.DEPLOYMENT_MODES
    ):
        raise L6B10333PairError("resolved_deployment_invalid")
    try:
        inspected = paired_outputs.inspect_identity_source(
            paired_outputs.IdentitySource(
                "canonical_manifest",
                deployment.manifest_path,
                "resolved-deployment",
            )
        )
    except paired_outputs.PairedOutputError as exc:
        raise L6B10333PairError("resolved_deployment_drift") from exc
    manifest = inspected.get("deployment")
    if not isinstance(manifest, dict):
        raise L6B10333PairError("resolved_deployment_invalid")
    adapter_values = manifest["load_components"].get("adapter_files", {})
    expected_adapters = tuple(
        (name, _component_path(deployment, value))
        for name, value in sorted(adapter_values.items())
    )
    training_source = manifest["training_source"]
    expected_source_tree = (
        training_source["adapter_tree_sha256"]
        if training_source is not None
        else None
    )
    if (
        inspected["sha256"] != deployment.manifest_sha256
        or manifest["side"] != deployment.side
        or manifest["deployment_mode"] != deployment.deployment_mode
        or _component_path(
            deployment, manifest["load_components"]["model_gguf"]
        )
        != deployment.model_gguf.resolve(strict=True)
        or expected_adapters
        != tuple(
            (name, path.resolve(strict=True))
            for name, path in deployment.adapter_files
        )
        or _component_path(deployment, manifest["tooling"]["converter"])
        != deployment.converter.resolve(strict=True)
        or _component_path(deployment, manifest["tooling"]["quantizer"])
        != deployment.quantizer.resolve(strict=True)
        or manifest["quantization"] != deployment.quantization
        or expected_source_tree != deployment.source_adapter_tree_sha256
        or deployment.model_gguf.suffix.lower() != ".gguf"
        or any(path.suffix.lower() != ".gguf" for _name, path in expected_adapters)
    ):
        raise L6B10333PairError("resolved_deployment_drift")


def build_b10333_command(
    deployment: paired_outputs.ResolvedDeployment,
    *,
    runtime_binary: Path,
    chat_template: Path,
    port: int,
) -> list[str]:
    """Construct the exact side command from a freshly checked deployment."""

    _require_frozen_contract()
    _revalidate_resolved_deployment(deployment)
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise L6B10333PairError("formal_pair_port_invalid")
    binary = _actual_path(runtime_binary, executable=True)
    template = _actual_path(chat_template)
    try:
        binary_identity = paired_outputs.inspect_identity_source(
            paired_outputs.IdentitySource(
                "regular_file", binary, "b10333-runtime-binary"
            )
        )
        template_identity = paired_outputs.inspect_identity_source(
            paired_outputs.IdentitySource(
                "regular_file", template, "formal-chat-template"
            )
        )
    except paired_outputs.PairedOutputError as exc:
        raise L6B10333PairError("formal_pair_shared_source_invalid") from exc
    if (
        binary_identity["sha256"] != FROZEN_SERVER_SHA256
        or template_identity["sha256"] != paired_outputs.FROZEN_CHAT_SHA256
    ):
        raise L6B10333PairError("formal_pair_shared_source_drift")

    command = [
        os.fspath(binary),
        "--offline",
        "--no-models-autoload",
        "--no-ui",
        "--host",
        HOST,
        "--port",
        str(port),
        "--model",
        os.fspath(deployment.model_gguf.resolve(strict=True)),
        "--alias",
        MODEL_ALIAS,
        "--no-mmproj",
    ]
    for _name, adapter_path in deployment.adapter_files:
        command.extend(["--lora", os.fspath(adapter_path.resolve(strict=True))])
    serving = model_backed.serving_contract()
    command.extend(
        [
            "--gpu-layers",
            str(serving["gpu_layers"]),
            "--split-mode",
            "none",
            "--main-gpu",
            "0",
            "--fit",
            serving["fit"],
            "--ctx-size",
            str(paired_outputs.FORMAL_SAMPLING_CONTRACT["context_size"]),
            "--batch-size",
            str(serving["batch_size"]),
            "--ubatch-size",
            str(serving["ubatch_size"]),
            "--parallel",
            "1",
            "--verbosity",
            str(launcher.FORMAL_SERVE_LOG_VERBOSITY),
            "--flash-attn",
            serving["flash_attention"],
            "--cache-type-k",
            serving["cache_type_k"],
            "--cache-type-v",
            serving["cache_type_v"],
            "--jinja",
            "--chat-template-file",
            os.fspath(template),
            "--metrics",
            "--slots",
        ]
    )
    return command


def build_formal_request(approval_input: Mapping[str, Any]) -> dict[str, Any]:
    """Build the frozen b10333 Responses request from one accepted payload."""

    _require_frozen_contract()
    if not isinstance(approval_input, Mapping):
        raise L6B10333PairError("formal_pair_approval_input_invalid")
    logical = copy.deepcopy(dict(approval_input))
    policy = logical.get("guardian_policy")
    if not isinstance(policy, str) or not policy:
        raise L6B10333PairError("formal_pair_approval_input_invalid")
    try:
        payload = StaticApprovalPayload(
            PolicyIdentity(
                STATIC_PAYLOAD_SCHEMA_VERSION,
                "responses_lite",
                _sha256(policy.encode("utf-8")),
                "known",
            ),
            cross_eval._canonical_bytes(logical),
            logical,
        )
        validate_static_payload(payload)
    except (EvidenceError, cross_eval.CrossEvalError) as exc:
        raise L6B10333PairError("formal_pair_approval_input_invalid") from exc
    return {
        "model": MODEL_ALIAS,
        "instructions": (
            f"{STATIC_INSTRUCTIONS}\n\nGuardian policy follows exactly:\n{policy}"
        ),
        "input": copy.deepcopy(logical["input"]),
        "stream": False,
        "temperature": 0.0,
        "top_p": 1.0,
        "seed": 42,
        "max_output_tokens": 512,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": STATIC_DECISION_SCHEMA_NAME,
                "strict": True,
                "schema": copy.deepcopy(STATIC_DECISION_SCHEMA),
            },
        },
    }


class _HttpTransport:
    def __init__(self, responses_url: str, *, timeout_seconds: float) -> None:
        self.responses_url = responses_url
        self.timeout_seconds = timeout_seconds

    def post(self, request: Mapping[str, Any]) -> Any:
        raw_request = json.dumps(
            request,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        outbound = urllib.request.Request(
            self.responses_url,
            data=raw_request,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with local_client._NO_REDIRECT_OPENER.open(
                outbound, timeout=self.timeout_seconds
            ) as response:
                if response.status != 200 or response.geturl() != self.responses_url:
                    raise local_client.ServiceUnavailableError(
                        "formal paired endpoint returned a non-200 response"
                    )
                raw = response.read(_MAX_RESPONSE_BYTES + 1)
        except TimeoutError as exc:
            raise L6B10333RequestTimeout("b10333 request timed out") from exc
        except urllib.error.HTTPError as exc:
            raise local_client.ServiceUnavailableError(
                "formal paired endpoint is unavailable"
            ) from exc
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise L6B10333RequestTimeout("b10333 request timed out") from exc
            raise local_client.ServiceUnavailableError(
                "formal paired endpoint is unavailable"
            ) from exc
        except OSError as exc:
            raise local_client.ServiceUnavailableError(
                "formal paired endpoint is unavailable"
            ) from exc
        if len(raw) > _MAX_RESPONSE_BYTES:
            raise local_client.StructuredOutputError(
                "formal paired response exceeds the size limit"
            )
        try:
            return json.loads(raw)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise local_client.StructuredOutputError(
                "formal paired response is not valid JSON"
            ) from exc


def _wait_for_side(
    process: subprocess.Popen[Any],
    *,
    deployment: paired_outputs.ResolvedDeployment,
    base_url: str,
    startup_timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + startup_timeout_seconds
    health_url = base_url.removesuffix("/v1") + "/health"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise L6B10333PairError("formal_pair_server_exited_during_startup")
        try:
            health = launcher._get_json(health_url, timeout=0.5)
            if isinstance(health, dict) and health.get("status") == "ok":
                break
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            pass
        time.sleep(0.05)
    else:
        raise L6B10333PairError("formal_pair_server_startup_timeout")
    try:
        props = launcher._get_json(
            base_url.removesuffix("/v1") + "/props", timeout=1.0
        )
        models = launcher._get_json(f"{base_url}/models", timeout=1.0)
        adapters = launcher._get_json(
            base_url.removesuffix("/v1") + "/lora-adapters", timeout=1.0
        )
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise L6B10333PairError("formal_pair_server_identity_unavailable") from exc
    model_data = models.get("data") if isinstance(models, dict) else None
    expected_adapters = [
        {
            "id": index,
            "path": os.fspath(path.resolve(strict=True)),
            "scale": 1.0,
        }
        for index, (_name, path) in enumerate(deployment.adapter_files)
    ]
    if not isinstance(adapters, list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("id"), int)
        or isinstance(item.get("id"), bool)
        or not isinstance(item.get("path"), str)
        or not isinstance(item.get("scale"), (int, float))
        or isinstance(item.get("scale"), bool)
        for item in adapters
    ):
        raise L6B10333PairError("formal_pair_server_identity_mismatch")
    adapter_projection = [
        {key: item[key] for key in ("id", "path", "scale")} for item in adapters
    ]
    if (
        not isinstance(props, dict)
        or props.get("build_info") != model_backed.CUDA_SERVICE_BUILD_INFO
        or Path(str(props.get("model_path"))).resolve(strict=False)
        != deployment.model_gguf.resolve(strict=True)
        or not isinstance(model_data, list)
        or len(model_data) != 1
        or not isinstance(model_data[0], dict)
        or model_data[0].get("id") != MODEL_ALIAS
        or adapter_projection != expected_adapters
    ):
        raise L6B10333PairError("formal_pair_server_identity_mismatch")


@contextlib.contextmanager
def subprocess_side_session(
    *,
    deployment: paired_outputs.ResolvedDeployment,
    command: Sequence[str],
    base_url: str,
    log_path: Path,
    request_timeout_seconds: float = REQUEST_TIMEOUT_SECONDS,
    startup_timeout_seconds: float = STARTUP_TIMEOUT_SECONDS,
) -> Iterator[SideTransport]:
    """Start and stop exactly one task-only server process."""

    if (
        not isinstance(startup_timeout_seconds, (int, float))
        or isinstance(startup_timeout_seconds, bool)
        or startup_timeout_seconds <= 0
        or not isinstance(request_timeout_seconds, (int, float))
        or isinstance(request_timeout_seconds, bool)
        or request_timeout_seconds <= 0
    ):
        raise L6B10333PairError("formal_pair_timeout_invalid")
    try:
        parent_info = os.lstat(log_path.parent)
        if (
            stat.S_ISLNK(parent_info.st_mode)
            or not stat.S_ISDIR(parent_info.st_mode)
            or stat.S_IMODE(parent_info.st_mode) != 0o700
        ):
            raise L6B10333PairError("formal_pair_log_directory_invalid")
        if log_path.exists() or log_path.is_symlink():
            log_info = os.lstat(log_path)
            if (
                stat.S_ISLNK(log_info.st_mode)
                or not stat.S_ISREG(log_info.st_mode)
                or stat.S_IMODE(log_info.st_mode) != 0o600
            ):
                raise L6B10333PairError("formal_pair_server_log_invalid")
        flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        log_descriptor = os.open(log_path, flags, 0o600)
        try:
            opened = os.fstat(log_descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or stat.S_IMODE(opened.st_mode) != 0o600
            ):
                raise L6B10333PairError("formal_pair_server_log_invalid")
            process = subprocess.Popen(
                list(command),
                env=launcher._sanitized_environment(),
                stdout=log_descriptor,
                stderr=log_descriptor,
            )
        finally:
            os.close(log_descriptor)
    except L6B10333PairError:
        raise
    except (OSError, ValueError) as exc:
        raise L6B10333PairError("formal_pair_server_start_failed") from exc
    try:
        _wait_for_side(
            process,
            deployment=deployment,
            base_url=base_url,
            startup_timeout_seconds=float(startup_timeout_seconds),
        )
        yield _HttpTransport(
            f"{base_url}/responses", timeout_seconds=float(request_timeout_seconds)
        )
    finally:
        launcher._stop_server_process(process)
        if process.poll() is None:
            raise L6B10333PairError("formal_pair_server_cleanup_failed")


class SerialB10333Invoker:
    """Adapt one-side-at-a-time sessions to the existing durable runner."""

    def __init__(
        self,
        *,
        runtime_binary: Path,
        chat_template: Path,
        port: int,
        log_dir: Path,
        phase: str,
        session_factory: SessionFactory = subprocess_side_session,
    ) -> None:
        self.runtime_binary = runtime_binary
        self.chat_template = chat_template
        self.port = port
        self.log_dir = log_dir
        if phase not in {"smoke", "formal"}:
            raise L6B10333PairError("formal_pair_phase_invalid")
        self.phase = phase
        self.session_factory = session_factory
        self._side_index: int | None = None
        self._manager: ContextManager[SideTransport] | None = None
        self._transport: SideTransport | None = None

    def __enter__(self) -> "SerialB10333Invoker":
        return self

    def __exit__(self, *exc: object) -> None:
        self._close_side(*exc)

    def _close_side(self, *exc: object) -> None:
        manager = self._manager
        self._manager = None
        self._transport = None
        if manager is not None:
            manager.__exit__(*exc)

    def _start_side(
        self,
        side: str,
        deployment: paired_outputs.ResolvedDeployment,
    ) -> None:
        index = paired_outputs.LOCAL_SIDE_ORDER.index(side)
        if self._side_index is not None and index != self._side_index + 1:
            raise L6B10333PairError("formal_pair_side_order_invalid")
        self._close_side(None, None, None)
        command = build_b10333_command(
            deployment,
            runtime_binary=self.runtime_binary,
            chat_template=self.chat_template,
            port=self.port,
        )
        manager = self.session_factory(
            deployment=deployment,
            command=command,
            base_url=f"http://{HOST}:{self.port}/v1",
            log_path=self.log_dir / f"{self.phase}-{side}.log",
        )
        transport = manager.__enter__()
        self._side_index = index
        self._manager = manager
        self._transport = transport

    def __call__(
        self,
        side: str,
        approval_input: Mapping[str, Any],
        deployment: paired_outputs.ResolvedDeployment,
    ) -> dict[str, Any]:
        if side != deployment.side or side not in paired_outputs.LOCAL_SIDE_ORDER:
            raise L6B10333PairError("formal_pair_side_binding_invalid")
        index = paired_outputs.LOCAL_SIDE_ORDER.index(side)
        if self._side_index != index:
            self._start_side(side, deployment)
        if self._transport is None:
            raise L6B10333PairError("formal_pair_side_not_started")
        try:
            envelope = self._transport.post(build_formal_request(approval_input))
            return local_client._parse_response(envelope, expected_model=MODEL_ALIAS)
        except L6B10333RequestTimeout as exc:
            # The timed-out request may still occupy b10333's only slot. Stop
            # that side before the journal advances to another sample.
            self._close_side(type(exc), exc, exc.__traceback__)
            self._side_index = None
            raise paired_outputs.SampleTimeout("b10333-request-timeout") from exc
        except local_client.StructuredOutputError as exc:
            # b10333's non-streaming Responses builder always emits output_text
            # (server-task.cpp); it has no emitted typed refusal shape to map.
            raise paired_outputs.StructuredOutputFailure(
                "b10333-structured-output"
            ) from exc


def _require_private_directory(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise L6B10333PairError("formal_pair_private_directory_missing") from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise L6B10333PairError("formal_pair_private_directory_invalid")


def _server_log_directory(private_dir: Path) -> Path:
    _require_private_directory(private_dir)
    log_dir = private_dir / "server-logs"
    if not log_dir.exists() and not log_dir.is_symlink():
        os.mkdir(log_dir, 0o700)
    try:
        info = os.lstat(log_dir)
    except OSError as exc:
        raise L6B10333PairError("formal_pair_log_directory_invalid") from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise L6B10333PairError("formal_pair_log_directory_invalid")
    return log_dir


def _write_or_verify(path: Path, raw: bytes) -> None:
    if path.exists() or path.is_symlink():
        try:
            actual = cross_eval._safe_read(path, private=True)
        except cross_eval.CrossEvalError as exc:
            raise L6B10333PairError("formal_pair_artifact_invalid") from exc
        if actual != raw:
            raise L6B10333PairError("formal_pair_artifact_drift")
        return
    cross_eval._write_exclusive(path, raw, mode=0o600)


def prepare_pair_evidence(
    *,
    pair_receipt: paired_outputs.BuiltPairReceipt,
    private_dir: Path,
) -> tuple[Path, Path]:
    """Materialize and reload the two private formal pair evidence files."""

    _require_private_directory(private_dir)
    paired_outputs.formal_pair_evidence(pair_receipt)
    receipt_path = private_dir / "l6-pair-receipt.json"
    evidence_path = private_dir / "l6-pair-evidence.json"
    _write_or_verify(
        receipt_path, cross_eval._json_file_bytes(pair_receipt.receipt)
    )
    if evidence_path.exists() or evidence_path.is_symlink():
        existing = paired_outputs.load_pair_evidence_locator(evidence_path)
        if (
            existing.receipt != pair_receipt.receipt
            or existing.source_manifest != pair_receipt.source_manifest
        ):
            raise L6B10333PairError("formal_pair_evidence_drift")
    else:
        paired_outputs.write_pair_evidence_locator(pair_receipt, evidence_path)
    reloaded = paired_outputs.load_pair_evidence_locator(evidence_path)
    if (
        reloaded.receipt != pair_receipt.receipt
        or reloaded.source_manifest != pair_receipt.source_manifest
    ):
        raise L6B10333PairError("formal_pair_evidence_reload_mismatch")
    return receipt_path, evidence_path


def _structural_smoke_diagnostics(
    results: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    terminal_status_counts = {
        side: {status: 0 for status in cross_eval.OUTPUT_TERMINAL_STATUSES}
        for side in paired_outputs.LOCAL_SIDE_ORDER
    }
    for result in results:
        side = result.get("side")
        terminal = result.get("terminal")
        if side not in terminal_status_counts or not isinstance(terminal, dict):
            raise L6B10333PairError("formal_pair_smoke_invalid")
        try:
            cross_eval.validate_output_terminal(terminal)
        except cross_eval.CrossEvalError as exc:
            raise L6B10333PairError("formal_pair_smoke_invalid") from exc
        terminal_status_counts[side][terminal["status"]] += 1
    return {
        "decision_count_by_side": {
            side: terminal_status_counts[side]["decision"]
            for side in paired_outputs.LOCAL_SIDE_ORDER
        },
        "terminal_status_counts_by_side": terminal_status_counts,
    }


def run_structural_smoke(
    *,
    bundle: cross_eval.CohortBundle,
    pair_receipt: paired_outputs.BuiltPairReceipt,
    runtime_binary: Path,
    private_dir: Path,
    port: int,
    sample_count: int = 2,
    session_factory: SessionFactory = subprocess_side_session,
) -> SmokeArtifacts:
    """Run the same deterministic 1-2 samples on both sides without a journal."""

    _require_private_directory(private_dir)
    cross_eval.validate_cohort_bundle(bundle)
    if (
        not isinstance(sample_count, int)
        or isinstance(sample_count, bool)
        or sample_count not in {1, 2}
    ):
        raise L6B10333PairError("formal_pair_smoke_sample_count_invalid")
    receipt, receipt_sha256, _contracts, deployments = (
        paired_outputs._revalidate_built_pair_receipt(pair_receipt)
    )
    smoke_path = private_dir / "l6-pair-structural-smoke.json"
    if smoke_path.exists() or smoke_path.is_symlink():
        raise L6B10333PairError("formal_pair_smoke_already_exists")
    sample_ids = sorted(item["sample_id"] for item in bundle.manifest["items"])[
        :sample_count
    ]
    sources = dict(pair_receipt.sources)
    log_dir = _server_log_directory(private_dir)
    results: list[dict[str, Any]] = []
    with SerialB10333Invoker(
        runtime_binary=runtime_binary,
        chat_template=sources["chat-template"].path,
        port=port,
        log_dir=log_dir,
        phase="smoke",
        session_factory=session_factory,
    ) as invoke:
        for side in paired_outputs.LOCAL_SIDE_ORDER:
            for sample_id in sample_ids:
                source = bundle.source_rows[sample_id]
                try:
                    terminal = paired_outputs._decision_terminal(
                        invoke(side, source["input"], deployments[side])
                    )
                except paired_outputs.SampleTerminal as exc:
                    terminal = paired_outputs._failure_terminal(
                        exc.status, exc.failure_code
                    )
                results.append(
                    {
                        "side": side,
                        "sample_id": sample_id,
                        "terminal": terminal,
                    }
                )
    diagnostics = _structural_smoke_diagnostics(results)
    smoke_status = "passed"
    value = {
        "schema_version": 2,
        "contract_version": "rondo_l6_b10333_structural_smoke_v2",
        "status": smoke_status,
        "scope": "structural_smoke_not_formal_pair_output",
        "pair_receipt_sha256": receipt_sha256,
        "cohort_manifest_sha256": bundle.manifest_sha256,
        "sample_ids": sample_ids,
        "sides": list(paired_outputs.LOCAL_SIDE_ORDER),
        "sampling_contract": copy.deepcopy(
            receipt["shared_contract"]["sampling_contract"]
        ),
        "lifecycle": {
            "serial_side_sessions_completed": list(
                paired_outputs.LOCAL_SIDE_ORDER
            ),
            "process_cleanup_completed": True,
        },
        "diagnostics": diagnostics,
        "results": results,
        "results_sha256": cross_eval._canonical_sha256(results),
    }
    raw = cross_eval._json_file_bytes(value)
    cross_eval._write_exclusive(smoke_path, raw, mode=0o600)
    return SmokeArtifacts(
        smoke_path,
        log_dir,
        smoke_status,
        sample_count,
        len(results),
        _sha256(raw),
    )


def _require_structural_smoke(
    *,
    bundle: cross_eval.CohortBundle,
    pair_receipt: paired_outputs.BuiltPairReceipt,
    private_dir: Path,
) -> None:
    path = private_dir / "l6-pair-structural-smoke.json"
    try:
        value, raw = cross_eval._load_json(path, private=True)
    except cross_eval.CrossEvalError as exc:
        raise L6B10333PairError("formal_pair_smoke_required") from exc
    _receipt, receipt_sha256, _contracts, _deployments = (
        paired_outputs._revalidate_built_pair_receipt(pair_receipt)
    )
    fields = {
        "schema_version",
        "contract_version",
        "status",
        "scope",
        "pair_receipt_sha256",
        "cohort_manifest_sha256",
        "sample_ids",
        "sides",
        "sampling_contract",
        "lifecycle",
        "diagnostics",
        "results",
        "results_sha256",
    }
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or raw != cross_eval._json_file_bytes(value)
        or value.get("schema_version") != 2
        or value.get("contract_version")
        != "rondo_l6_b10333_structural_smoke_v2"
        or value.get("status") != "passed"
        or value.get("scope") != "structural_smoke_not_formal_pair_output"
        or value.get("pair_receipt_sha256") != receipt_sha256
        or value.get("cohort_manifest_sha256") != bundle.manifest_sha256
        or not isinstance(value.get("sample_ids"), list)
        or len(value["sample_ids"]) not in {1, 2}
        or value["sample_ids"]
        != sorted(item["sample_id"] for item in bundle.manifest["items"])[
            : len(value["sample_ids"])
        ]
        or value.get("sides") != list(paired_outputs.LOCAL_SIDE_ORDER)
        or value.get("sampling_contract")
        != paired_outputs.FORMAL_SAMPLING_CONTRACT
        or value.get("lifecycle")
        != {
            "serial_side_sessions_completed": list(
                paired_outputs.LOCAL_SIDE_ORDER
            ),
            "process_cleanup_completed": True,
        }
        or not isinstance(value.get("results"), list)
        or len(value["results"])
        != len(value["sample_ids"]) * len(paired_outputs.LOCAL_SIDE_ORDER)
        or value.get("results_sha256")
        != cross_eval._canonical_sha256(value["results"])
    ):
        raise L6B10333PairError("formal_pair_smoke_invalid")
    expected_keys = [
        (side, sample_id)
        for side in paired_outputs.LOCAL_SIDE_ORDER
        for sample_id in value["sample_ids"]
    ]
    actual_keys = []
    try:
        for result in value["results"]:
            if not isinstance(result, dict) or set(result) != {
                "side",
                "sample_id",
                "terminal",
            }:
                raise cross_eval.CrossEvalError("smoke_result_invalid")
            actual_keys.append((result["side"], result["sample_id"]))
            cross_eval.validate_output_terminal(result["terminal"])
    except cross_eval.CrossEvalError as exc:
        raise L6B10333PairError("formal_pair_smoke_invalid") from exc
    if actual_keys != expected_keys:
        raise L6B10333PairError("formal_pair_smoke_invalid")
    try:
        diagnostics = _structural_smoke_diagnostics(value["results"])
    except L6B10333PairError as exc:
        raise L6B10333PairError("formal_pair_smoke_invalid") from exc
    if value.get("diagnostics") != diagnostics:
        raise L6B10333PairError("formal_pair_smoke_invalid")


def run_formal_pair_bundle(
    *,
    worktree_root: Path,
    bundle: cross_eval.CohortBundle,
    pair_receipt: paired_outputs.BuiltPairReceipt,
    runtime_binary: Path,
    run_dir: Path,
    private_dir: Path,
    port: int,
    session_factory: SessionFactory = subprocess_side_session,
) -> FormalPairArtifacts:
    """Run, materialize, and formally re-import one complete paired bundle."""

    _require_private_directory(private_dir)
    paired_outputs.formal_pair_evidence(pair_receipt)
    _require_structural_smoke(
        bundle=bundle, pair_receipt=pair_receipt, private_dir=private_dir
    )
    sources = dict(pair_receipt.sources)
    log_dir = _server_log_directory(private_dir)
    receipt_path, evidence_path = prepare_pair_evidence(
        pair_receipt=pair_receipt, private_dir=private_dir
    )
    outputs_path = private_dir / "three-side-outputs.jsonl"
    receipt_raw = cross_eval._json_file_bytes(pair_receipt.receipt)

    with SerialB10333Invoker(
        runtime_binary=runtime_binary,
        chat_template=sources["chat-template"].path,
        port=port,
        log_dir=log_dir,
        phase="formal",
        session_factory=session_factory,
    ) as invoke:
        local_rows = paired_outputs.run_paired_outputs(
            bundle,
            pair_receipt=pair_receipt,
            run_dir=run_dir,
            invoke=invoke,
        )
    rows = paired_outputs.assemble_three_side_outputs(
        bundle, local_rows, pair_receipt=pair_receipt
    )
    outputs_raw = cross_eval._jsonl_bytes(rows)
    _write_or_verify(outputs_path, outputs_raw)
    _bundle, verified_rows, evidence = cross_eval.validate_three_side_import(
        worktree_root,
        outputs_path,
        receipt_path,
        pair_evidence_path=evidence_path,
    )
    if (
        not isinstance(evidence, cross_eval.FormalL6PairEvidence)
        or verified_rows != rows
    ):
        raise L6B10333PairError("formal_pair_verify_import_mismatch")
    evidence_raw = cross_eval._safe_read(evidence_path, private=True)
    return FormalPairArtifacts(
        outputs_path=outputs_path,
        pair_receipt_path=receipt_path,
        pair_evidence_path=evidence_path,
        log_dir=log_dir,
        side_output_count=len(rows),
        outputs_sha256=_sha256(outputs_raw),
        pair_receipt_sha256=_sha256(receipt_raw),
        pair_evidence_sha256=_sha256(evidence_raw),
    )


def _print_result(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _add_runtime_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--worktree-root", type=Path, required=True)
    command.add_argument("--pair-evidence-source", type=Path, required=True)
    command.add_argument("--runtime-binary", type=Path, required=True)
    command.add_argument("--port", type=int, required=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m rondo_eval.local_approval.l6_b10333_pair"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare-evidence")
    prepare.add_argument("--pair-id", required=True)
    prepare.add_argument("--base-model", type=Path, required=True)
    prepare.add_argument("--local-static-deployment", type=Path, required=True)
    prepare.add_argument("--local-ft-deployment", type=Path, required=True)
    prepare.add_argument("--training-receipt", type=Path, required=True)
    prepare.add_argument("--runtime-lock", type=Path, required=True)
    prepare.add_argument("--chat-template", type=Path, required=True)
    prepare.add_argument("--pair-contract", type=Path, required=True)
    prepare.add_argument(
        "--blind-identity-marker", action="append", required=True
    )
    prepare.add_argument("--private-dir", type=Path, required=True)

    show = commands.add_parser("show-commands")
    _add_runtime_arguments(show)
    smoke = commands.add_parser("smoke")
    _add_runtime_arguments(smoke)
    smoke.add_argument("--private-dir", type=Path, required=True)
    smoke.add_argument("--sample-count", type=int, choices=(1, 2), default=2)
    run = commands.add_parser("run")
    _add_runtime_arguments(run)
    run.add_argument("--run-dir", type=Path, required=True)
    run.add_argument("--private-dir", type=Path, required=True)
    resolve = commands.add_parser("resolve-interrupted")
    resolve.add_argument("--worktree-root", type=Path, required=True)
    resolve.add_argument("--pair-evidence-source", type=Path, required=True)
    resolve.add_argument("--run-dir", type=Path, required=True)
    resolve.add_argument("--failure-code", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "prepare-evidence":
            built = paired_outputs.build_pair_receipt(
                pair_id=args.pair_id,
                base_model=paired_outputs.IdentitySource(
                    "frozen_lock", args.base_model, "base-model-contract"
                ),
                local_static=paired_outputs.IdentitySource(
                    "canonical_manifest",
                    args.local_static_deployment,
                    "local-static-deployment",
                ),
                local_ft_static=paired_outputs.IdentitySource(
                    "canonical_manifest",
                    args.local_ft_deployment,
                    "local-ft-deployment",
                ),
                training_receipt=paired_outputs.IdentitySource(
                    "frozen_lock", args.training_receipt, "training-receipt"
                ),
                runtime_lock=paired_outputs.IdentitySource(
                    "frozen_lock", args.runtime_lock, "runtime-lock"
                ),
                chat_template=paired_outputs.IdentitySource(
                    "regular_file", args.chat_template, "chat-template"
                ),
                pair_contract=paired_outputs.IdentitySource(
                    "frozen_lock", args.pair_contract, "pair-contract"
                ),
                blind_identity_markers=args.blind_identity_marker,
            )
            receipt_path, evidence_path = prepare_pair_evidence(
                pair_receipt=built, private_dir=args.private_dir
            )
            _print_result(
                {
                    "status": "ready",
                    "pair_receipt": os.fspath(receipt_path),
                    "pair_receipt_sha256": _sha256(
                        cross_eval._safe_read(receipt_path, private=True)
                    ),
                    "pair_evidence": os.fspath(evidence_path),
                    "pair_evidence_sha256": _sha256(
                        cross_eval._safe_read(evidence_path, private=True)
                    ),
                }
            )
            return 0

        built = paired_outputs.load_pair_evidence_locator(
            args.pair_evidence_source
        )
        receipt, receipt_sha256, _contracts, deployments = (
            paired_outputs._revalidate_built_pair_receipt(built)
        )
        del receipt
        if args.command == "show-commands":
            chat_template = dict(built.sources)["chat-template"].path
            result = {
                "status": "ready",
                "pair_receipt_sha256": receipt_sha256,
                "commands": {
                    side: build_b10333_command(
                        deployments[side],
                        runtime_binary=args.runtime_binary,
                        chat_template=chat_template,
                        port=args.port,
                    )
                    for side in paired_outputs.LOCAL_SIDE_ORDER
                },
            }
        elif args.command == "smoke":
            smoke_artifacts = run_structural_smoke(
                bundle=cross_eval.load_synthetic_bundle(args.worktree_root),
                pair_receipt=built,
                runtime_binary=args.runtime_binary,
                private_dir=args.private_dir,
                port=args.port,
                sample_count=args.sample_count,
            )
            result = {
                "status": smoke_artifacts.status,
                "scope": "structural_smoke_not_formal_pair_output",
                "sample_count": smoke_artifacts.sample_count,
                "terminal_count": smoke_artifacts.terminal_count,
                "receipt": os.fspath(smoke_artifacts.receipt_path),
                "receipt_sha256": smoke_artifacts.receipt_sha256,
                "server_log_dir": os.fspath(smoke_artifacts.log_dir),
            }
        elif args.command == "run":
            artifacts = run_formal_pair_bundle(
                worktree_root=args.worktree_root,
                bundle=cross_eval.load_synthetic_bundle(args.worktree_root),
                pair_receipt=built,
                runtime_binary=args.runtime_binary,
                run_dir=args.run_dir,
                private_dir=args.private_dir,
                port=args.port,
            )
            result = {
                "status": "complete",
                "side_output_count": artifacts.side_output_count,
                "outputs": os.fspath(artifacts.outputs_path),
                "outputs_sha256": artifacts.outputs_sha256,
                "pair_receipt": os.fspath(artifacts.pair_receipt_path),
                "pair_receipt_sha256": artifacts.pair_receipt_sha256,
                "pair_evidence": os.fspath(artifacts.pair_evidence_path),
                "pair_evidence_sha256": artifacts.pair_evidence_sha256,
                "server_log_dir": os.fspath(artifacts.log_dir),
            }
        else:
            row = paired_outputs.resolve_interrupted_attempt(
                cross_eval.load_synthetic_bundle(args.worktree_root),
                pair_receipt=built,
                run_dir=args.run_dir,
                failure_code=args.failure_code,
            )
            result = {
                "status": "resolved",
                "side": row["side"],
                "sample_id": row["sample_id"],
                "terminal": row["terminal"],
            }
        _print_result(result)
        return 0
    except local_client.ServiceUnavailableError:
        _print_result(
            {"status": "not_ready", "blocker": "formal_pair_service_unavailable"}
        )
        return 2
    except local_client.StructuredOutputError:
        _print_result(
            {"status": "not_ready", "blocker": "formal_pair_structured_output"}
        )
        return 2
    except OSError:
        _print_result({"status": "not_ready", "blocker": "filesystem_error"})
        return 2
    except (
        L6B10333PairError,
        paired_outputs.PairedOutputError,
        cross_eval.CrossEvalError,
    ) as exc:
        _print_result({"status": "not_ready", "blocker": str(exc)})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
