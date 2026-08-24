"""Bounded Plan 068 launcher for the real Rust service and typed probe."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import selectors
import signal
import subprocess
import threading
import time
from typing import Any, BinaryIO, Mapping, Sequence

from ..identity import canonical_json_bytes, sha256_bytes, sha256_file
from .qualification import QualificationError, freeze_sha256, validate_freeze


RESULT_SCHEMA = "rondo-publication-critic-plan068-service-run-v2"
_DESCRIPTOR_KEYS = {
    "worker_protocol",
    "object_id",
    "deployment_artifact_sha256",
    "qualification_freeze_sha256",
    "service_descriptor",
}
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_PROBE_FAILURE = re.compile(r"publication_critic_probe_failed code=([a-z0-9_]+)\n?\Z")
_TYPED_PROBE_FAILURES = {
    "backend",
    "call_timeout",
    "cancelled",
    "cancellation_did_not_win",
    "connect",
    "disconnected",
    "identity_mismatch",
    "invalid_configuration",
    "invalid_descriptor",
    "invalid_identity",
    "invalid_packet",
    "invalid_resource_configuration",
    "invalid_score",
    "invalid_scoring_configuration",
    "io_timeout",
    "malformed_response",
    "not_ready",
    "queue_full",
    "request_rejected",
    "request_too_large",
    "response_too_large",
    "shutdown_timeout",
    "shutting_down",
    "startup_timeout",
    "unexpected_exit",
    "unsupported_protocol",
}
_MAX_JSON_BYTES = 1024 * 1024
_MAX_PROBE_BYTES = 16 * 1024
_INHERITED_RUNTIME_ENVIRONMENT = {
    "PATH",
    "LD_LIBRARY_PATH",
    "CUDA_HOME",
    "CUDA_PATH",
    "CUDA_VISIBLE_DEVICES",
    "NVIDIA_VISIBLE_DEVICES",
    "NVIDIA_DRIVER_CAPABILITIES",
    "TMPDIR",
    "RONDO_WATCHDOG_WRAPPER_PID",
    "RONDO_WATCHDOG_WRAPPER_START_TICKS",
    "RONDO_WATCHDOG_HEARTBEAT_PATH",
    "RONDO_WATCHDOG_SCRIPT_PATH",
}


class ServiceRunnerError(RuntimeError):
    """A fixed, body-free launcher failure."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class ExclusiveOutput:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.parent.is_symlink() or not path.parent.is_dir() or path.is_symlink():
            raise ServiceRunnerError("output_path_unsafe")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            self._descriptor = os.open(path, flags, 0o600)
        except OSError as exc:
            raise ServiceRunnerError("output_not_exclusive") from exc

    def write(self, value: Mapping[str, Any]) -> None:
        body = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8") + b"\n"
        try:
            with os.fdopen(self._descriptor, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            self._descriptor = -1

    def close(self) -> None:
        if self._descriptor >= 0:
            os.close(self._descriptor)
            self._descriptor = -1


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ServiceRunnerError(f"{label}_missing") from exc
    if (
        path.is_symlink()
        or not path.is_file()
        or metadata.st_size <= 0
        or metadata.st_size > _MAX_JSON_BYTES
    ):
        raise ServiceRunnerError(f"{label}_unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ServiceRunnerError(f"{label}_invalid") from exc
    if not isinstance(value, dict):
        raise ServiceRunnerError(f"{label}_invalid")
    return value


def _validate_descriptor(value: Mapping[str, Any]) -> dict[str, Any]:
    if (
        set(value) != _DESCRIPTOR_KEYS
        or value["worker_protocol"] != "rondo-publication-critic-worker-v1"
        or value["object_id"] not in {"base", "c1", "c2", "c3"}
        or not isinstance(value["deployment_artifact_sha256"], str)
        or _SHA256.fullmatch(value["deployment_artifact_sha256"]) is None
        or not isinstance(value["qualification_freeze_sha256"], str)
        or _SHA256.fullmatch(value["qualification_freeze_sha256"]) is None
        or not isinstance(value["service_descriptor"], dict)
    ):
        raise ServiceRunnerError("descriptor_identity_invalid")
    return dict(value)


def _announcement_matches(
    expected: Mapping[str, Any],
    announced: Any,
) -> tuple[bool, bool]:
    if announced == expected:
        return True, False
    if not isinstance(announced, dict):
        return False, False
    try:
        expected_threshold = expected["identity"]["scoring"]["threshold"]
        announced_threshold = announced["identity"]["scoring"]["threshold"]
    except (KeyError, TypeError):
        return False, False
    if (
        type(expected_threshold) is not float
        or type(announced_threshold) is not float
        or not math.isfinite(expected_threshold)
        or not math.isfinite(announced_threshold)
        or abs(expected_threshold - announced_threshold) > math.ulp(expected_threshold)
    ):
        return False, False
    normalized = copy.deepcopy(announced)
    normalized["identity"]["scoring"]["threshold"] = expected_threshold
    matches = normalized == expected
    return matches, matches


def _bind_frozen_runtime(
    args: argparse.Namespace,
    descriptor: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        freeze = validate_freeze(_load_json(args.freeze, "freeze"))
    except (QualificationError, ServiceRunnerError):
        raise ServiceRunnerError("freeze_identity_invalid") from None
    digest = freeze_sha256(freeze)
    object_id = descriptor["object_id"]
    service_descriptor = descriptor["service_descriptor"]
    if (
        freeze["mode"] != args.mode
        or descriptor["qualification_freeze_sha256"] != digest
        or descriptor["deployment_artifact_sha256"]
        != freeze["artifacts"][object_id]["deployment_artifact_sha256"]
        or sha256_bytes(canonical_json_bytes(service_descriptor))
        != freeze["artifacts"][object_id]["service_descriptor_sha256"]
        or set(service_descriptor) != {"identity", "limits"}
        or not isinstance(service_descriptor["limits"], dict)
    ):
        raise ServiceRunnerError("freeze_descriptor_mismatch")
    runtime = freeze["runtime"]
    frozen_programs = runtime["programs"]
    if (
        sha256_file(args.service) != frozen_programs["service_sha256"]
        or sha256_file(args.probe) != frozen_programs["probe_sha256"]
        or sha256_file(args.python) != frozen_programs["python_sha256"]
    ):
        raise ServiceRunnerError("freeze_programs_mismatch")
    frozen_limits = runtime["service_limits"]
    descriptor_limits = service_descriptor["limits"]
    descriptor_limit_names = {
        "request_bytes",
        "response_bytes",
        "max_concurrency",
        "queue_capacity",
        "job_timeout_ms",
        "io_timeout_ms",
    }
    if set(descriptor_limits) != descriptor_limit_names or any(
        descriptor_limits[name] != frozen_limits[name]
        for name in descriptor_limit_names
    ):
        raise ServiceRunnerError("freeze_service_limits_mismatch")
    argument_names = {
        "worker_startup_timeout_ms",
        "worker_io_timeout_ms",
        "worker_shutdown_timeout_ms",
        "graceful_shutdown_ms",
        "force_shutdown_ms",
        "call_timeout_ms",
        "startup_timeout_ms",
        "process_timeout_ms",
    }
    if (
        args.device != runtime["device"]
        or args.dtype != runtime["dtype"]
        or args.cpu_threads != runtime["cpu_threads"]
        or any(getattr(args, name) != frozen_limits[name] for name in argument_names)
    ):
        raise ServiceRunnerError("freeze_runtime_arguments_mismatch")
    representative = object_id == freeze["representative_lifecycle_object"]
    expected_cancel = frozen_limits["representative_cancel_after_ms"]
    if args.mode == "formal" and (
        (representative and args.cancel_after_ms != expected_cancel)
        or (not representative and args.cancel_after_ms is not None)
    ):
        raise ServiceRunnerError("freeze_cancel_scenario_mismatch")
    return (
        {
            "device": args.device,
            "dtype": args.dtype,
            "cpu_threads": args.cpu_threads,
            "deployment_format": runtime["deployment_format"],
            "programs": dict(frozen_programs),
            "service_limits": dict(frozen_limits),
        },
        freeze,
    )


def _runtime_environment(repo_root: Path, cpu_threads: int) -> dict[str, str]:
    environment = {
        name: value
        for name in _INHERITED_RUNTIME_ENVIRONMENT
        if (value := os.environ.get(name)) is not None
    }
    environment.update(
        {
            "PYTHONPATH": str(repo_root / "eval"),
            "PYTHONNOUSERSITE": "1",
            "PYTHONUNBUFFERED": "1",
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
            "HF_HUB_DISABLE_TELEMETRY": "1",
            "DO_NOT_TRACK": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "OMP_NUM_THREADS": str(cpu_threads),
            "MKL_NUM_THREADS": str(cpu_threads),
            "OPENBLAS_NUM_THREADS": str(cpu_threads),
        }
    )
    return environment


def _require_path(
    path: Path,
    label: str,
    *,
    directory: bool = False,
    allow_symlink: bool = False,
) -> None:
    if (path.is_symlink() and not allow_symlink) or (
        not path.is_dir() if directory else not path.is_file()
    ):
        raise ServiceRunnerError(f"{label}_unsafe")


def _positive(value: int, label: str) -> int:
    if value <= 0 or value > 300_000:
        raise ServiceRunnerError(f"{label}_invalid")
    return value


def _read_announcement(stream: BinaryIO, timeout_ms: int) -> dict[str, Any]:
    selector = selectors.DefaultSelector()
    selector.register(stream, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout_ms / 1000.0
    body = bytearray()
    try:
        while b"\n" not in body:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise ServiceRunnerError("announcement_timeout")
            chunk = os.read(stream.fileno(), min(4096, _MAX_JSON_BYTES + 1 - len(body)))
            if not chunk:
                raise ServiceRunnerError("service_exited_before_announcement")
            body.extend(chunk)
            if len(body) > _MAX_JSON_BYTES:
                raise ServiceRunnerError("announcement_too_large")
    finally:
        selector.close()
    line, remainder = bytes(body).split(b"\n", 1)
    if remainder.strip():
        raise ServiceRunnerError("announcement_stdout_not_single_line")
    try:
        value = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ServiceRunnerError("announcement_invalid") from exc
    if not isinstance(value, dict) or set(value) != {"protocol", "endpoint", "descriptor"}:
        raise ServiceRunnerError("announcement_invalid")
    return value


def _endpoint(value: Any) -> str:
    if not isinstance(value, str) or not value.startswith("127.0.0.1:"):
        raise ServiceRunnerError("announcement_endpoint_invalid")
    host, separator, port_text = value.rpartition(":")
    try:
        address = ipaddress.ip_address(host)
        port = int(port_text)
    except ValueError as exc:
        raise ServiceRunnerError("announcement_endpoint_invalid") from exc
    if not separator or not address.is_loopback or not 0 < port <= 65535:
        raise ServiceRunnerError("announcement_endpoint_invalid")
    return value


def _terminate_group(process: subprocess.Popen[bytes], timeout_ms: int) -> dict[str, Any]:
    leader_already_exited = process.poll() is not None
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    if leader_already_exited:
        exit_code = process.returncode
    else:
        try:
            exit_code = process.wait(timeout=timeout_ms / 1000.0)
        except subprocess.TimeoutExpired:
            _kill_remaining_group(process.pid)
            exit_code = process.wait()
            return {"method": "kill_group", "exit_code": exit_code, "reaped": True}
    # The service may already have exited while a worker remained in its task-only
    # process group. Signal that exact group even in this case; never enumerate or
    # touch unrelated processes.
    _kill_remaining_group(process.pid)
    return {
        "method": "terminate_group_after_exit" if leader_already_exited else "terminate_group",
        "exit_code": exit_code,
        "reaped": True,
    }


def _kill_remaining_group(process_group: int) -> bool:
    try:
        os.killpg(process_group, signal.SIGKILL)
        return True
    except ProcessLookupError:
        return False


def _discard(stream: BinaryIO) -> None:
    try:
        while stream.read(8192):
            pass
    except OSError:
        pass


def _probe_failure(stderr: bytes) -> str:
    if len(stderr) > _MAX_PROBE_BYTES:
        return "invalid_probe_failure"
    try:
        text = stderr.decode("utf-8")
    except UnicodeDecodeError:
        return "invalid_probe_failure"
    match = _PROBE_FAILURE.fullmatch(text)
    if match is None or match.group(1) not in _TYPED_PROBE_FAILURES:
        return "invalid_probe_failure"
    return match.group(1)


def _run_probe(
    args: argparse.Namespace,
    endpoint: str,
    operation: str,
) -> dict[str, Any]:
    command = [
        str(args.probe),
        "--endpoint",
        endpoint,
        "--expected-descriptor",
        str(args.descriptor),
        "--call-timeout-ms",
        str(args.call_timeout_ms),
        "--startup-timeout-ms",
        str(args.startup_timeout_ms),
    ]
    if operation in {"review", "cancel"}:
        command.extend([operation, "--packet", str(args.packet)])
        if operation == "cancel":
            command.extend(["--cancel-after-ms", str(args.cancel_after_ms)])
    else:
        command.append(operation)
    started = time.perf_counter()
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_runtime_environment(args.repo_root, args.cpu_threads),
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=args.process_timeout_ms / 1000.0)
    except subprocess.TimeoutExpired:
        cleanup = _terminate_group(process, args.process_timeout_ms)
        return {
            "operation": operation,
            "outcome": "failure",
            "failure_code": "probe_timeout",
            "latency_ms": (time.perf_counter() - started) * 1000.0,
            "probe_cleanup": cleanup,
        }
    latency_ms = (time.perf_counter() - started) * 1000.0
    if process.returncode != 0:
        return {
            "operation": operation,
            "outcome": "failure",
            "failure_code": _probe_failure(stderr),
            "latency_ms": latency_ms,
        }
    if stderr or len(stdout) > _MAX_PROBE_BYTES:
        return {
            "operation": operation,
            "outcome": "failure",
            "failure_code": "invalid_probe_output",
            "latency_ms": latency_ms,
        }
    try:
        value = json.loads(stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        value = None
    expected = {
        "ready": "ready",
        "review": {"pass", "rewrite"},
        "cancel": "cancelled",
        "shutdown": "accepted",
    }[operation]
    valid = (
        isinstance(value, dict)
        and set(value) == {"operation", "result"}
        and value["operation"] == operation
        and (
            value["result"] in expected
            if isinstance(expected, set)
            else value["result"] == expected
        )
    )
    if not valid:
        return {
            "operation": operation,
            "outcome": "failure",
            "failure_code": "invalid_probe_output",
            "latency_ms": latency_ms,
        }
    return {
        "operation": operation,
        "outcome": "success",
        "result": value["result"],
        "latency_ms": latency_ms,
    }


def _service_command(args: argparse.Namespace) -> list[str]:
    worker_arguments = [
        "-u",
        "-m",
        "rondo_eval.publication_critic.local_deployment.worker",
        "--snapshot",
        str(args.snapshot),
        "--descriptor",
        str(args.descriptor),
        "--device",
        args.device,
        "--dtype",
        args.dtype,
        "--cpu-threads",
        str(args.cpu_threads),
        "--repo-root",
        str(args.repo_root),
    ]
    command = [
        str(args.service),
        "--descriptor",
        str(args.descriptor),
        "--worker-program",
        str(args.python),
    ]
    command.extend(f"--worker-arg={argument}" for argument in worker_arguments)
    command.extend(
        [
            "--worker-startup-timeout-ms",
            str(args.worker_startup_timeout_ms),
            "--worker-io-timeout-ms",
            str(args.worker_io_timeout_ms),
            "--worker-shutdown-timeout-ms",
            str(args.worker_shutdown_timeout_ms),
            "--graceful-shutdown-ms",
            str(args.graceful_shutdown_ms),
            "--force-shutdown-ms",
            str(args.force_shutdown_ms),
        ]
    )
    return command


def _run(args: argparse.Namespace, evidence: dict[str, Any]) -> str | None:
    for path, label in (
        (args.service, "service_program"),
        (args.probe, "probe_program"),
        (args.packet, "packet"),
        (args.freeze, "freeze"),
    ):
        _require_path(path, label)
    _require_path(args.python, "python_program", allow_symlink=True)
    _require_path(args.snapshot, "snapshot", directory=True)
    _require_path(args.repo_root, "repo_root", directory=True)
    descriptor = _validate_descriptor(_load_json(args.descriptor, "descriptor"))
    frozen_runtime, freeze = _bind_frozen_runtime(args, descriptor)
    _load_json(args.packet, "packet")
    packet_sha256 = sha256_file(args.packet)
    snapshot_model_sha256 = sha256_file(args.snapshot / "model.safetensors")
    if packet_sha256 != freeze["service_parity_input"]["packet_sha256"]:
        raise ServiceRunnerError("packet_identity_mismatch")
    if snapshot_model_sha256 != freeze["artifacts"][descriptor["object_id"]][
        "deployment_artifact_sha256"
    ]:
        raise ServiceRunnerError("snapshot_artifact_mismatch")
    evidence.update(
        {
            "run_id": freeze["run_id"],
            "object_id": descriptor["object_id"],
            "descriptor_sha256": sha256_file(args.descriptor),
            "service_descriptor_sha256": sha256_bytes(
                canonical_json_bytes(descriptor["service_descriptor"])
            ),
            "qualification_freeze_sha256": descriptor[
                "qualification_freeze_sha256"
            ],
            "snapshot_model_sha256": snapshot_model_sha256,
            "service_sample_id": freeze["service_parity_input"]["sample_id"],
            "packet_sha256": packet_sha256,
            "frozen_runtime": frozen_runtime,
        }
    )
    environment = _runtime_environment(args.repo_root, args.cpu_threads)
    service = subprocess.Popen(
        _service_command(args),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=environment,
        start_new_session=True,
    )
    if service.stdout is None:
        raise ServiceRunnerError("service_stdout_unavailable")
    endpoint: str | None = None
    shutdown_attempted = False
    run_failure: str | None = None
    drain_thread: threading.Thread | None = None
    try:
        announcement = _read_announcement(service.stdout, args.startup_timeout_ms)
        if announcement["protocol"] != "rondo_publication_critic_v1":
            raise ServiceRunnerError("announcement_protocol_mismatch")
        observed_endpoint = _endpoint(announcement["endpoint"])
        announcement_matches, threshold_normalized = _announcement_matches(
            descriptor["service_descriptor"],
            announcement["descriptor"],
        )
        if not announcement_matches:
            raise ServiceRunnerError("announcement_identity_mismatch")
        endpoint = observed_endpoint
        evidence["announcement"] = {
            "protocol": announcement["protocol"],
            "endpoint": endpoint,
            "descriptor_matches_trusted_input": True,
            "threshold_ulp_normalized": threshold_normalized,
        }
        drain_thread = threading.Thread(target=_discard, args=(service.stdout,), daemon=True)
        drain_thread.start()

        ready = _run_probe(args, endpoint, "ready")
        evidence["ready"] = ready
        if ready["outcome"] != "success":
            run_failure = "ready_probe_failed"
        else:
            warm = [_run_probe(args, endpoint, "review") for _ in range(3)]
            evidence["warm_reviews"] = warm
            stress: list[dict[str, Any]] = []
            for concurrency in (1, 2, 4, 8):
                started = time.perf_counter()
                with ThreadPoolExecutor(max_workers=concurrency) as executor:
                    calls = list(
                        executor.map(
                            lambda _index: _run_probe(args, endpoint, "review"),
                            range(concurrency),
                        )
                    )
                stress.append(
                    {
                        "concurrency": concurrency,
                        "wall_ms": (time.perf_counter() - started) * 1000.0,
                        "calls": calls,
                    }
                )
            evidence["stress"] = stress
            if args.cancel_after_ms is not None:
                evidence["cancel"] = _run_probe(args, endpoint, "cancel")
                if evidence["cancel"]["outcome"] == "success":
                    evidence["post_cancel_ready"] = _run_probe(args, endpoint, "ready")
                    evidence["post_cancel_review"] = _run_probe(args, endpoint, "review")
                else:
                    evidence["post_cancel_ready"] = {
                        "operation": "ready",
                        "outcome": "N/A",
                        "reason": "cancel_did_not_complete",
                    }
                    evidence["post_cancel_review"] = {
                        "operation": "review",
                        "outcome": "N/A",
                        "reason": "cancel_did_not_complete",
                    }
            else:
                evidence["cancel"] = {
                    "operation": "cancel",
                    "outcome": "N/A",
                    "reason": "not_representative_object",
                }
            review_records = warm + [call for scenario in stress for call in scenario["calls"]]
            all_call_records = review_records + [evidence["cancel"]]
            if args.cancel_after_ms is not None:
                all_call_records.extend(
                    [evidence["post_cancel_ready"], evidence["post_cancel_review"]]
                )
            protocol_failure_codes = {
                "invalid_probe_failure",
                "invalid_probe_output",
                "probe_timeout",
            }
            if any(
                record.get("failure_code") in protocol_failure_codes
                for record in all_call_records
            ):
                run_failure = "probe_protocol_failed"
            evidence["call_summary"] = {
                "warm_call_count": len(warm),
                "warm_success_count": sum(
                    record["outcome"] == "success" for record in warm
                ),
                "stress_call_count": len(review_records) - len(warm),
                "stress_success_count": sum(
                    record["outcome"] == "success"
                    for record in review_records[len(warm) :]
                ),
                "verdict_counts": {
                    verdict: sum(record.get("result") == verdict for record in review_records)
                    for verdict in ("pass", "rewrite")
                },
                "typed_failure_codes": sorted(
                    record["failure_code"]
                    for record in all_call_records
                    if record.get("failure_code") in _TYPED_PROBE_FAILURES
                ),
            }

        shutdown_attempted = True
        shutdown = _run_probe(args, endpoint, "shutdown")
        evidence["shutdown"] = shutdown
        if shutdown["outcome"] != "success":
            run_failure = run_failure or "shutdown_probe_failed"
        try:
            exit_code = service.wait(timeout=args.process_timeout_ms / 1000.0)
            evidence["service_exit"] = {
                "method": "graceful",
                "exit_code": exit_code,
                "reaped": True,
                "remaining_group_kill_signalled": _kill_remaining_group(service.pid),
            }
            if exit_code != 0:
                run_failure = run_failure or "service_exit_failed"
        except subprocess.TimeoutExpired:
            evidence["service_exit"] = _terminate_group(service, args.process_timeout_ms)
            run_failure = run_failure or "service_shutdown_timeout"
        return run_failure
    except ServiceRunnerError as exc:
        run_failure = exc.code
        return run_failure
    finally:
        if service.poll() is None:
            if endpoint is not None and not shutdown_attempted:
                shutdown_attempted = True
                evidence["shutdown"] = _run_probe(args, endpoint, "shutdown")
                try:
                    exit_code = service.wait(timeout=args.process_timeout_ms / 1000.0)
                    evidence["service_exit"] = {
                        "method": "graceful_after_failure",
                        "exit_code": exit_code,
                        "reaped": True,
                        "remaining_group_kill_signalled": _kill_remaining_group(
                            service.pid
                        ),
                    }
                except subprocess.TimeoutExpired:
                    evidence["service_exit"] = _terminate_group(
                        service, args.process_timeout_ms
                    )
            else:
                evidence["service_exit"] = _terminate_group(service, args.process_timeout_ms)
        if drain_thread is not None:
            drain_thread.join(timeout=args.process_timeout_ms / 1000.0)
        service.stdout.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run bounded real Publication Critic service qualification"
    )
    parser.add_argument("--mode", choices=("commissioning", "formal"), required=True)
    parser.add_argument("--service", type=Path, required=True)
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--descriptor", type=Path, required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--dtype", choices=("float32", "bfloat16"), required=True)
    parser.add_argument("--cpu-threads", type=int, required=True)
    parser.add_argument("--worker-startup-timeout-ms", type=int, required=True)
    parser.add_argument("--worker-io-timeout-ms", type=int, required=True)
    parser.add_argument("--worker-shutdown-timeout-ms", type=int, required=True)
    parser.add_argument("--graceful-shutdown-ms", type=int, required=True)
    parser.add_argument("--force-shutdown-ms", type=int, required=True)
    parser.add_argument("--call-timeout-ms", type=int, required=True)
    parser.add_argument("--startup-timeout-ms", type=int, required=True)
    parser.add_argument("--process-timeout-ms", type=int, required=True)
    parser.add_argument("--cancel-after-ms", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    output: ExclusiveOutput | None = None
    evidence: dict[str, Any] = {
        "schema": RESULT_SCHEMA,
        "mode": args.mode,
        "latency_scope": "typed_probe_process_e2e",
        "status": "FAILED",
        "failure_code": None,
    }
    failure_code: str | None = None
    try:
        for name in (
            "cpu_threads",
            "worker_startup_timeout_ms",
            "worker_io_timeout_ms",
            "worker_shutdown_timeout_ms",
            "graceful_shutdown_ms",
            "force_shutdown_ms",
            "call_timeout_ms",
            "startup_timeout_ms",
            "process_timeout_ms",
        ):
            _positive(getattr(args, name), name)
        if args.cancel_after_ms is not None:
            _positive(args.cancel_after_ms, "cancel_after_ms")
        output = ExclusiveOutput(args.output)
        failure_code = _run(args, evidence)
    except ServiceRunnerError as exc:
        failure_code = exc.code
    except (OSError, subprocess.SubprocessError):
        failure_code = "process_infrastructure_failure"
    except Exception:
        failure_code = "unexpected_runner_failure"
    finally:
        evidence["failure_code"] = failure_code
        evidence["status"] = "COMPLETE" if failure_code is None else "FAILED"
        if output is not None:
            output.write(evidence)
            output.close()
    if failure_code is not None:
        os.write(2, f"publication_critic_service_runner_failed code={failure_code}\n".encode())
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
