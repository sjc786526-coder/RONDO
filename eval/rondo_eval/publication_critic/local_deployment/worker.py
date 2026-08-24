"""Private persistent Plan 068 inference worker with bounded framed JSON IPC."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import struct
import sys
from typing import Any, BinaryIO, Mapping

from ..backend import body_free_exception
from ..contract import REPO_ROOT
from ..identity import sha256_file
from .inference import InferenceError, PublicationCriticInference


WORKER_PROTOCOL = "rondo-publication-critic-worker-v1"
DEFAULT_MAX_FRAME_BYTES = 1024 * 1024
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


class WorkerError(RuntimeError):
    """A fixed, body-free worker protocol or lifecycle failure."""


def _require_exact_keys(value: Mapping[str, Any], expected: set[str]) -> None:
    if set(value) != expected:
        raise WorkerError("worker request fields are invalid")


def _read_exact(stream: BinaryIO, length: int, label: str) -> bytes:
    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            raise WorkerError(f"worker request frame {label} is incomplete")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_frame(stream: BinaryIO, max_frame_bytes: int) -> dict[str, Any] | None:
    header = stream.read(4)
    if header == b"":
        return None
    if len(header) != 4:
        header += _read_exact(stream, 4 - len(header), "header")
    (length,) = struct.unpack(">I", header)
    if length == 0 or length > max_frame_bytes:
        raise WorkerError("worker request frame length is invalid")
    body = _read_exact(stream, length, "body")
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerError("worker request frame is not strict JSON") from exc
    if not isinstance(value, dict):
        raise WorkerError("worker request frame must be an object")
    return value


def write_frame(stream: BinaryIO, value: Mapping[str, Any], max_frame_bytes: int) -> None:
    body = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if not body or len(body) > max_frame_bytes:
        raise WorkerError("worker response frame length is invalid")
    stream.write(struct.pack(">I", len(body)))
    stream.write(body)
    stream.flush()


def _body_free_failure(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, WorkerError):
        failure = {"failure_kind": "WorkerError", "message": str(exc)}
    elif isinstance(exc, InferenceError):
        failure = {"failure_kind": "InferenceError", "message": str(exc)}
    else:
        failure = body_free_exception(exc)
    return {"ok": False, "failure": failure}


class WorkerSession:
    def __init__(
        self,
        inference: PublicationCriticInference,
        *,
        descriptor: Mapping[str, Any],
    ) -> None:
        self.inference = inference
        self.descriptor = dict(descriptor)

    def handle(self, request: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        op = request.get("op")
        if op == "descriptor":
            _require_exact_keys(request, {"op"})
            return {"ok": True, "descriptor": self.descriptor}, False
        if op == "status":
            _require_exact_keys(request, {"op"})
            return {
                "ok": True,
                "state": "ready",
                "load_seconds": self.inference.load_seconds,
                "resources": self.inference.resource_snapshot(),
            }, False
        if op == "score":
            _require_exact_keys(request, {"op", "request_id", "packet"})
            request_id = request["request_id"]
            if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
                raise WorkerError("worker request identity is invalid")
            packet = request["packet"]
            if not isinstance(packet, dict):
                raise WorkerError("worker packet must be an object")
            result = self.inference.score_packet(packet)
            return {
                "ok": True,
                "request_id": request_id,
                "raw_logit": result.raw_logit,
                "projected_score": result.projected_score,
                "token_count": result.token_count,
                "dropped_oldest_publications": result.dropped_oldest_publications,
                "model_elapsed_ms": result.model_elapsed_ms,
            }, False
        if op == "shutdown":
            _require_exact_keys(request, {"op"})
            return {"ok": True, "state": "stopped"}, True
        raise WorkerError("worker operation is invalid")


def serve(
    session: WorkerSession,
    input_stream: BinaryIO,
    output_stream: BinaryIO,
    *,
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES,
) -> None:
    if max_frame_bytes < 8192 or max_frame_bytes > 8 * 1024 * 1024:
        raise WorkerError("worker frame cap is invalid")
    while True:
        request = read_frame(input_stream, max_frame_bytes)
        if request is None:
            return
        try:
            response, should_stop = session.handle(request)
        except BaseException as exc:
            response, should_stop = _body_free_failure(exc), False
        write_frame(output_stream, response, max_frame_bytes)
        if should_stop:
            return


def _load_descriptor(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise WorkerError("worker descriptor is missing or unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise WorkerError("worker descriptor is invalid") from exc
    if not isinstance(value, dict) or set(value) != {
        "worker_protocol",
        "object_id",
        "deployment_artifact_sha256",
        "qualification_freeze_sha256",
        "service_descriptor",
    }:
        raise WorkerError("worker descriptor identity is invalid")
    if (
        value["worker_protocol"] != WORKER_PROTOCOL
        or value["object_id"] not in {"base", "c1", "c2", "c3"}
        or not isinstance(value["deployment_artifact_sha256"], str)
        or _SHA256.fullmatch(value["deployment_artifact_sha256"]) is None
        or not isinstance(value["qualification_freeze_sha256"], str)
        or _SHA256.fullmatch(value["qualification_freeze_sha256"]) is None
        or not isinstance(value["service_descriptor"], dict)
    ):
        raise WorkerError("worker descriptor identity is invalid")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one bounded Publication Critic worker")
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--descriptor", type=Path, required=True)
    parser.add_argument("--device", choices=("cpu", "cuda"), required=True)
    parser.add_argument("--dtype", choices=("float32", "bfloat16"), required=True)
    parser.add_argument("--cpu-threads", type=int, required=True)
    parser.add_argument("--max-frame-bytes", type=int, default=DEFAULT_MAX_FRAME_BYTES)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    diagnostic_fd: int | None = None
    try:
        if args.cpu_threads <= 0:
            raise WorkerError("worker CPU thread count is invalid")
        descriptor = _load_descriptor(args.descriptor)
        expected_hash = descriptor.get("deployment_artifact_sha256")
        weight_path = args.snapshot / "model.safetensors"
        if not isinstance(expected_hash, str) or sha256_file(weight_path) != expected_hash:
            raise WorkerError("worker deployment artifact identity is invalid")
        inference = PublicationCriticInference(
            args.snapshot,
            repo_root=args.repo_root,
            device=args.device,
            dtype=args.dtype,
            cpu_threads=args.cpu_threads,
        )
        ipc_output_fd = os.dup(sys.stdout.fileno())
        diagnostic_fd = os.dup(sys.stderr.fileno())
        null_fd = os.open(os.devnull, os.O_WRONLY)
        os.dup2(null_fd, sys.stdout.fileno())
        os.dup2(null_fd, sys.stderr.fileno())
        os.close(null_fd)
        inference.load()
        with os.fdopen(ipc_output_fd, "wb", buffering=0) as ipc_output:
            serve(
                WorkerSession(inference, descriptor=descriptor),
                sys.stdin.buffer,
                ipc_output,
                max_frame_bytes=args.max_frame_bytes,
            )
        return 0
    except BaseException:
        os.write(
            diagnostic_fd if diagnostic_fd is not None else 2,
            b"publication critic worker failed\n",
        )
        return 1
    finally:
        if diagnostic_fd is not None:
            os.close(diagnostic_fd)


if __name__ == "__main__":
    raise SystemExit(main())
