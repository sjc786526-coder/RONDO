"""Restricted first-run qualification for the frozen 4k local approval contract.

This is a deliberately narrow, single-purpose entrypoint.  The formal launcher
keeps refusing to start a model until strict evidence exists, and nothing here
adds a reusable bypass: the qualification path only accepts the exact frozen
CUDA runtime, the single frozen GGUF and the 4k `auto`/`fit=on` contract, it
holds the same shared watchdog lease, and it writes evidence only after the
real structured decision *and* the on-site cleanup have both succeeded.

Nothing derived from the selected `E_final`, from the model's rationale or from
its generated text is printed or persisted; only identities, digests, counters
and durations leave this module.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import secrets
import socket
import stat
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from .. import runtime_bridge
from ..config import ConfigError, RepoPaths, RuntimeConfig, load_runtime_config
from ..evidence import build_static_payload
from ..exit_codes import CONFIG_ERROR, INFRA_ERROR, SUCCESS
from . import model_backed
from .client import (
    LocalApprovalClient,
    LocalApprovalError,
    LocalApprovalSettings,
    settings_from_config,
)
from .identity import clear_launcher_identity, publish_launcher_identity
from .launcher import (
    LLAMA_CPP_CUDA_CAPABILITY,
    _get_json,
    build_serve_command,
    inspect_runtime,
    model_path as resolve_model,
    serve_config_sha256,
    serve_environment,
)


_PRIVATE_ROOT = "eval-data/local-approval"
_READY_TIMEOUT_SECONDS = 420.0
_READY_POLL_SECONDS = 0.25
_STOP_TIMEOUT_SECONDS = 20.0
_PORT_RELEASE_TIMEOUT_SECONDS = 20.0
_VRAM_POLL_SECONDS = 0.2
_SLOT_POLL_SECONDS = 0.015
_MAX_EVIDENCE_INPUT_BYTES = 4_194_304
_NVIDIA_SMI_CANDIDATES = (
    Path("/usr/lib/wsl/lib/nvidia-smi"),
    Path("/usr/bin/nvidia-smi"),
)
_OFFLOAD = re.compile(r"offloaded\s+(\d+)\s*/\s*(\d+)\s+layers?\s+to\s+GPU", re.IGNORECASE)
# `inspect_runtime` already refuses to continue unless the frozen device probe
# reports this exact device, so the device name never depends on log wording.
CUDA_DEVICE_NAME = "NVIDIA GeForce RTX 4060 Laptop GPU"
_CUDA_MARKERS = (
    "ggml_cuda_init:",
    "CUDA0 model buffer size",
    "CUDA0 KV buffer size",
    "CUDA0 compute buffer size",
    "using device CUDA0",
)
# Only llama.cpp's own infrastructure lines may be echoed in a blocker report;
# request bodies never reach these prefixes.
_DIAGNOSTIC_LINE = re.compile(
    r"^(?:ggml_|load_tensors|llama_|print_info|init:|main:|srv |slot |build:|system_info)"
)
_DIAGNOSTIC_KEYWORD = re.compile(r"GPU|CUDA|layer|n_ctx|device", re.IGNORECASE)
_MAX_DIAGNOSTIC_LINES = 25


class QualificationError(RuntimeError):
    """Fail-closed qualification error carrying a stable, non-sensitive code."""

    exit_code = INFRA_ERROR

    def __init__(self, code: str, facts: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.facts = dict(facts or {})


@dataclass(frozen=True)
class EvidenceSource:
    path: Path
    relative_path: str
    sha256: str
    guardian_source_baseline: str
    guardian_source_commit: str


class NvidiaSmiSampler:
    """Device-level VRAM sampler for the exclusive-GPU qualification window."""

    def __init__(self, binary: Path | None = None) -> None:
        self.binary = binary or next(
            (path for path in _NVIDIA_SMI_CANDIDATES if path.is_file()), None
        )

    def _query(self, flag: str) -> list[str]:
        if self.binary is None:
            raise QualificationError("gpu_sampler_unavailable")
        try:
            completed = subprocess.run(
                [os.fspath(self.binary), flag, "--format=csv,noheader,nounits"],
                check=False,
                capture_output=True,
                text=True,
                timeout=20,
                env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise QualificationError("gpu_sampler_unavailable") from exc
        if completed.returncode != 0:
            raise QualificationError("gpu_sampler_unavailable")
        return [line for line in completed.stdout.splitlines() if line.strip()]

    def used_bytes(self) -> int:
        lines = self._query("--query-gpu=memory.used")
        if len(lines) != 1 or not lines[0].strip().isdigit():
            raise QualificationError("gpu_sampler_unavailable")
        return int(lines[0].strip()) * 1024 * 1024

    def compute_process_pids(self) -> list[int]:
        pids: list[int] = []
        for line in self._query("--query-compute-apps=pid"):
            value = line.split(",", 1)[0].strip()
            if value.isdigit():
                pids.append(int(value))
        return pids


def run_qualification(
    config: RuntimeConfig,
    *,
    evidence_relative_path: str,
    popen: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
    watchdog_factory: Callable[[], runtime_bridge.WatchdogProof] | None = None,
    gpu_sampler: Any | None = None,
    identity_publisher: Callable[..., Any] = publish_launcher_identity,
    identity_clearer: Callable[[RuntimeConfig, Any], None] = clear_launcher_identity,
    verify_identity: Callable[[RuntimeConfig, Path], None] | None = None,
    decide: Callable[[RuntimeConfig, Any], dict[str, Any]] | None = None,
    http_get: Callable[..., Any] = _get_json,
    clock: Callable[[], float] = time.monotonic,
    today: Callable[[], str] | None = None,
) -> dict[str, Any]:
    """Run one supervised qualification lifecycle and publish evidence at the end."""

    settings = settings_from_config(config)
    model_backed.require_qualification_contract(config, settings)
    if model_backed.evidence_exists(config):
        raise QualificationError("evidence_already_exists")
    source = _select_evidence_source(config, evidence_relative_path)
    payload = _static_payload(source)
    model = resolve_model(config, settings)

    watchdog = _lease(watchdog_factory)
    runtime = inspect_runtime(config, settings)
    if not runtime.ok or runtime.binary is None or runtime.identity_sha256 is None:
        raise QualificationError("runtime_not_ready")
    if runtime.capability != LLAMA_CPP_CUDA_CAPABILITY:
        raise QualificationError("runtime_capability_unexpected")

    sampler = gpu_sampler if gpu_sampler is not None else NvidiaSmiSampler()
    if sampler.compute_process_pids():
        raise QualificationError("gpu_not_exclusive")
    baseline_vram = sampler.used_bytes()
    _require_free_port(settings.host, settings.port)

    private_root = _prepare_private_directory(config)
    command = build_serve_command(config, settings, runtime.binary)
    serving_config = serve_config_sha256(config, settings)
    log_path = private_root / "server.log"
    process: subprocess.Popen[Any] | None = None
    identity = None
    decision_error: LocalApprovalError | None = None
    peak = _PeakSampler(sampler, baseline_vram)
    try:
        _require_watchdog(watchdog)
        peak.start()
        descriptor = os.open(
            log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
        )
        try:
            process = popen(
                command,
                env=serve_environment(config),
                stdout=descriptor,
                stderr=subprocess.STDOUT,
            )
        finally:
            os.close(descriptor)
        identity = identity_publisher(
            config,
            pid=process.pid,
            command=command,
            runtime_sha256=runtime.identity_sha256,
            model_sha256=settings.model_sha256,
            model_path=model,
            model_id=settings.model_id,
            base_url=settings.base_url,
            host=settings.host,
            port=settings.port,
            serve_config_sha256=serving_config,
        )
        props = _await_ready(process, settings, http_get, clock)
        _require_watchdog(watchdog)
        observed_context = _service_context_size(props)
        if verify_identity is None:
            _verify_service_identity(config, model)
        else:
            verify_identity(config, model)
        foreign = _foreign_compute_pids(sampler, process.pid)
        if foreign:
            raise QualificationError("gpu_not_exclusive", {"foreign_compute_pids": foreign})

        peak.observe()
        try:
            decision, ttft_ms, total_ms = _timed_decision(
                config, payload, settings, http_get, clock, decide
            )
        except LocalApprovalError as exc:
            decision_error = exc
        _require_watchdog(watchdog)
        peak.observe()
        peak.stop()
        peak_vram = peak.peak_bytes
    finally:
        peak.stop()
        # llama.cpp b10333 writes its load log through a fully buffered stdout,
        # so the offload facts are only complete once the process has exited.
        cleanup, log_text = _teardown(
            config, process, identity, settings, private_root, identity_clearer, log_path
        )

    if decision_error is not None:
        facts = _decision_failure_facts(log_text)
        facts["cleanup"] = cleanup
        raise QualificationError("structured_decision_failed", facts) from decision_error
    if not all(cleanup.values()):
        raise QualificationError("cleanup_incomplete")
    load_facts = _load_facts(log_text)
    observed = {
        "service_build_info": model_backed.CUDA_SERVICE_BUILD_INFO,
        "model_loaded": True,
        "cuda_device": load_facts["cuda_device"],
        "gpu_offloaded_layers": load_facts["offloaded_layers"],
        "gpu_total_layers": load_facts["total_layers"],
        "effective_context_size": observed_context,
        "vram": {
            "baseline_bytes": baseline_vram,
            "peak_bytes": peak_vram,
            "delta_bytes": peak_vram - baseline_vram,
            "method": (
                "nvidia-smi device-level memory.used sampled every "
                f"{int(_VRAM_POLL_SECONDS * 1000)}ms with no other CUDA compute process"
            ),
        },
        "time_to_first_token_ms": ttft_ms,
        "ttft_method": (
            "non-streaming request with /slots next_token.n_decoded polled every "
            f"{int(_SLOT_POLL_SECONDS * 1000)}ms; first positive value is the first token"
        ),
        "total_decision_ms": total_ms,
        "structured_response": _response_facts(decision),
        "evidence_source": {
            "relative_path": source.relative_path,
            "sha256": source.sha256,
            "request_shape": payload.policy_identity.request_shape,
            "guardian_source_baseline": source.guardian_source_baseline,
            "guardian_source_commit": source.guardian_source_commit,
        },
    }
    identity_record = model_backed.build_identity(
        settings,
        runtime_identity_sha256=runtime.identity_sha256,
        serve_config_sha256=serving_config,
    )
    stamp = today() if today is not None else datetime.date.today().isoformat()
    document = model_backed.evidence_document(
        identity_record, observed, cleanup, qualified_on=stamp
    )
    model_backed.write_evidence(config, document)
    return {
        "status": "qualified",
        "capability": model_backed.GPU_MODEL_SERVING_CAPABILITY,
        "gpu_offloaded_layers": observed["gpu_offloaded_layers"],
        "gpu_total_layers": observed["gpu_total_layers"],
        "effective_context_size": observed["effective_context_size"],
        "peak_vram_bytes": peak_vram,
        "vram_delta_bytes": peak_vram - baseline_vram,
        "time_to_first_token_ms": ttft_ms,
        "total_decision_ms": total_ms,
        "structured_response_valid": True,
        "cleanup": cleanup,
    }


class _PeakSampler:
    """Sample device VRAM in the background and keep only the peak value."""

    def __init__(self, sampler: Any, baseline: int) -> None:
        self._sampler = sampler
        self.peak_bytes = baseline
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def observe(self) -> None:
        try:
            used = self._sampler.used_bytes()
        except Exception:
            return
        if used > self.peak_bytes:
            self.peak_bytes = used

    def _run(self) -> None:
        while True:
            self.observe()
            if self._stop.wait(_VRAM_POLL_SECONDS):
                return

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None


def _lease(
    watchdog_factory: Callable[[], runtime_bridge.WatchdogProof] | None,
) -> runtime_bridge.WatchdogProof:
    try:
        watchdog = (watchdog_factory or runtime_bridge.lease_from_watchdog)()
        watchdog.lease.validate()
    except (AttributeError, TypeError, runtime_bridge.RuntimeBridgeError) as exc:
        raise QualificationError("watchdog_unavailable") from exc
    _require_watchdog(watchdog)
    return watchdog


def _require_watchdog(watchdog: runtime_bridge.WatchdogProof) -> None:
    try:
        held = watchdog.guard.is_held(watchdog.lease) is True
    except Exception:
        held = False
    if not held:
        raise QualificationError("watchdog_unavailable")


def _foreign_compute_pids(sampler: Any, server_pid: int) -> list[int]:
    """Report CUDA compute processes that this task's own server did not create.

    Device-level VRAM attribution is only meaningful while nothing else uses the
    GPU, but the qualified server itself legitimately appears here once it has
    initialised CUDA.
    """

    return [
        pid
        for pid in sampler.compute_process_pids()
        if not _belongs_to(pid, server_pid)
    ]


def _belongs_to(pid: int, ancestor: int) -> bool:
    seen: set[int] = set()
    current = pid
    while current > 1 and current not in seen:
        if current == ancestor:
            return True
        seen.add(current)
        try:
            raw = Path(f"/proc/{current}/stat").read_text(encoding="ascii")
            current = int(raw[raw.rindex(")") + 2 :].split()[1])
        except (OSError, UnicodeError, ValueError, IndexError):
            return False
    return current == ancestor


def _require_free_port(host: str, port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(1.0)
        if probe.connect_ex((host, port)) == 0:
            # Never touch a listener this task cannot identify; only report it.
            raise QualificationError("port_already_in_use")


def _prepare_private_directory(config: RuntimeConfig) -> Path:
    root = config.paths.common_root / _PRIVATE_ROOT
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.is_symlink() or not root.is_dir():
        raise QualificationError("private_directory_invalid")
    private_root = root / f"qualification-{secrets.token_hex(8)}"
    private_root.mkdir(mode=0o700)
    info = os.lstat(private_root)
    if stat.S_ISLNK(info.st_mode) or info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        raise QualificationError("private_directory_invalid")
    return private_root


def _select_evidence_source(config: RuntimeConfig, relative_path: str) -> EvidenceSource:
    """Bind one frozen archived `E_final` with verified production metadata."""

    candidate = Path(relative_path)
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or not relative_path.startswith("eval-data/runs/")
        or not relative_path.endswith("/E_final.json")
    ):
        raise QualificationError("evidence_source_path_invalid")
    path = config.paths.common_root / candidate
    if path.is_symlink() or not path.is_file():
        raise QualificationError("evidence_source_missing")
    if path.stat().st_size > _MAX_EVIDENCE_INPUT_BYTES:
        raise QualificationError("evidence_source_too_large")
    raw = path.read_bytes()
    meta_path = path.parent / "meta.json"
    if meta_path.is_symlink() or not meta_path.is_file():
        raise QualificationError("evidence_meta_missing")
    try:
        meta = json.loads(meta_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError("evidence_meta_invalid") from exc
    baseline = meta.get("guardian_source_baseline") if isinstance(meta, dict) else None
    commit = meta.get("guardian_source_commit") if isinstance(meta, dict) else None
    # A real archived Guardian evidence carries its production provenance; an
    # arbitrary JSON file dropped into the runs namespace does not.
    if (
        not isinstance(meta, dict)
        or meta.get("evidence") != "e_final"
        or not isinstance(baseline, str)
        or not baseline
        or not isinstance(commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", commit) is None
        or not isinstance(meta.get("review_id"), str)
        or not isinstance(meta.get("terminal_status"), str)
        or not meta.get("terminal_status")
        or not isinstance(meta.get("token_usage"), dict)
    ):
        raise QualificationError("evidence_meta_invalid")
    return EvidenceSource(
        path=path,
        relative_path=relative_path,
        sha256=hashlib.sha256(raw).hexdigest(),
        guardian_source_baseline=baseline,
        guardian_source_commit=commit,
    )


def _static_payload(source: EvidenceSource) -> Any:
    try:
        return build_static_payload(json.loads(source.path.read_bytes()))
    except Exception as exc:
        raise QualificationError("evidence_source_unparsable") from exc


def _await_ready(
    process: subprocess.Popen[Any],
    settings: LocalApprovalSettings,
    http_get: Callable[..., Any],
    clock: Callable[[], float],
) -> Any:
    origin = _origin(settings)
    deadline = clock() + _READY_TIMEOUT_SECONDS
    while clock() < deadline:
        if process.poll() is not None:
            raise QualificationError("server_exited_before_ready")
        try:
            health = http_get(f"{origin}/health", timeout=2.0)
        except Exception:
            time.sleep(_READY_POLL_SECONDS)
            continue
        if isinstance(health, dict) and health.get("status") == "ok":
            break
        time.sleep(_READY_POLL_SECONDS)
    else:
        raise QualificationError("server_not_ready_before_deadline")
    try:
        return http_get(f"{origin}/props", timeout=10.0)
    except Exception as exc:
        raise QualificationError("service_props_unavailable") from exc


def _origin(settings: LocalApprovalSettings) -> str:
    return f"http://{settings.host}:{settings.port}"


def _service_context_size(props: Any) -> int:
    defaults = props.get("default_generation_settings") if isinstance(props, dict) else None
    value = defaults.get("n_ctx") if isinstance(defaults, dict) else None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise QualificationError("service_context_unavailable")
    if value != model_backed.QUALIFIED_CONTEXT_SIZE:
        raise QualificationError("service_context_differs")
    if props.get("total_slots") != 1:
        raise QualificationError("service_slots_differ")
    return value


def _load_facts(text: str | None) -> dict[str, Any]:
    """Extract only allow-listed load facts from the private server output."""

    if text is None:
        raise QualificationError("server_output_unavailable")
    offload = _OFFLOAD.search(text)
    cuda_seen = any(marker in text for marker in _CUDA_MARKERS)
    if offload is None or not cuda_seen:
        raise QualificationError("gpu_offload_not_reported", _log_diagnostics(text))
    offloaded = int(offload.group(1))
    total = int(offload.group(2))
    if offloaded <= 0 or total <= 0 or offloaded > total:
        raise QualificationError("gpu_offload_not_positive", _log_diagnostics(text))
    return {
        "offloaded_layers": offloaded,
        "total_layers": total,
        "cuda_device": CUDA_DEVICE_NAME,
    }


def _log_diagnostics(text: str) -> dict[str, Any]:
    """Summarise the private server output without echoing any request data."""

    lines = text.splitlines()
    selected = [
        line.strip()[:160]
        for line in lines
        if _DIAGNOSTIC_LINE.match(line.strip()) and _DIAGNOSTIC_KEYWORD.search(line)
    ]
    return {
        "log_bytes": len(text),
        "log_lines": len(lines),
        "infrastructure_lines": selected[:_MAX_DIAGNOSTIC_LINES],
    }


def _decision_failure_facts(text: str | None) -> dict[str, Any]:
    """Read only allow-listed counters out of the private server output.

    A rejected request is far easier to act on with the server's own token
    accounting than with a bare transport error, and the numbers below carry no
    evidence content.
    """

    if text is None:
        return {}
    facts: dict[str, Any] = {}
    tokens = re.search(r"(?:input|request) \((\d+) tokens\)", text)
    if tokens is not None:
        facts["prompt_tokens"] = int(tokens.group(1))
    limit = re.search(r"(?:max|available) context size \((\d+) tokens\)", text)
    if limit is not None:
        facts["context_size"] = int(limit.group(1))
    for marker in (
        "exceeds the available context size",
        "is larger than the max context size",
        "is too large to process",
    ):
        if marker in text:
            facts["server_error_class"] = marker
            break
    return facts


def _timed_decision(
    config: RuntimeConfig,
    payload: Any,
    settings: LocalApprovalSettings,
    http_get: Callable[..., Any],
    clock: Callable[[], float],
    decide: Callable[[RuntimeConfig, Any], dict[str, Any]] | None,
) -> tuple[dict[str, Any], float, float]:
    """Send the single real request and observe the first token as it happens.

    b10333 only reports its predicted-token counters after a request completes,
    so `/metrics` cannot express time-to-first-token for this non-streaming
    contract.  `/slots` publishes the live `next_token.n_decoded` of the active
    slot, which turns positive exactly when the first token has been decoded.
    """

    observer = _FirstTokenObserver(_origin(settings), http_get, clock)
    runner = decide or (lambda cfg, item: LocalApprovalClient(cfg).decide(item))
    # The clock starts before the observer so a first token can never be dated
    # earlier than the measurement window it belongs to.
    started = clock()
    observer.start()
    try:
        decision = runner(config, payload)
    finally:
        observer.stop()
    total_ms = (clock() - started) * 1000.0
    if observer.first_token_at is None:
        raise QualificationError("first_token_not_observed")
    ttft_ms = (observer.first_token_at - started) * 1000.0
    if ttft_ms <= 0 or ttft_ms > total_ms:
        raise QualificationError("first_token_timing_invalid")
    return decision, ttft_ms, total_ms


class _FirstTokenObserver:
    def __init__(
        self,
        origin: str,
        http_get: Callable[..., Any],
        clock: Callable[[], float],
    ) -> None:
        self._origin = origin
        self._http_get = http_get
        self._clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.first_token_at: float | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                slots = self._http_get(f"{self._origin}/slots", timeout=2.0)
            except Exception:
                slots = None
            if _decoded_tokens(slots) > 0:
                self.first_token_at = self._clock()
                return
            self._stop.wait(_SLOT_POLL_SECONDS)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=10)
            self._thread = None


def _decoded_tokens(slots: Any) -> int:
    if not isinstance(slots, list):
        return 0
    total = 0
    for slot in slots:
        if not isinstance(slot, dict) or slot.get("is_processing") is not True:
            continue
        next_token = slot.get("next_token")
        entries = next_token if isinstance(next_token, list) else [next_token]
        for entry in entries:
            value = entry.get("n_decoded") if isinstance(entry, dict) else None
            if isinstance(value, int) and not isinstance(value, bool) and value > 0:
                total += value
    return total


def _response_facts(decision: Any) -> dict[str, Any]:
    """Record only compliance facts and a digest, never the decision content."""

    if (
        not isinstance(decision, dict)
        or decision.get("outcome") not in {"allow", "deny"}
        or not isinstance(decision.get("rationale"), str)
        or not decision["rationale"].strip()
        or not isinstance(decision.get("risk_tags"), list)
    ):
        raise QualificationError("structured_response_invalid")
    canonical = json.dumps(
        decision, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return {
        "schema_name": "rondo_static_approval_v1",
        "valid": True,
        "outcome_in_enum": True,
        "rationale_non_empty": True,
        "risk_tag_count": len(decision["risk_tags"]),
        "response_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def _verify_service_identity(config: RuntimeConfig, model: Path) -> None:
    LocalApprovalClient(config).verify_service_identity(
        model, expected_build_info=model_backed.CUDA_SERVICE_BUILD_INFO
    )


def _teardown(
    config: RuntimeConfig,
    process: subprocess.Popen[Any] | None,
    identity: Any,
    settings: LocalApprovalSettings,
    private_root: Path,
    identity_clearer: Callable[[RuntimeConfig, Any], None],
    log_path: Path,
) -> tuple[dict[str, bool], str | None]:
    """Stop only this task's own server, receipt and private artifacts."""

    stopped = True
    if process is not None:
        stopped = _stop_process(process)
    try:
        log_text: str | None = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        log_text = None
    receipt_cleared = True
    if identity is not None:
        try:
            identity_clearer(config, identity)
        except (ConfigError, OSError):
            receipt_cleared = False
        else:
            receipt_cleared = not (
                config.paths.common_root
                / _PRIVATE_ROOT
                / "launcher-identity.json"
            ).exists()
    released = _port_released(settings.host, settings.port)
    removed = _remove_private_directory(private_root)
    return (
        {
            "server_stopped": stopped,
            "port_released": released,
            "receipt_cleared": receipt_cleared,
            "private_artifacts_removed": removed,
        },
        log_text,
    )


def _stop_process(process: subprocess.Popen[Any]) -> bool:
    if process.poll() is not None:
        return True
    try:
        process.terminate()
    except OSError:
        pass
    try:
        process.wait(timeout=_STOP_TIMEOUT_SECONDS)
        return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        process.kill()
        process.wait(timeout=_STOP_TIMEOUT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return True


def _port_released(host: str, port: int) -> bool:
    deadline = time.monotonic() + _PORT_RELEASE_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(1.0)
            if probe.connect_ex((host, port)) != 0:
                return True
        time.sleep(0.25)
    return False


def _remove_private_directory(private_root: Path) -> bool:
    try:
        if private_root.is_symlink() or not private_root.is_dir():
            return False
        for child in private_root.iterdir():
            if child.is_symlink() or not child.is_file():
                return False
            child.unlink()
        private_root.rmdir()
    except OSError:
        return False
    return not private_root.exists()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the restricted first model-backed local approval qualification"
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument(
        "--evidence",
        required=True,
        help="repository-relative path of one archived E_final.json",
    )
    args = parser.parse_args(argv)
    try:
        config = load_runtime_config(RepoPaths.discover(args.repo))
        summary = run_qualification(config, evidence_relative_path=args.evidence)
    except QualificationError as error:
        report = {"status": "not_qualified", "blocker": error.code}
        if error.facts:
            report["facts"] = error.facts
        print(json.dumps(report, sort_keys=True))
        return error.exit_code
    except LocalApprovalError as error:
        print(
            json.dumps(
                {"status": "not_qualified", "blocker": type(error).__name__},
                sort_keys=True,
            )
        )
        return error.exit_code
    except ConfigError:
        print(json.dumps({"status": "not_qualified", "blocker": "configuration"}, sort_keys=True))
        return CONFIG_ERROR
    print(json.dumps(summary, sort_keys=True))
    return SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
