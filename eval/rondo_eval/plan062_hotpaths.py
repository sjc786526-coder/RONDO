"""Run and aggregate the body-free Plan 062 Divan microbenchmark."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import time
from typing import Any


SCHEMA_VERSION = 1
BENCHMARK_VERSION = "plan062-hotpaths-v1"
BENCHMARK_NAME = "plan062_hotpaths"
FORMAL_SAMPLE_COUNT = 20
FORMAL_SAMPLE_SIZE = 10
TOOL_SPEC_REPEATS = 16
UNIFIED_EXEC_MAX_BYTES = 1_048_576
EXPECTED_CASES = {
    "history_turns_8": ("history_orphan_normalization", {"turns": 8}),
    "history_turns_32": ("history_orphan_normalization", {"turns": 32}),
    "history_turns_128": ("history_orphan_normalization", {"turns": 128}),
    "tool_specs_8": (
        "model_visible_tool_specs",
        {"spec_count": 8, "repeats": TOOL_SPEC_REPEATS},
    ),
    "tool_specs_32": (
        "model_visible_tool_specs",
        {"spec_count": 32, "repeats": TOOL_SPEC_REPEATS},
    ),
    "tool_specs_64": (
        "model_visible_tool_specs",
        {"spec_count": 64, "repeats": TOOL_SPEC_REPEATS},
    ),
    "unified_exec_bytes_4096": (
        "unified_exec_snapshot",
        {"input_bytes": 4_096, "max_bytes": UNIFIED_EXEC_MAX_BYTES},
    ),
    "unified_exec_bytes_262144": (
        "unified_exec_snapshot",
        {"input_bytes": 262_144, "max_bytes": UNIFIED_EXEC_MAX_BYTES},
    ),
    "unified_exec_bytes_1048576": (
        "unified_exec_snapshot",
        {"input_bytes": 1_048_576, "max_bytes": UNIFIED_EXEC_MAX_BYTES},
    ),
}
HARNESS_PATHS = (
    "mydev/codex-rs/Cargo.lock",
    "mydev/codex-rs/core/Cargo.toml",
    "mydev/codex-rs/core/benches/plan062_hotpaths.rs",
    "mydev/codex-rs/core/src/test_support/plan062_hotpaths.rs",
    "eval/rondo_eval/plan062_hotpaths.py",
    "eval/tests/test_plan062_hotpaths.py",
    "mydev/justfile",
)
ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
TIME_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)\s*(ps|ns|us|µs|ms|s)$")
NUMBER_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)$")
BYTES_RE = re.compile(r"^([0-9]+(?:\.[0-9]+)?)\s*(B|KB|MB|GB|KiB|MiB|GiB)$")
TIME_TO_NS = {
    "ps": 0.001,
    "ns": 1.0,
    "us": 1_000.0,
    "µs": 1_000.0,
    "ms": 1_000_000.0,
    "s": 1_000_000_000.0,
}
BYTES_MULTIPLIER = {
    "B": 1.0,
    "KB": 1_000.0,
    "MB": 1_000_000.0,
    "GB": 1_000_000_000.0,
    "KiB": 1_024.0,
    "MiB": 1_048_576.0,
    "GiB": 1_073_741_824.0,
}


class Plan062BenchmarkError(RuntimeError):
    """Fail-closed error for the Plan 062 benchmark contract."""


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def harness_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in HARNESS_PATHS:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise Plan062BenchmarkError(
                f"missing regular benchmark harness file: {relative}"
            )
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _parse_time(value: str) -> float:
    match = TIME_RE.fullmatch(value.strip())
    if not match:
        raise Plan062BenchmarkError(f"unknown Divan time value: {value!r}")
    return float(match.group(1)) * TIME_TO_NS[match.group(2)]


def _parse_number(value: str) -> float:
    normalized = value.strip().replace(",", "")
    match = NUMBER_RE.fullmatch(normalized)
    if not match:
        raise Plan062BenchmarkError(f"unknown Divan numeric value: {value!r}")
    return float(match.group(1))


def _parse_bytes(value: str) -> float:
    match = BYTES_RE.fullmatch(value.strip())
    if not match:
        raise Plan062BenchmarkError(f"unknown Divan byte value: {value!r}")
    return float(match.group(1)) * BYTES_MULTIPLIER[match.group(2)]


def _tree_label(value: str) -> str:
    return value.strip().lstrip("│├└┌┬┤╰─ ").strip()


def parse_divan_output(output: str) -> dict[str, dict[str, float | int]]:
    """Parse the allowlisted Divan 0.1.21 table and reject partial results."""

    current_group: str | None = None
    current_case: str | None = None
    allocation_mode = False
    allocation_rows = 0
    parsed: dict[str, dict[str, float | int]] = {}

    for raw_line in output.splitlines():
        line = ANSI_RE.sub("", raw_line)
        for group in ("history_turns", "tool_specs", "unified_exec_bytes"):
            if group in line:
                current_group = group
                current_case = None
                allocation_mode = False
                allocation_rows = 0
                break

        if "│" not in line:
            continue
        columns = [column.strip() for column in line.split("│")]
        while len(columns) > 6 and not columns[0]:
            columns = columns[1:]
        if len(columns) < 6:
            continue
        label = _tree_label(columns[0])
        if label == "alloc:":
            if current_case is None:
                raise Plan062BenchmarkError(
                    "Divan allocation block has no benchmark case"
                )
            allocation_mode = True
            allocation_rows = 0
            continue

        case_match = re.search(r"(?:├─|╰─)\s*([0-9]+)\s+", columns[0])
        if current_group is not None and case_match:
            case_id = f"{current_group}_{case_match.group(1)}"
            if case_id not in EXPECTED_CASES:
                raise Plan062BenchmarkError(
                    f"unexpected Plan 062 benchmark case: {case_id}"
                )
            if case_id in parsed:
                raise Plan062BenchmarkError(
                    f"duplicate Plan 062 benchmark case: {case_id}"
                )
            parsed[case_id] = {
                "median_ns": _parse_time(columns[2]),
                "mean_ns": _parse_time(columns[3]),
                "samples": int(_parse_number(columns[4])),
                "iterations": int(_parse_number(columns[5])),
            }
            current_case = case_id
            allocation_mode = False
            allocation_rows = 0
            continue

        if allocation_mode and current_case is not None and "alloc:" not in label:
            if allocation_rows == 0:
                parsed[current_case]["alloc_count_median"] = _parse_number(columns[2])
            elif allocation_rows == 1:
                parsed[current_case]["alloc_bytes_median"] = _parse_bytes(columns[2])
                allocation_mode = False
            else:
                raise Plan062BenchmarkError("unexpected extra Divan allocation row")
            allocation_rows += 1

    missing = sorted(set(EXPECTED_CASES) - set(parsed))
    extra = sorted(set(parsed) - set(EXPECTED_CASES))
    if missing or extra:
        raise Plan062BenchmarkError(
            f"Divan case mismatch: missing={missing}, extra={extra}"
        )
    for case_id, metrics in parsed.items():
        required = {
            "median_ns",
            "mean_ns",
            "samples",
            "iterations",
            "alloc_count_median",
            "alloc_bytes_median",
        }
        absent = sorted(required - set(metrics))
        if absent:
            raise Plan062BenchmarkError(
                f"Divan metrics missing for {case_id}: {absent}"
            )
    return parsed


def _read_watchdog_summary(watchdog_root: Path) -> dict[str, str | int]:
    summaries = list(watchdog_root.glob("*/summary.env"))
    if len(summaries) != 1:
        raise Plan062BenchmarkError(
            f"expected exactly one watchdog summary, found {len(summaries)}"
        )
    values: dict[str, str] = {}
    for line in summaries[0].read_text("utf-8").splitlines():
        key, separator, value = line.partition("=")
        if not separator:
            raise Plan062BenchmarkError("malformed watchdog summary")
        values[key] = value
    if (
        values.get("wrapper_status") != "complete"
        or values.get("final_rc") != "0"
        or values.get("stop_reason") != "none"
        or values.get("cleanup_reason") != "none"
    ):
        raise Plan062BenchmarkError("watchdog did not report a clean completion")
    string_keys = (
        "wrapper_status",
        "stop_reason",
        "cleanup_reason",
        "memory_high",
        "memory_max",
        "swap_max",
    )
    integer_keys = (
        "final_rc",
        "project_before_bytes",
        "project_after_bytes",
        "project_peak_sampled_bytes",
        "target_after_bytes",
        "target_peak_sampled_bytes",
        "windows_c_available_before_bytes",
        "windows_c_available_after_bytes",
        "memory_peak_sampled_bytes",
        "memory_nonreclaimable_peak_sampled_bytes",
        "swap_peak_sampled_bytes",
        "cgroup_psi_full_avg10_peak_bp",
        "host_psi_full_avg10_peak_bp",
        "project_stop_bytes",
        "project_max_bytes",
    )
    projected: dict[str, str | int] = {}
    for key in string_keys:
        if key not in values:
            raise Plan062BenchmarkError(f"watchdog summary missing {key}")
        projected[key] = values[key]
    for key in integer_keys:
        try:
            projected[key] = int(values[key])
        except (KeyError, ValueError) as exc:
            raise Plan062BenchmarkError(f"watchdog summary has invalid {key}") from exc
    return projected


def _run_command(
    command: list[str], cwd: Path, output_path: Path, env: dict[str, str]
) -> tuple[int, float]:
    started = time.monotonic()
    with output_path.open("w", encoding="utf-8") as output_file:
        process = subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        for line in process.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            output_file.write(line)
        return process.wait(), time.monotonic() - started


def run_benchmark(phase: str, smoke: bool) -> Path:
    root = _repo_root()
    commit = _git(root, "rev-parse", "HEAD")
    dirty = bool(_git(root, "status", "--porcelain", "--untracked-files=normal"))
    if not smoke and dirty:
        raise Plan062BenchmarkError("formal benchmark requires a clean commit")
    timestamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_root = root / ".codex" / "plan062-hotpaths" / "raw" / phase / commit / timestamp
    run_root.mkdir(parents=True, exist_ok=False)
    watchdog_root = run_root / "watchdog"
    output_path = run_root / "output.txt"

    command = [
        str(root / "scripts" / "with-build-lock.sh"),
        "cargo",
        "bench",
        "-p",
        "codex-core",
        "--bench",
        BENCHMARK_NAME,
        "--",
        "--color",
        "never",
    ]
    if smoke:
        command.append("--test")
    else:
        command.extend(
            [
                "--timer",
                "os",
                "--threads",
                "1",
                "--sample-count",
                str(FORMAL_SAMPLE_COUNT),
                "--sample-size",
                str(FORMAL_SAMPLE_SIZE),
            ]
        )
    child_env = os.environ.copy()
    child_env["RONDO_BUILD_METRICS_DIR"] = str(watchdog_root)
    return_code, wall_seconds = _run_command(
        command,
        root / "mydev" / "codex-rs",
        output_path,
        child_env,
    )

    metadata: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "benchmark_version": BENCHMARK_VERSION,
        "benchmark_name": BENCHMARK_NAME,
        "phase": phase,
        "commit": commit,
        "dirty": dirty,
        "smoke": smoke,
        "started_at_utc": timestamp,
        "wall_time_seconds": round(wall_seconds, 6),
        "return_code": return_code,
        "harness_sha256": harness_sha256(root),
        "requested_sample_count": None if smoke else FORMAL_SAMPLE_COUNT,
        "requested_sample_size": None if smoke else FORMAL_SAMPLE_SIZE,
        "environment": {
            "os": platform.system(),
            "release": platform.release(),
            "arch": platform.machine(),
            "rustc": subprocess.run(
                ["rustc", "--version"], check=True, capture_output=True, text=True
            ).stdout.strip(),
            "cargo": subprocess.run(
                ["cargo", "--version"], check=True, capture_output=True, text=True
            ).stdout.strip(),
            "divan": "0.1.21",
            "profile": "bench",
            "timer": "os",
        },
        "workloads": {
            case_id: {"workload": workload, "parameters": parameters}
            for case_id, (workload, parameters) in EXPECTED_CASES.items()
        },
        "output_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
    }
    if return_code == 0:
        metadata["resources"] = _read_watchdog_summary(watchdog_root)
        if not smoke:
            metadata["cases"] = parse_divan_output(output_path.read_text("utf-8"))
    (run_root / "run.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    if return_code != 0:
        raise Plan062BenchmarkError(
            f"benchmark exited with status {return_code}; raw={run_root}"
        )
    print(run_root)
    return run_root


def _ratio_delta(candidate: float, baseline: float) -> float | None:
    if baseline == 0:
        return None
    return round((candidate - baseline) / baseline * 100.0, 6)


def aggregate(baseline_path: Path, candidate_path: Path, output_path: Path) -> None:
    baseline = json.loads((baseline_path / "run.json").read_text("utf-8"))
    candidate = json.loads((candidate_path / "run.json").read_text("utf-8"))
    for phase, run in (("baseline", baseline), ("candidate", candidate)):
        if (
            run.get("phase") != phase
            or run.get("dirty") is not False
            or run.get("smoke") is not False
        ):
            raise Plan062BenchmarkError(f"invalid formal {phase} run identity")
        if run.get("return_code") != 0:
            raise Plan062BenchmarkError(f"formal {phase} run did not complete")
    if baseline["harness_sha256"] != candidate["harness_sha256"]:
        raise Plan062BenchmarkError("baseline and candidate benchmark harnesses differ")
    if baseline["environment"] != candidate["environment"]:
        raise Plan062BenchmarkError(
            "baseline and candidate benchmark environments differ"
        )
    if baseline["workloads"] != candidate["workloads"]:
        raise Plan062BenchmarkError("baseline and candidate workloads differ")

    cases = []
    for case_id, (workload, parameters) in EXPECTED_CASES.items():
        before = baseline["cases"][case_id]
        after = candidate["cases"][case_id]
        delta = {
            "median_ns_percent": _ratio_delta(after["median_ns"], before["median_ns"]),
            "mean_ns_percent": _ratio_delta(after["mean_ns"], before["mean_ns"]),
            "alloc_count_absolute": after["alloc_count_median"]
            - before["alloc_count_median"],
            "alloc_count_percent": _ratio_delta(
                after["alloc_count_median"], before["alloc_count_median"]
            ),
            "alloc_bytes_absolute": after["alloc_bytes_median"]
            - before["alloc_bytes_median"],
            "alloc_bytes_percent": _ratio_delta(
                after["alloc_bytes_median"], before["alloc_bytes_median"]
            ),
        }
        cases.append(
            {
                "case_id": case_id,
                "workload": workload,
                "parameters": parameters,
                "baseline": before,
                "candidate": after,
                "delta": delta,
            }
        )

    result = {
        "schema_version": SCHEMA_VERSION,
        "kind": "rondo_direction1_teacher_hotpath_benchmark",
        "result_id": "plan062-direction1-teacher-hotpath-optimizations",
        "body_free": True,
        "benchmark": {
            "name": BENCHMARK_NAME,
            "version": BENCHMARK_VERSION,
            "divan_version": "0.1.21",
            "profile": "bench",
            "timer": "os",
            "requested_sample_count": FORMAL_SAMPLE_COUNT,
            "requested_sample_size": FORMAL_SAMPLE_SIZE,
            "harness_sha256": baseline["harness_sha256"],
        },
        "baseline": {
            key: baseline[key]
            for key in (
                "commit",
                "dirty",
                "wall_time_seconds",
                "environment",
                "resources",
            )
        },
        "candidate": {
            key: candidate[key]
            for key in (
                "commit",
                "dirty",
                "wall_time_seconds",
                "environment",
                "resources",
            )
        },
        "cases": cases,
        "interpretation": {
            "scope": "only the named local synchronous hot paths",
            "task_success_claim": False,
            "model_quality_claim": False,
            "api_latency_claim": False,
        },
        "privacy": {"body_free": True, "raw_tracked": False},
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="action", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("phase", choices=("baseline", "candidate", "smoke"))
    run_parser.add_argument("--smoke", action="store_true")
    aggregate_parser = subparsers.add_parser("aggregate")
    aggregate_parser.add_argument("baseline", type=Path)
    aggregate_parser.add_argument("candidate", type=Path)
    aggregate_parser.add_argument("output", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "run":
            run_benchmark(args.phase, args.smoke)
        else:
            aggregate(args.baseline, args.candidate, args.output)
    except (
        OSError,
        subprocess.SubprocessError,
        Plan062BenchmarkError,
        KeyError,
        ValueError,
    ) as exc:
        print(f"plan062-hotpaths: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
