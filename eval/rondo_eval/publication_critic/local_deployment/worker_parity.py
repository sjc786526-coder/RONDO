"""Bounded Plan 071 direct-worker parity probe."""

from __future__ import annotations

import argparse
from io import BytesIO
import json
import math
import os
from pathlib import Path
import signal
import subprocess
from typing import Any, Mapping, Sequence

from ..contract import REPO_ROOT
from ..identity import canonical_json_bytes, sha256_bytes, sha256_file
from ..scoring import project_logit
from .comparability import OFFLINE_SCHEMA, freeze_sha256, validate_freeze
from .qualification import QualificationError, _write_json_exclusive
from .service_runner import _runtime_environment
from .worker import DEFAULT_MAX_FRAME_BYTES, read_frame, write_frame


RESULT_SCHEMA = "rondo-publication-critic-plan071-worker-parity-v1"


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise QualificationError(f"Plan 071 {label} is missing or unsafe")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"Plan 071 {label} is invalid") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"Plan 071 {label} is invalid")
    return value


def _worker_input(packet: Mapping[str, Any]) -> bytes:
    stream = BytesIO()
    for request in (
        {"op": "status"},
        {"op": "score", "request_id": "plan071-worker-parity", "packet": dict(packet)},
        {"op": "shutdown"},
    ):
        write_frame(stream, request, DEFAULT_MAX_FRAME_BYTES)
    return stream.getvalue()


def _worker_responses(body: bytes) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    stream = BytesIO(body)
    responses = [read_frame(stream, DEFAULT_MAX_FRAME_BYTES) for _ in range(3)]
    if any(not isinstance(item, dict) for item in responses) or stream.read(1):
        raise QualificationError("Plan 071 worker response framing is invalid")
    status, score, shutdown = responses
    assert isinstance(status, dict) and isinstance(score, dict) and isinstance(shutdown, dict)
    if (
        status.get("ok") is not True
        or status.get("state") != "ready"
        or score.get("ok") is not True
        or score.get("request_id") != "plan071-worker-parity"
        or shutdown != {"ok": True, "state": "stopped"}
    ):
        raise QualificationError("Plan 071 worker response is invalid")
    return status, score, shutdown


def run(args: argparse.Namespace) -> int:
    freeze = validate_freeze(_load_json(args.freeze, "freeze"))
    digest = freeze_sha256(freeze)
    descriptor = _load_json(args.descriptor, "worker descriptor")
    packet = _load_json(args.packet, "service packet")
    offline = _load_json(args.deployment_offline, "deployment offline output")
    object_id = args.object_id
    artifact = freeze["artifacts"][object_id]
    service_descriptor = descriptor.get("service_descriptor")
    if (
        descriptor.get("worker_protocol") != "rondo-publication-critic-worker-v1"
        or descriptor.get("object_id") != object_id
        or descriptor.get("deployment_artifact_sha256")
        != artifact["deployment_artifact_sha256"]
        or descriptor.get("qualification_freeze_sha256") != digest
        or not isinstance(service_descriptor, dict)
        or sha256_bytes(canonical_json_bytes(service_descriptor))
        != artifact["service_descriptor_sha256"]
        or sha256_file(args.snapshot / "model.safetensors")
        != artifact["deployment_artifact_sha256"]
        or sha256_file(args.packet) != freeze["service_parity_input"]["packet_sha256"]
        or sha256_file(args.python) != freeze["runtime"]["programs"]["python_sha256"]
    ):
        raise QualificationError("Plan 071 worker parity identity is invalid")
    if (
        offline.get("schema") != OFFLINE_SCHEMA
        or offline.get("mode") != freeze["mode"]
        or offline.get("run_id") != freeze["run_id"]
        or offline.get("qualification_freeze_sha256") != digest
        or offline.get("execution_role") != "deployment"
        or offline.get("object_id") != object_id
        or offline.get("deployment_artifact_sha256")
        != artifact["deployment_artifact_sha256"]
        or offline.get("snapshot_model_sha256") != artifact["deployment_artifact_sha256"]
        or offline.get("cohort_sample_ids_sha256")
        != sha256_bytes(canonical_json_bytes(list(freeze["cohort"]["sample_ids"])))
        or offline.get("runtime")
        != {
            "device": freeze["runtime"]["device"],
            "dtype": freeze["runtime"]["dtype"],
            "cpu_threads": freeze["runtime"]["cpu_threads"],
        }
    ):
        raise QualificationError("Plan 071 deployment offline identity is invalid")
    sample_id = freeze["service_parity_input"]["sample_id"]
    rows = [row for row in offline.get("rows", []) if row.get("sample_id") == sample_id]
    if len(rows) != 1:
        raise QualificationError("Plan 071 deployment parity row is missing")
    offline_row = rows[0]
    runtime = freeze["runtime"]
    command = [
        str(args.python),
        "-u",
        "-m",
        "rondo_eval.publication_critic.local_deployment.worker",
        "--snapshot",
        str(args.snapshot),
        "--descriptor",
        str(args.descriptor),
        "--device",
        runtime["device"],
        "--dtype",
        runtime["dtype"],
        "--cpu-threads",
        str(runtime["cpu_threads"]),
        "--repo-root",
        str(args.repo_root),
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_runtime_environment(args.repo_root, runtime["cpu_threads"]),
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(
            input=_worker_input(packet),
            timeout=runtime["service_limits"]["process_timeout_ms"] / 1000.0,
        )
    except subprocess.TimeoutExpired as exc:
        os.killpg(process.pid, signal.SIGKILL)
        process.communicate()
        raise QualificationError("Plan 071 worker parity timed out") from exc
    if process.returncode != 0 or stderr:
        raise QualificationError("Plan 071 worker parity process failed")
    status, score, _shutdown = _worker_responses(stdout)
    for name in ("raw_logit", "projected_score", "model_elapsed_ms"):
        if not isinstance(score.get(name), (int, float)) or not math.isfinite(
            float(score[name])
        ):
            raise QualificationError("Plan 071 worker parity score is invalid")
    raw_logit = float(score["raw_logit"])
    projected_score = float(score["projected_score"])
    response_projection_drift = abs(project_logit(raw_logit) - projected_score)
    if response_projection_drift > 1e-12:
        raise QualificationError("Plan 071 worker response projection drifted")
    threshold = float(freeze["threshold"]["projected_score"])
    result = {
        "schema": RESULT_SCHEMA,
        "mode": freeze["mode"],
        "run_id": freeze["run_id"],
        "qualification_freeze_sha256": digest,
        "object_id": object_id,
        "deployment_artifact_sha256": artifact["deployment_artifact_sha256"],
        "deployment_offline_sha256": sha256_file(args.deployment_offline),
        "packet_sha256": sha256_file(args.packet),
        "sample_id": sample_id,
        "raw_logit_absolute_difference": abs(
            float(offline_row["raw_logit"]) - raw_logit
        ),
        "projected_score_absolute_difference": abs(
            float(offline_row["projected_score"]) - projected_score
        ),
        "verdict_mismatch": (float(offline_row["projected_score"]) >= threshold)
        != (projected_score >= threshold),
        "token_count_matches": offline_row["token_count"] == score.get("token_count"),
        "dropped_oldest_publications_matches": offline_row[
            "dropped_oldest_publications"
        ]
        == score.get("dropped_oldest_publications"),
        "within_response_projection_absolute_difference": response_projection_drift,
        "worker_load_seconds": status.get("load_seconds"),
        "worker_resources": status.get("resources"),
        "worker_exit_code": process.returncode,
        "worker_reaped": process.poll() is not None,
        "stderr_bytes": len(stderr),
    }
    _write_json_exclusive(args.output, result)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Plan 071 direct worker parity")
    parser.add_argument("--object-id", choices=("base", "c1", "c3"), required=True)
    parser.add_argument("--freeze", type=Path, required=True)
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--descriptor", type=Path, required=True)
    parser.add_argument("--packet", type=Path, required=True)
    parser.add_argument("--deployment-offline", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
