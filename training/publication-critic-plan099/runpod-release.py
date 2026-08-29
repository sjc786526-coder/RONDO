#!/usr/bin/env python3
"""Reviewer-gated wrapper around the proven exact-Pod terminal helper."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping


SCHEMA = "rondo-publication-critic-plan099-pod-release-approval-v1"
THREAD_ID = "01a04c14-30e5-7212-8e6e-597ae12e5baa"
PHRASE = "确认不再需要 Pod，批准立即释放"


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approval-receipt", type=Path, required=True)
    parser.add_argument("--terminal-helper", type=Path, required=True)
    parser.add_argument("--pod-id", required=True)
    parser.add_argument("--pod-name", required=True)
    parser.add_argument("--captured-at", required=True)
    parser.add_argument("--task-started-at", required=True)
    parser.add_argument("--runpodctl", default="runpodctl")
    args = parser.parse_args()
    try:
        value = json.loads(args.approval_receipt.read_text(encoding="utf-8"))
        if not isinstance(value, Mapping):
            raise ValueError("release_approval_invalid")
        fields = {
            "schema",
            "reviewer_thread_id",
            "approval_phrase",
            "pod_id",
            "pod_name",
            "approved_at",
            "content_sha256",
        }
        core = {key: item for key, item in value.items() if key != "content_sha256"}
        if (
            set(value) != fields
            or value.get("schema") != SCHEMA
            or value.get("reviewer_thread_id") != THREAD_ID
            or value.get("approval_phrase") != PHRASE
            or value.get("pod_id") != args.pod_id
            or value.get("pod_name") != args.pod_name
            or not args.pod_name.startswith("rondo-plan099-")
            or value.get("content_sha256")
            != hashlib.sha256(canonical(core)).hexdigest()
        ):
            raise ValueError("release_approval_invalid")
        completed = subprocess.run(
            [
                sys.executable,
                str(args.terminal_helper),
                "--runpodctl",
                args.runpodctl,
                "--pod-id",
                args.pod_id,
                "--pod-name",
                args.pod_name,
                "--task-pod-name-prefix",
                "rondo-plan099-",
                "--captured-at",
                args.captured_at,
                "--task-started-at",
                args.task_started_at,
                "--timeout-seconds",
                "360",
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=420,
        )
        result = json.loads(completed.stdout)
        if (
            result.get("pod_count") != 0
            or result.get("compute_rate_usd_per_hour") != 0.0
        ):
            raise ValueError("release_terminal_state_invalid")
        print(json.dumps(result, sort_keys=True))
        return 0
    except (OSError, ValueError, json.JSONDecodeError, subprocess.SubprocessError):
        print(
            json.dumps({"status": "failed", "code": "plan099_release_failed"}),
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
