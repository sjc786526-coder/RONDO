"""L3 Local-static shadow replay against the frozen L5a Sol teacher batch.

Three stages, deliberately separated so the measurement contract is frozen
before any real model output exists:

``verify``
    Read-only.  Re-runs the Plan 032 verifier over the private teacher batch,
    binds it to the tracked body-free lock, and reports counts and set digests.

``run``
    One supervised local model lifecycle.  Every selected sample is replayed
    through the qualified 12k service with the exact canonical static payload
    bytes the teacher saw, and every sample ends in exactly one terminal state.
    Per-sample bodies, raw envelopes and attempts stay in a 0700/0600 private
    directory under the Git common root.

``publish``
    Offline.  Recomputes the frozen L4 metrics from that private batch and
    appends four shadow rows (imported/auto x seed/holdout) plus one aggregate
    baseline.

The teacher labels are a point-in-time Sol distillation target, not human
ground truth: this module only ever says "teacher agreement" and "teacher
disagreement", never "false allow" or "false deny".
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import os
import re
import stat
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

from .. import runtime_bridge
from ..artifacts import (
    ArtifactError,
    ArtifactWriter,
    read_validated_run_records,
    upstream_codex_identity,
)
from ..config import ConfigError, RepoPaths, RuntimeConfig, load_runtime_config
from ..evidence import (
    STATIC_DECISION_SCHEMA_NAME,
    STATIC_PAYLOAD_SCHEMA_VERSION,
    EvidenceError,
    PolicyIdentity,
    StaticApprovalPayload,
    validate_static_decision,
)
from ..exit_codes import CONFIG_ERROR, INFRA_ERROR, SUCCESS
from . import model_backed, teacher_labels
from .client import (
    LocalApprovalClient,
    LocalApprovalError,
    LocalApprovalSettings,
    ServiceUnavailableError,
    StructuredOutputError,
    _parse_response,
    settings_from_config,
)
from .identity import clear_launcher_identity, publish_launcher_identity
from .launcher import (
    GPU_MODEL_SERVING_CAPABILITY,
    _get_json,
    build_serve_command,
    inspect_runtime,
    model_path as resolve_model,
    serve_config_sha256,
    serve_environment,
)
from .qualification import (
    NvidiaSmiSampler,
    QualificationError,
    _PeakSampler,
    _await_ready,
    _foreign_compute_pids,
    _lease,
    _port_released,
    _prepare_private_directory,
    _require_free_port,
    _require_watchdog,
    _service_context_size,
    _stop_process,
    _verify_service_identity,
)


RUN_SCHEMA_VERSION = 1
BASELINE_SCHEMA_VERSION = 1
PUBLICATION_SCHEMA_VERSION = 1
# The whole L4 measurement contract: names, denominators, failure classes,
# percentile rule and units.  Frozen in tracked code and in the tracked
# template below before the first real replay; afterwards only the numbers
# change.  See doc/WBS/local-approval-model.md L4.
METRIC_CONTRACT_NAME = "rondo_l4_local_static_v1"
METRIC_CONTRACT_VERSION = 1
METRIC_CONTRACT_RELATIVE_PATH = (
    "eval/templates/local-approval/l4-metric-contract-v1.json"
)
BASELINE_RELATIVE_PATH = (
    "eval/results/baselines/local-approval-unfinetuned-static-baseline-v1.json"
)
TEACHER_BATCH_ID = "20260815-sol-teacher-labels-v1"
TEACHER_LOCK_RELATIVE_PATH = "eval/locks/local-approval-sol-teacher-labels-v1.json"
TEACHER_LABELS_SHA256 = (
    "7eaafa25aa99de804559ee77f034f4e69f8ff4227f5cf5d8d70c66f0a7b82a40"
)
EXPECTED_PARTITION_COUNTS = {"seed": 24, "holdout": 16}
EXPECTED_SAMPLE_COUNT = 40
PARTITIONS = ("seed", "holdout")

PERCENTILE_METHOD = (
    "nearest-rank on ascending observations: index = ceil(p / 100 * n), 1-based"
)
LATENCY_SCOPE = (
    "monotonic clock from immediately before the sample enters its request "
    "phase to its terminal state, including any granted infrastructure retry"
)
INPUT_TOKEN_SOURCE = (
    "exact frozen census count bound to the sample's canonical static payload"
)
USAGE_TOKEN_SOURCE = "strictly validated service usage from the response envelope"
VRAM_METHOD = (
    "nvidia-smi device-level memory.used sampled every 200ms across the whole "
    "local batch lifecycle with no other CUDA compute process"
)

# One sample belongs to exactly one of these.
DECIDED_ALLOW = "decided_allow"
DECIDED_DENY = "decided_deny"
STRUCTURED_OUTPUT_FAILED = "structured_output_failed"
TIMED_OUT = "timed_out"
INFRA_FAILED = "infra_failed"
TERMINAL_STATES = (
    DECIDED_ALLOW,
    DECIDED_DENY,
    STRUCTURED_OUTPUT_FAILED,
    TIMED_OUT,
    INFRA_FAILED,
)
# Facility behaviour, not a model or teacher judgement: none of these may
# release an allow/deny downstream, and a compliant model deny is never one.
FAIL_CLOSED_STATES = (STRUCTURED_OUTPUT_FAILED, TIMED_OUT, INFRA_FAILED)
DECISION_BY_STATE = {DECIDED_ALLOW: "allow", DECIDED_DENY: "deny"}

PRIVATE_ROOT = "eval-data/local-approval"
PRIVATE_RUN_PREFIX = "l3-replay"
SIDE_IMPORTED = "sol-static"
SIDE_LOCAL = "local-static"
PRODUCT_LOCAL = "rondo-local"

_WATCHDOG_RECHECK_EVERY = 10
_GPU_RELEASE_TIMEOUT_SECONDS = 20.0
_MAX_PRIVATE_FILE_BYTES = 64 * 1024 * 1024
_OUTCOME_FIELDS = {
    "semantic_id",
    "partition",
    "e_final_sha256",
    "static_payload_sha256",
    "terminal_state",
    "decision_outcome",
    "teacher_outcome",
    "teacher_match",
    "latency_ms",
    "attempts",
    "retry_reason",
    "failure_code",
    "input_tokens",
    "usage",
}
_USAGE_FIELDS = {"input_tokens", "output_tokens", "total_tokens"}
_RUN_UID = re.compile(r"[0-9a-f]{16}\Z")


class ShadowReplayError(RuntimeError):
    """Fail-closed error carrying a stable, non-sensitive code."""

    exit_code = INFRA_ERROR

    def __init__(self, code: str, facts: Mapping[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.facts = dict(facts or {})


@dataclass(frozen=True)
class TeacherSample:
    """One frozen selected label and the exact payload the teacher saw."""

    semantic_id: str
    partition: str
    usage: str
    e_final_sha256: str
    static_payload_sha256: str
    input_tokens: int
    request_shape: str
    teacher_outcome: str
    canonical_payload: Mapping[str, Any]


@dataclass(frozen=True)
class TeacherBatch:
    batch_id: str
    summary: Mapping[str, Any]
    samples: tuple[TeacherSample, ...]

    def by_partition(self, partition: str) -> tuple[TeacherSample, ...]:
        return tuple(item for item in self.samples if item.partition == partition)


# --------------------------------------------------------------------------
# Frozen teacher input
# --------------------------------------------------------------------------


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sample_set_sha256(samples: Iterable[TeacherSample]) -> str:
    """Identity of a sample set, independent of ordering and of any body."""

    return canonical_sha256(
        sorted(
            [
                item.semantic_id,
                item.e_final_sha256,
                item.static_payload_sha256,
                item.partition,
                item.usage,
            ]
            for item in samples
        )
    )


def load_teacher_batch(*, worktree_root: Path, private_dir: Path) -> TeacherBatch:
    """Strictly import the frozen batch; any drift refuses the whole run.

    The Plan 032 verifier is re-run in full and its body-free summary has to
    equal the tracked lock byte for byte, so the labels, the canonical payloads
    and the tracked contract are checked by the same code that froze them.
    """

    try:
        summary = teacher_labels.build_summary(
            worktree_root=worktree_root, private_dir=private_dir
        )
        manifest, _raw, selected, outbound, _outbound_raw, _receipt = (
            teacher_labels._validate_frozen_batch(
                worktree_root=worktree_root, private_dir=private_dir
            )
        )
        labels, labels_raw = teacher_labels._load_jsonl(
            private_dir / "labels.jsonl", private=True
        )
    except teacher_labels.TeacherLabelsError as exc:
        raise ShadowReplayError("teacher_batch_invalid", {"blocker": exc.code}) from exc

    lock_path = worktree_root / TEACHER_LOCK_RELATIVE_PATH
    if lock_path.is_symlink() or not lock_path.is_file():
        raise ShadowReplayError("teacher_lock_missing")
    try:
        lock = json.loads(lock_path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ShadowReplayError("teacher_lock_invalid") from exc
    if lock != summary:
        raise ShadowReplayError("teacher_lock_differs_from_batch")
    if (
        summary.get("batch_id") != TEACHER_BATCH_ID
        or summary.get("ready_for_l3") is not True
        or summary["private_artifacts"]["labels_sha256"] != TEACHER_LABELS_SHA256
        or teacher_labels._sha256(labels_raw) != TEACHER_LABELS_SHA256
        or summary["counts"]["selected_labels"] != EXPECTED_SAMPLE_COUNT
        or summary["counts"]["selected_partitions"] != EXPECTED_PARTITION_COUNTS
        or summary["teacher"]["model"] != teacher_labels.TEACHER_MODEL
    ):
        raise ShadowReplayError("teacher_batch_identity_drift")

    payload_by_id = {row["semantic_id"]: row for row in outbound}
    samples: list[TeacherSample] = []
    seen: set[str] = set()
    for row in labels:
        if not isinstance(row, dict) or row.get("batch_id") != TEACHER_BATCH_ID:
            raise ShadowReplayError("teacher_label_row_invalid")
        semantic_id = row.get("semantic_id")
        source = selected.get(semantic_id)
        outbound_row = payload_by_id.get(semantic_id)
        if source is None or outbound_row is None or semantic_id in seen:
            raise ShadowReplayError("teacher_label_identity_set_invalid")
        seen.add(semantic_id)
        if (
            row.get("representative_e_final_sha256") != source["e_final_sha256"]
            or row.get("static_payload_sha256") != source["static_payload_sha256"]
            or row.get("partition") != source["partition"]
            or row.get("usage") != source["usage"]
            or row.get("teacher_model") != teacher_labels.TEACHER_MODEL
            or row.get("prompt_version") != manifest["prompt_version"]
            or row.get("prompt_sha256") != manifest["prompt_sha256"]
        ):
            raise ShadowReplayError("teacher_label_binding_invalid")
        try:
            decision = validate_static_decision(row.get("decision"))
        except (EvidenceError, TypeError) as exc:
            raise ShadowReplayError("teacher_label_decision_invalid") from exc
        samples.append(
            TeacherSample(
                semantic_id=semantic_id,
                partition=source["partition"],
                usage=source["usage"],
                e_final_sha256=source["e_final_sha256"],
                static_payload_sha256=source["static_payload_sha256"],
                input_tokens=source["input_tokens"],
                request_shape=source["request_shape"],
                teacher_outcome=decision["outcome"],
                canonical_payload=outbound_row["canonical_payload"],
            )
        )
    if seen != set(selected):
        raise ShadowReplayError("teacher_label_identity_set_invalid")
    ordered = tuple(sorted(samples, key=lambda item: item.semantic_id))
    counts = {
        partition: sum(1 for item in ordered if item.partition == partition)
        for partition in PARTITIONS
    }
    if counts != EXPECTED_PARTITION_COUNTS or len(ordered) != EXPECTED_SAMPLE_COUNT:
        raise ShadowReplayError("teacher_partition_counts_invalid", {"counts": counts})
    return TeacherBatch(batch_id=TEACHER_BATCH_ID, summary=summary, samples=ordered)


def batch_identity(batch: TeacherBatch) -> dict[str, Any]:
    """Body-free identity of the frozen teacher input, safe to publish."""

    summary = batch.summary
    identity = {
        "batch_id": batch.batch_id,
        "teacher_model": summary["teacher"]["model"],
        "teacher_generated_at": summary["teacher"]["generated_dates"][0],
        "teacher_nature": summary["teacher"]["nature"],
        "prompt_version": summary["prompt"]["version"],
        "prompt_sha256": summary["prompt"]["sha256"],
        "label_schema_version": summary["contracts"]["label_schema_version"],
        "label_schema_sha256": summary["label_schema_sha256"],
        "labels_sha256": summary["private_artifacts"]["labels_sha256"],
        "import_metadata_sha256": summary["private_artifacts"]["import_metadata_sha256"],
        "artifacts": summary["private_artifacts"]["relative_directory"],
        "static_payload_schema_version": summary["contracts"][
            "static_payload_schema_version"
        ],
        "static_decision_schema_name": summary["contracts"][
            "static_decision_schema_name"
        ],
        "identity_rule_version": summary["contracts"]["identity_rule_version"],
        "representative_rule_version": summary["contracts"][
            "representative_rule_version"
        ],
        "sample_set_sha256": sample_set_sha256(batch.samples),
        "sample_count": len(batch.samples),
    }
    for partition in PARTITIONS:
        members = batch.by_partition(partition)
        identity[f"{partition}_sample_set_sha256"] = sample_set_sha256(members)
        identity[f"{partition}_sample_count"] = len(members)
    return identity


# --------------------------------------------------------------------------
# Frozen L4 metric contract
# --------------------------------------------------------------------------


def percentile(sorted_values: Sequence[float], percent: int) -> float | None:
    """Nearest-rank percentile; see `PERCENTILE_METHOD` for the exact rule."""

    if not sorted_values:
        return None
    index = math.ceil(percent / 100 * len(sorted_values))
    return sorted_values[max(1, min(index, len(sorted_values))) - 1]


def _distribution(values: Sequence[float], missing: int, source: str) -> dict[str, Any]:
    ordered = sorted(values)
    return {
        "observed": len(ordered),
        "missing": missing,
        "p50": percentile(ordered, 50),
        "p95": percentile(ordered, 95),
        "source": source,
    }


def validate_outcome_rows(rows: Any) -> tuple[dict[str, Any], ...]:
    """Accept only complete, unambiguous per-sample terminal records."""

    if not isinstance(rows, list) or not rows:
        raise ShadowReplayError("outcome_rows_invalid")
    seen: set[str] = set()
    validated: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != _OUTCOME_FIELDS:
            raise ShadowReplayError("outcome_row_fields_invalid")
        state = row["terminal_state"]
        decision = row["decision_outcome"]
        semantic_id = row["semantic_id"]
        if (
            not isinstance(semantic_id, str)
            or semantic_id in seen
            or state not in TERMINAL_STATES
            or row["partition"] not in PARTITIONS
            or row["teacher_outcome"] not in {"allow", "deny"}
            or decision != DECISION_BY_STATE.get(state)
            or row["teacher_match"]
            != (None if decision is None else decision == row["teacher_outcome"])
            or isinstance(row["latency_ms"], bool)
            or not isinstance(row["latency_ms"], (int, float))
            or not math.isfinite(row["latency_ms"])
            or row["latency_ms"] < 0
            or isinstance(row["attempts"], bool)
            or not isinstance(row["attempts"], int)
            or not 1 <= row["attempts"] <= 2
            or (row["attempts"] == 2) != (row["retry_reason"] is not None)
            or (row["retry_reason"] not in (None, "infra_retry"))
            or isinstance(row["input_tokens"], bool)
            or not isinstance(row["input_tokens"], int)
            or row["input_tokens"] <= 0
            or (state in DECISION_BY_STATE) != (row["failure_code"] is None)
        ):
            raise ShadowReplayError("outcome_row_invalid", {"semantic_id": semantic_id})
        usage = row["usage"]
        if usage is not None:
            if (
                not isinstance(usage, dict)
                or set(usage) != _USAGE_FIELDS
                or any(
                    isinstance(usage[key], bool)
                    or not isinstance(usage[key], int)
                    or usage[key] < 0
                    for key in _USAGE_FIELDS
                )
                or usage["input_tokens"] + usage["output_tokens"]
                != usage["total_tokens"]
            ):
                raise ShadowReplayError("outcome_usage_invalid")
        seen.add(semantic_id)
        validated.append(row)
    return tuple(sorted(validated, key=lambda row: row["semantic_id"]))


def summarize(rows: Sequence[Mapping[str, Any]], *, scope: str) -> dict[str, Any]:
    """Build the frozen L4 metric block for one scope from terminal records.

    The primary quality number is teacher agreement over comparable decisions
    only, and the effective-decision coverage plus every failure class are
    reported next to it, so judgement quality and engineering usability stay
    separate and no failure can vanish from the baseline.
    """

    total = len(rows)
    if total <= 0:
        raise ShadowReplayError("summary_input_empty")
    states = {state: 0 for state in TERMINAL_STATES}
    local_decisions = {"allow": 0, "deny": 0}
    teacher_decisions = {"allow": 0, "deny": 0}
    agreement = 0
    disagreement = 0
    latencies: list[float] = []
    input_tokens: list[float] = []
    output_tokens: list[float] = []
    total_tokens: list[float] = []
    usage_missing = 0
    usage_input_matching = 0
    usage_input_differing = 0
    for row in rows:
        states[row["terminal_state"]] += 1
        teacher_decisions[row["teacher_outcome"]] += 1
        latencies.append(float(row["latency_ms"]))
        input_tokens.append(float(row["input_tokens"]))
        decision = row["decision_outcome"]
        if decision is not None:
            local_decisions[decision] += 1
            if decision == row["teacher_outcome"]:
                agreement += 1
            else:
                disagreement += 1
        usage = row["usage"]
        if usage is None:
            usage_missing += 1
            continue
        output_tokens.append(float(usage["output_tokens"]))
        total_tokens.append(float(usage["total_tokens"]))
        if usage["input_tokens"] == row["input_tokens"]:
            usage_input_matching += 1
        else:
            usage_input_differing += 1
    comparable = agreement + disagreement
    fail_closed = {state: states[state] for state in FAIL_CLOSED_STATES}
    fail_closed["total"] = sum(fail_closed.values())
    return {
        "metric_contract": METRIC_CONTRACT_NAME,
        "metric_contract_version": METRIC_CONTRACT_VERSION,
        "scope": scope,
        "sample_count": total,
        "terminal_states": states,
        "comparable_decision_count": comparable,
        "effective_decision_coverage": {
            "numerator": comparable,
            "denominator": total,
            "ratio": comparable / total,
        },
        "teacher_agreement": {
            "numerator": agreement,
            "denominator": comparable,
            "rate": (agreement / comparable) if comparable else None,
        },
        "teacher_disagreement_count": disagreement,
        "fail_closed": fail_closed,
        "teacher_decisions": teacher_decisions,
        "local_decisions": local_decisions,
        "latency_ms": {
            **_distribution(latencies, total - len(latencies), LATENCY_SCOPE),
            "unit": "milliseconds",
            "percentile_method": PERCENTILE_METHOD,
        },
        "tokens": {
            "unit": "tokens",
            "percentile_method": PERCENTILE_METHOD,
            "input": _distribution(input_tokens, 0, INPUT_TOKEN_SOURCE),
            "output": _distribution(output_tokens, usage_missing, USAGE_TOKEN_SOURCE),
            "total": _distribution(total_tokens, usage_missing, USAGE_TOKEN_SOURCE),
            "input_usage_check": {
                "matching": usage_input_matching,
                "differing": usage_input_differing,
                "missing": usage_missing,
            },
        },
    }


def summarize_all(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Seed, holdout and the overall set, all through the same pure function."""

    blocks = {
        partition: summarize(
            [row for row in rows if row["partition"] == partition], scope=partition
        )
        for partition in PARTITIONS
    }
    blocks["overall"] = summarize(rows, scope="overall")
    return blocks


def metric_contract_document() -> dict[str, Any]:
    """The frozen, publishable description of what the L4 numbers mean."""

    return {
        "schema_version": METRIC_CONTRACT_VERSION,
        "name": METRIC_CONTRACT_NAME,
        "purpose": (
            "frozen L4 approval-quality and engineering-usability metric "
            "contract for Local-static shadow replays of the Sol teacher batch"
        ),
        "teacher_semantics": (
            "teacher labels are a point-in-time Sol distillation target, not "
            "human ground truth; differences are teacher disagreement and are "
            "never reported as false allow or false deny"
        ),
        "terminal_states": list(TERMINAL_STATES),
        "fail_closed_states": list(FAIL_CLOSED_STATES),
        "teacher_agreement_rate": (
            "teacher_agreement.numerator / comparable_decision_count; null when "
            "the denominator is zero"
        ),
        "comparable_decision_count": (
            "samples whose terminal state is a schema-valid allow or deny"
        ),
        "effective_decision_coverage": (
            "comparable_decision_count / sample_count for the scope"
        ),
        "percentile_method": PERCENTILE_METHOD,
        "latency_scope": LATENCY_SCOPE,
        "latency_unit": "milliseconds",
        "token_unit": "tokens",
        "input_token_source": INPUT_TOKEN_SOURCE,
        "usage_token_source": USAGE_TOKEN_SOURCE,
        "vram_method": VRAM_METHOD,
        "vram_scope": "peak bytes across the whole local batch lifecycle",
        "scopes": [*PARTITIONS, "overall"],
        "public_projection": {
            "seed": "batch summary plus body-free per-sample identity is allowed",
            "holdout": "batch summary only; tasks must be null",
        },
        "thresholds": (
            "none; no mechanical pass or fail gate is derived from these numbers"
        ),
    }


def load_metric_contract(worktree_root: Path) -> dict[str, Any]:
    path = worktree_root / METRIC_CONTRACT_RELATIVE_PATH
    if path.is_symlink() or not path.is_file():
        raise ShadowReplayError("metric_contract_missing")
    try:
        value = json.loads(path.read_bytes())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ShadowReplayError("metric_contract_invalid") from exc
    if value != metric_contract_document():
        raise ShadowReplayError("metric_contract_drift")
    return value


# --------------------------------------------------------------------------
# Private run artifacts
# --------------------------------------------------------------------------


def _write_private_json(path: Path, value: Mapping[str, Any]) -> Path:
    return _write_private_bytes(path, canonical_bytes(value) + b"\n")


def _write_private_bytes(path: Path, raw: bytes) -> Path:
    if path.exists() or path.is_symlink():
        raise ShadowReplayError("private_output_already_exists")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("write did not progress")
            view = view[written:]
        os.fsync(descriptor)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    return path


def _read_private_json(path: Path) -> tuple[Any, bytes]:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ShadowReplayError("private_input_missing") from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISREG(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_size > _MAX_PRIVATE_FILE_BYTES
    ):
        raise ShadowReplayError("private_input_unsafe")
    raw = path.read_bytes()
    try:
        return json.loads(raw), raw
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ShadowReplayError("private_input_invalid") from exc


def _require_private_run_directory(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise ShadowReplayError("private_run_directory_missing") from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ShadowReplayError("private_run_directory_invalid")


# --------------------------------------------------------------------------
# Measurement state
# --------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    result = _git_result(root, *args)
    if result.returncode != 0:
        raise ShadowReplayError("harness_commit_unavailable")
    return result.stdout.strip()


def _git_result(root: Path, *args: str) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            ("git", "-C", os.fspath(root), *args),
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="strict",
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LC_ALL": "C"},
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError, ValueError) as exc:
        raise ShadowReplayError("harness_commit_unavailable") from exc


def require_run_commit_in_history(worktree_root: Path, commit: str) -> None:
    """Bind the publication to the harness the measurement actually came from.

    Publication is offline and necessarily happens after the run, so `HEAD`
    legitimately moves on: the results and the documentation are themselves
    commits.  Requiring `HEAD` to still equal the run commit would make the
    delivered state unable to recompute its own baseline.  What has to stay
    true is that the exact harness is still reachable in this history and was
    not rewritten away.  The run-time clean-tree rule is unchanged.
    """

    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ShadowReplayError("harness_commit_invalid")
    result = _git_result(
        worktree_root, "merge-base", "--is-ancestor", commit, "HEAD"
    )
    if result.returncode != 0:
        raise ShadowReplayError(
            "harness_commit_not_in_history", {"commit": commit[:12]}
        )


def harness_state(worktree_root: Path) -> dict[str, Any]:
    commit = _git(worktree_root, "rev-parse", "HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ShadowReplayError("harness_commit_unavailable")
    dirty = bool(
        _git(worktree_root, "status", "--porcelain=v1", "--untracked-files=normal")
    )
    return {"eval_harness_commit": commit, "git_dirty": dirty}


def _timeout_cause(error: BaseException) -> bool:
    """Tell an inference read timeout apart from any other transport failure."""

    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        if isinstance(current, TimeoutError):
            return True
        seen.add(id(current))
        current = current.__cause__ or current.__context__
    return False


def extract_usage(envelope: Any) -> dict[str, int] | None:
    """Read usage only when the envelope reports it in a fully consistent form.

    Missing or inconsistent usage is counted as missing rather than filled with
    zeros or with the frozen census count, so the published output and total
    token statistics only ever describe measured samples.
    """

    if not isinstance(envelope, Mapping):
        return None
    usage = envelope.get("usage")
    if not isinstance(usage, Mapping):
        return None
    values: dict[str, int] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
        value = usage.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        values[key] = value
    if values["input_tokens"] + values["output_tokens"] != values["total_tokens"]:
        return None
    if values["output_tokens"] <= 0:
        return None
    return values


def build_payload(sample: TeacherSample) -> StaticApprovalPayload:
    """Rebuild the accepted payload object from the frozen canonical bytes."""

    canonical = canonical_bytes(sample.canonical_payload)
    if hashlib.sha256(canonical).hexdigest() != sample.static_payload_sha256:
        raise ShadowReplayError("frozen_payload_sha256_mismatch")
    policy = sample.canonical_payload.get("guardian_policy")
    if not isinstance(policy, str) or not policy:
        raise ShadowReplayError("frozen_payload_policy_invalid")
    return StaticApprovalPayload(
        PolicyIdentity(
            STATIC_PAYLOAD_SCHEMA_VERSION,
            sample.request_shape,
            hashlib.sha256(policy.encode("utf-8")).hexdigest(),
            "known",
        ),
        canonical,
        dict(sample.canonical_payload),
    )


def _teardown(
    config: RuntimeConfig,
    process: subprocess.Popen[Any] | None,
    identity: Any,
    settings: LocalApprovalSettings,
    identity_clearer: Callable[[RuntimeConfig, Any], None],
    sampler: Any,
) -> dict[str, bool]:
    """Stop only this task's own server and receipt; keep the private batch."""

    stopped = True if process is None else _stop_process(process)
    receipt_cleared = True
    if identity is not None:
        try:
            identity_clearer(config, identity)
        except (ConfigError, OSError):
            receipt_cleared = False
        else:
            receipt_cleared = not (
                config.paths.common_root / PRIVATE_ROOT / "launcher-identity.json"
            ).exists()
    return {
        "server_stopped": stopped,
        "port_released": _port_released(settings.host, settings.port),
        "receipt_cleared": receipt_cleared,
        "gpu_released": _gpu_released(sampler),
    }


def _gpu_released(sampler: Any) -> bool:
    """Confirm the device reports no CUDA compute process after teardown."""

    deadline = time.monotonic() + _GPU_RELEASE_TIMEOUT_SECONDS
    while True:
        try:
            if not sampler.compute_process_pids():
                return True
        except Exception:
            return False
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.5)


def run_replay(
    config: RuntimeConfig,
    *,
    teacher_private_dir: Path,
    popen: Callable[..., subprocess.Popen[Any]] = subprocess.Popen,
    watchdog_factory: Callable[[], runtime_bridge.WatchdogProof] | None = None,
    gpu_sampler: Any | None = None,
    identity_publisher: Callable[..., Any] = publish_launcher_identity,
    identity_clearer: Callable[[RuntimeConfig, Any], None] = clear_launcher_identity,
    verify_identity: Callable[[RuntimeConfig, Path], None] | None = None,
    http_get: Callable[..., Any] = _get_json,
    clock: Callable[[], float] = time.monotonic,
    now: Callable[[], datetime.datetime] | None = None,
) -> dict[str, Any]:
    """Replay the whole frozen batch in one supervised model lifecycle."""

    settings = settings_from_config(config)
    model_backed.require_qualification_contract(config, settings)
    evidence = model_backed.load_model_backed_evidence(config)
    if evidence is None:
        raise ShadowReplayError("qualification_evidence_unavailable")
    load_metric_contract(config.paths.worktree_root)
    harness = harness_state(config.paths.worktree_root)
    if harness["git_dirty"]:
        # The metric contract has to be frozen in a clean commit before any
        # real model output exists; a dirty tree cannot prove that ordering.
        raise ShadowReplayError("harness_not_clean")
    batch = load_teacher_batch(
        worktree_root=config.paths.worktree_root, private_dir=teacher_private_dir
    )

    client = LocalApprovalClient(config)
    requests = {
        sample.semantic_id: client.build_request(build_payload(sample))
        for sample in batch.samples
    }
    model = resolve_model(config, settings)

    watchdog = _lease(watchdog_factory)
    runtime = inspect_runtime(config, settings)
    if not runtime.ok or runtime.binary is None or runtime.identity_sha256 is None:
        raise ShadowReplayError("runtime_not_ready", {"detail": runtime.detail})
    if runtime.capability != GPU_MODEL_SERVING_CAPABILITY:
        raise ShadowReplayError(
            "runtime_capability_unexpected", {"capability": runtime.capability}
        )

    sampler = gpu_sampler if gpu_sampler is not None else NvidiaSmiSampler()
    if sampler.compute_process_pids():
        raise ShadowReplayError("gpu_not_exclusive")
    baseline_vram = sampler.used_bytes()
    _require_free_port(settings.host, settings.port)

    command = build_serve_command(config, settings, runtime.binary)
    serving_config = serve_config_sha256(config, settings)
    private_root = _prepare_private_directory(config, prefix=PRIVATE_RUN_PREFIX)
    run_uid = private_root.name.rsplit("-", 1)[-1]
    log_path = private_root / "server.log"
    attempts_path = private_root / "attempts.jsonl"
    started_at = (now() if now is not None else datetime.datetime.now().astimezone())

    process: subprocess.Popen[Any] | None = None
    identity = None
    peak: _PeakSampler | None = None
    failure: ShadowReplayError | None = None
    outcomes: list[dict[str, Any]] = []
    attempt_records: list[dict[str, Any]] = []
    peak_vram = baseline_vram
    vram_samples = 0
    try:
        _require_watchdog(watchdog)
        descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            process = popen(
                command,
                env=serve_environment(config),
                stdout=descriptor,
                stderr=subprocess.STDOUT,
            )
        finally:
            os.close(descriptor)
        peak = _PeakSampler(sampler, baseline_vram, process.pid)
        peak.start()
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
        _service_context_size(props)
        if verify_identity is None:
            _verify_service_identity(config, model)
        else:
            verify_identity(config, model)
        foreign = _foreign_compute_pids(sampler, process.pid)
        if foreign:
            raise ShadowReplayError("gpu_not_exclusive", {"foreign_compute_pids": foreign})
        bound = client.require_service_identity()

        for index, sample in enumerate(batch.samples, start=1):
            outcome, attempts = _replay_sample(
                client, sample, requests[sample.semantic_id], bound, clock
            )
            outcomes.append(outcome)
            attempt_records.extend(attempts)
            if index % _WATCHDOG_RECHECK_EVERY == 0:
                _require_watchdog(watchdog)
                peak.observe()
        _require_watchdog(watchdog)
        foreign = _foreign_compute_pids(sampler, process.pid)
        if foreign:
            raise ShadowReplayError("gpu_not_exclusive", {"foreign_compute_pids": foreign})
        peak.observe()
        peak_vram = peak.finalize()
        vram_samples = peak.samples
    except ShadowReplayError as error:
        failure = error
    except QualificationError as error:
        failure = ShadowReplayError(error.code, error.facts)
    except LocalApprovalError as error:
        # The only way one of these escapes a sample is the post-failure
        # identity re-check: the bound instance is gone, so the batch is over.
        failure = ShadowReplayError(
            "service_identity_lost", {"error": type(error).__name__}
        )
    finally:
        if peak is not None:
            peak.stop()
        cleanup = _teardown(
            config, process, identity, settings, identity_clearer, sampler
        )

    finished_at = now() if now is not None else datetime.datetime.now().astimezone()
    _write_private_bytes(
        attempts_path,
        b"".join(canonical_bytes(row) + b"\n" for row in attempt_records),
    )
    if failure is not None:
        facts = dict(failure.facts)
        facts.update(
            {
                "cleanup": cleanup,
                "samples_with_terminal_state": len(outcomes),
                "private_run_directory": private_root.name,
            }
        )
        raise ShadowReplayError(failure.code, facts) from failure
    if not all(cleanup.values()):
        raise ShadowReplayError("cleanup_incomplete", {"cleanup": cleanup})

    rows = validate_outcome_rows(outcomes)
    if {row["semantic_id"] for row in rows} != {
        sample.semantic_id for sample in batch.samples
    }:
        raise ShadowReplayError("terminal_state_set_incomplete")

    document = {
        "schema_version": RUN_SCHEMA_VERSION,
        "kind": "l3_local_static_replay",
        "run_uid": run_uid,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
        "harness": harness,
        "teacher": batch_identity(batch),
        "service": {
            "model_id": settings.model_id,
            "model_relative_path": model_backed.MODEL_RELATIVE_PATH,
            "model_sha256": settings.model_sha256,
            "quantization": settings.quantization,
            "fine_tuned": False,
            "runtime_relative_path": model_backed.CUDA_RUNTIME_RELATIVE_PATH,
            "runtime_identity_sha256": runtime.identity_sha256,
            "service_build_info": model_backed.service_build_info(settings),
            "serve_config_sha256": serving_config,
            "request_contract_sha256": model_backed.request_contract_sha256(settings),
            "chat_template_sha256": settings.chat_template_sha256,
            "context_size": settings.context_size,
            "max_output_tokens": settings.max_output_tokens,
            "temperature": settings.temperature,
            "top_p": settings.top_p,
            "seed": settings.seed,
            "qualification_capability": model_backed.GPU_MODEL_SERVING_CAPABILITY,
            "qualification_evidence_relative_path": model_backed.EVIDENCE_RELATIVE_PATH,
            "static_payload_schema_version": STATIC_PAYLOAD_SCHEMA_VERSION,
            "static_decision_schema_name": STATIC_DECISION_SCHEMA_NAME,
        },
        "vram": {
            "baseline_bytes": baseline_vram,
            "peak_bytes": peak_vram,
            "delta_bytes": peak_vram - baseline_vram,
            "samples": vram_samples,
            "complete": True,
            "method": VRAM_METHOD,
            "scope": "peak bytes across the whole local batch lifecycle",
        },
        "cleanup": cleanup,
        "attempts_sha256": hashlib.sha256(attempts_path.read_bytes()).hexdigest(),
        "outcomes": list(rows),
    }
    _write_private_json(private_root / "run.json", document)
    return {
        "status": "completed",
        "run_uid": run_uid,
        "private_run_directory": private_root.name,
        "samples": len(rows),
        "terminal_states": summarize(rows, scope="overall")["terminal_states"],
        "peak_vram_bytes": peak_vram,
        "cleanup": cleanup,
    }


def _replay_sample(
    client: LocalApprovalClient,
    sample: TeacherSample,
    request: Mapping[str, Any],
    bound: Any,
    clock: Callable[[], float],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Replay one sample to exactly one terminal state.

    Only an unambiguous local transport or infrastructure failure that carries
    no model judgement may be retried, once, with the identical input.  A read
    timeout, a structured-output failure and any allow/deny the model actually
    produced are results, never a reason to send the sample again.
    """

    attempts: list[dict[str, Any]] = []
    state: str | None = None
    failure_code: str | None = None
    decision: dict[str, Any] | None = None
    usage: dict[str, int] | None = None
    retry_reason: str | None = None
    started = clock()
    for attempt in (1, 2):
        record: dict[str, Any] = {
            "semantic_id": sample.semantic_id,
            "partition": sample.partition,
            "attempt": attempt,
        }
        try:
            envelope = client.post_decision_request(request, bound)
        except ServiceUnavailableError as error:
            timed_out = _timeout_cause(error)
            # A transport failure only belongs to the sample while the bound
            # instance is still there; otherwise the whole batch is over.
            client.require_service_identity()
            state = TIMED_OUT if timed_out else INFRA_FAILED
            failure_code = "inference_timeout" if timed_out else "service_unavailable"
            record.update({"outcome": state, "failure_code": failure_code})
            attempts.append(record)
            if timed_out or attempt == 2:
                break
            retry_reason = "infra_retry"
            continue
        except StructuredOutputError:
            state = STRUCTURED_OUTPUT_FAILED
            failure_code = "response_envelope_invalid"
            record.update({"outcome": state, "failure_code": failure_code})
            attempts.append(record)
            break
        record["raw_envelope"] = envelope
        usage = extract_usage(envelope)
        try:
            decision = _parse_response(envelope, expected_model=client.settings.model_id)
        except StructuredOutputError:
            state = STRUCTURED_OUTPUT_FAILED
            failure_code = "structured_decision_invalid"
            record.update({"outcome": state, "failure_code": failure_code})
            attempts.append(record)
            break
        state = DECIDED_ALLOW if decision["outcome"] == "allow" else DECIDED_DENY
        failure_code = None
        record.update({"outcome": state, "decision": decision})
        attempts.append(record)
        break
    latency_ms = (clock() - started) * 1000.0
    if state is None:  # pragma: no cover - the loop always assigns a state
        raise ShadowReplayError("terminal_state_missing")
    local_outcome = DECISION_BY_STATE.get(state)
    return (
        {
            "semantic_id": sample.semantic_id,
            "partition": sample.partition,
            "e_final_sha256": sample.e_final_sha256,
            "static_payload_sha256": sample.static_payload_sha256,
            "terminal_state": state,
            "decision_outcome": local_outcome,
            "teacher_outcome": sample.teacher_outcome,
            "teacher_match": (
                None if local_outcome is None else local_outcome == sample.teacher_outcome
            ),
            "latency_ms": latency_ms,
            "attempts": len(attempts),
            "retry_reason": retry_reason if len(attempts) == 2 else None,
            "failure_code": failure_code,
            "input_tokens": sample.input_tokens,
            "usage": usage,
        },
        attempts,
    )


# --------------------------------------------------------------------------
# Publication
# --------------------------------------------------------------------------


def load_private_run(private_run_dir: Path) -> dict[str, Any]:
    _require_private_run_directory(private_run_dir)
    document, _raw = _read_private_json(private_run_dir / "run.json")
    if (
        not isinstance(document, dict)
        or document.get("schema_version") != RUN_SCHEMA_VERSION
        or document.get("kind") != "l3_local_static_replay"
        or not _RUN_UID.fullmatch(str(document.get("run_uid", "")))
    ):
        raise ShadowReplayError("private_run_document_invalid")
    document["outcomes"] = list(validate_outcome_rows(document.get("outcomes")))
    if len(document["outcomes"]) != EXPECTED_SAMPLE_COUNT:
        raise ShadowReplayError("private_run_sample_count_invalid")
    vram = document.get("vram")
    if (
        not isinstance(vram, dict)
        or vram.get("complete") is not True
        or not isinstance(vram.get("peak_bytes"), int)
        or vram["peak_bytes"] <= 0
        or vram.get("samples", 0) <= 0
    ):
        raise ShadowReplayError("private_run_vram_invalid")
    return document


def _run_id(stamp: datetime.datetime, side: str, offset_ms: int) -> str:
    moment = stamp + datetime.timedelta(milliseconds=offset_ms)
    return f"{moment.strftime('%Y%m%d-%H%M%S')}{moment.microsecond // 1000:03d}-shadow-{side}-r1"


def _publication_plan(
    document: Mapping[str, Any], stamp: datetime.datetime
) -> dict[str, Any]:
    entries = []
    for offset, (partition, side, source) in enumerate(
        (
            ("seed", SIDE_IMPORTED, "imported"),
            ("seed", SIDE_LOCAL, "auto"),
            ("holdout", SIDE_IMPORTED, "imported"),
            ("holdout", SIDE_LOCAL, "auto"),
        )
    ):
        entries.append(
            {
                "run_id": _run_id(stamp, side, offset),
                "partition": partition,
                "side": side,
                "source": source,
            }
        )
    if len({entry["run_id"] for entry in entries}) != len(entries):
        raise ShadowReplayError("publication_run_ids_collide")
    return {
        "schema_version": PUBLICATION_SCHEMA_VERSION,
        "run_uid": document["run_uid"],
        "created_at": stamp.isoformat(timespec="seconds"),
        "records": entries,
        "baseline": BASELINE_RELATIVE_PATH,
    }


def _seed_tasks(
    rows: Sequence[Mapping[str, Any]], *, source: str
) -> list[dict[str, Any]]:
    """Body-free per-sample projection; only ever built for the seed partition."""

    tasks = []
    for row in sorted(rows, key=lambda item: item["semantic_id"]):
        if source == "imported":
            tasks.append(
                {"task_id": row["semantic_id"], "outcome": row["teacher_outcome"]}
            )
            continue
        tasks.append(
            {
                "task_id": row["semantic_id"],
                "outcome": row["terminal_state"],
                "decision": row["decision_outcome"],
                "teacher_match": row["teacher_match"],
                "duration_ms": round(float(row["latency_ms"]), 3),
                "tokens_in": row["input_tokens"],
                "tokens_out": None if row["usage"] is None else row["usage"]["output_tokens"],
            }
        )
    return tasks


def build_records(
    document: Mapping[str, Any],
    plan: Mapping[str, Any],
    metrics: Mapping[str, Mapping[str, Any]],
    *,
    created_at: str,
) -> list[dict[str, Any]]:
    """Build the four shadow rows from one frozen private batch."""

    teacher = document["teacher"]
    service = document["service"]
    harness = document["harness"]
    rows_by_partition = {
        partition: [
            row for row in document["outcomes"] if row["partition"] == partition
        ]
        for partition in PARTITIONS
    }
    records: list[dict[str, Any]] = []
    for entry in plan["records"]:
        partition = entry["partition"]
        source = entry["source"]
        rows = rows_by_partition[partition]
        block = metrics[partition]
        common = {
            "schema_version": 1,
            "run_id": entry["run_id"],
            "created_at": created_at,
            "track": "shadow",
            "side": entry["side"],
            "source": source,
            "git_commit": harness["eval_harness_commit"],
            "git_dirty": harness["git_dirty"],
            "upstream_codex": upstream_codex_identity(),
            "outcome": "completed",
            "cost": {"estimated_usd": 0.0, "actual_usd": None},
        }
        shared_config = {
            "partition": partition,
            "taskset": partition,
            "round": 1,
            "teacher_batch_id": teacher["batch_id"],
            "sample_count": teacher[f"{partition}_sample_count"],
            "sample_set_sha256": teacher[f"{partition}_sample_set_sha256"],
            "static_payload_schema_version": teacher["static_payload_schema_version"],
            "static_decision_schema_name": teacher["static_decision_schema_name"],
            "eval_harness_commit": harness["eval_harness_commit"],
        }
        if source == "imported":
            records.append(
                {
                    **common,
                    "binary_sha256": None,
                    "config": {
                        **shared_config,
                        "teacher_model": teacher["teacher_model"],
                        "generated_at": teacher["teacher_generated_at"],
                        "prompt_version": teacher["prompt_version"],
                        "prompt_sha256": teacher["prompt_sha256"],
                        "teacher_nature": teacher["teacher_nature"],
                        "label_schema_version": teacher["label_schema_version"],
                        "label_schema_sha256": teacher["label_schema_sha256"],
                        "labels_sha256": teacher["labels_sha256"],
                        "import_metadata_sha256": teacher["import_metadata_sha256"],
                        "identity_rule_version": teacher["identity_rule_version"],
                        "representative_rule_version": teacher[
                            "representative_rule_version"
                        ],
                    },
                    "summary": {
                        "partition": partition,
                        "samples": block["sample_count"],
                        "teacher_decisions": block["teacher_decisions"],
                        "sample_set_sha256": teacher[f"{partition}_sample_set_sha256"],
                    },
                    "tasks": (
                        _seed_tasks(rows, source=source) if partition == "seed" else None
                    ),
                    "metrics": None,
                    "artifacts": teacher["artifacts"],
                    "notes": (
                        "Imported frozen point-in-time Sol teacher labels; not an "
                        "automated eval run and not human ground truth."
                    ),
                }
            )
            continue
        records.append(
            {
                **common,
                "product": PRODUCT_LOCAL,
                "binary_sha256": service["model_sha256"],
                "config": {
                    **shared_config,
                    "product": PRODUCT_LOCAL,
                    "binary_product": PRODUCT_LOCAL,
                    "teacher_model": teacher["teacher_model"],
                    "teacher_generated_at": teacher["teacher_generated_at"],
                    "teacher_labels_sha256": teacher["labels_sha256"],
                    "metric_contract": METRIC_CONTRACT_NAME,
                    "metric_contract_version": METRIC_CONTRACT_VERSION,
                    "local_run_uid": document["run_uid"],
                    **{
                        key: service[key]
                        for key in (
                            "model_id",
                            "model_relative_path",
                            "model_sha256",
                            "quantization",
                            "fine_tuned",
                            "runtime_relative_path",
                            "runtime_identity_sha256",
                            "service_build_info",
                            "serve_config_sha256",
                            "request_contract_sha256",
                            "chat_template_sha256",
                            "context_size",
                            "max_output_tokens",
                            "temperature",
                            "top_p",
                            "seed",
                            "qualification_capability",
                            "qualification_evidence_relative_path",
                        )
                    },
                },
                "summary": {
                    "partition": partition,
                    "samples": block["sample_count"],
                    "terminal_states": block["terminal_states"],
                    "comparable_decision_count": block["comparable_decision_count"],
                    "teacher_agreement_rate": block["teacher_agreement"]["rate"],
                    "teacher_disagreement_count": block["teacher_disagreement_count"],
                    "fail_closed": block["fail_closed"]["total"],
                    "sample_set_sha256": teacher[f"{partition}_sample_set_sha256"],
                },
                "tasks": (
                    _seed_tasks(rows, source=source) if partition == "seed" else None
                ),
                "metrics": {**block, "vram": document["vram"]},
                "artifacts": f"eval-data/runs/{entry['run_id']}",
                "notes": (
                    "Unfinetuned Local-static replay of the frozen teacher batch; "
                    "differences from the teacher are teacher disagreement, not "
                    "false allow or false deny."
                ),
            }
        )
    return records


def build_baseline(
    document: Mapping[str, Any],
    plan: Mapping[str, Any],
    metrics: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": BASELINE_SCHEMA_VERSION,
        "purpose": (
            "unfinetuned RONDO Local static approval baseline against the frozen "
            "point-in-time Sol teacher batch"
        ),
        "status": "complete",
        "metric_contract": METRIC_CONTRACT_NAME,
        "metric_contract_version": METRIC_CONTRACT_VERSION,
        "teacher": document["teacher"],
        "service": document["service"],
        "harness": document["harness"],
        "vram": document["vram"],
        "runs": [
            {
                "run_id": entry["run_id"],
                "side": entry["side"],
                "source": entry["source"],
                "partition": entry["partition"],
            }
            for entry in plan["records"]
        ],
        "metrics": dict(metrics),
        "boundaries": {
            "teacher_labels_are_not_human_ground_truth": True,
            "holdout_summary_only": True,
            "false_allow_or_false_deny_reported": False,
            "mechanical_threshold_applied": False,
        },
    }


def publish(
    config: RuntimeConfig,
    *,
    private_run_dir: Path,
    teacher_private_dir: Path,
    now: Callable[[], datetime.datetime] | None = None,
) -> dict[str, Any]:
    """Recompute the frozen metrics offline and append the four shadow rows."""

    load_metric_contract(config.paths.worktree_root)
    batch = load_teacher_batch(
        worktree_root=config.paths.worktree_root, private_dir=teacher_private_dir
    )
    document = load_private_run(private_run_dir)
    identity = batch_identity(batch)
    if document["teacher"] != identity:
        raise ShadowReplayError("private_run_teacher_identity_drift")
    recorded = {
        (row["semantic_id"], row["e_final_sha256"], row["static_payload_sha256"], row["partition"])
        for row in document["outcomes"]
    }
    expected = {
        (item.semantic_id, item.e_final_sha256, item.static_payload_sha256, item.partition)
        for item in batch.samples
    }
    if recorded != expected:
        raise ShadowReplayError("private_run_sample_set_drift")
    for row in document["outcomes"]:
        sample = next(
            item for item in batch.samples if item.semantic_id == row["semantic_id"]
        )
        if row["teacher_outcome"] != sample.teacher_outcome:
            raise ShadowReplayError("private_run_teacher_label_drift")
    require_run_commit_in_history(
        config.paths.worktree_root, document["harness"]["eval_harness_commit"]
    )

    metrics = summarize_all(document["outcomes"])
    plan_path = private_run_dir / "publication.json"
    if plan_path.exists():
        plan, _raw = _read_private_json(plan_path)
        if (
            not isinstance(plan, dict)
            or plan.get("schema_version") != PUBLICATION_SCHEMA_VERSION
            or plan.get("run_uid") != document["run_uid"]
        ):
            raise ShadowReplayError("publication_plan_invalid")
    else:
        stamp = now() if now is not None else datetime.datetime.now().astimezone()
        plan = _publication_plan(document, stamp)
        _write_private_json(plan_path, plan)

    created_at = plan["created_at"]
    records = build_records(document, plan, metrics, created_at=created_at)
    published: list[str] = []
    for record in records:
        if _publish_record(config, record, document):
            published.append(record["run_id"])

    baseline_path = config.paths.worktree_root / BASELINE_RELATIVE_PATH
    baseline = build_baseline(document, plan, metrics)
    raw = json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True).encode() + b"\n"
    if baseline_path.exists():
        if baseline_path.is_symlink() or baseline_path.read_bytes() != raw:
            raise ShadowReplayError("baseline_already_exists")
    else:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(baseline_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    return {
        "status": "published",
        "run_uid": document["run_uid"],
        "records": [entry["run_id"] for entry in plan["records"]],
        "newly_published": published,
        "baseline": BASELINE_RELATIVE_PATH,
        "baseline_sha256": hashlib.sha256(raw).hexdigest(),
        "metrics": {
            scope: {
                "sample_count": block["sample_count"],
                "comparable_decision_count": block["comparable_decision_count"],
                "teacher_agreement_rate": block["teacher_agreement"]["rate"],
                "fail_closed": block["fail_closed"]["total"],
            }
            for scope, block in metrics.items()
        },
    }


def _publish_record(
    config: RuntimeConfig, record: Mapping[str, Any], document: Mapping[str, Any]
) -> bool:
    """Append one row, reusing the existing journal and recovery semantics."""

    results = config.paths.worktree_root / "eval" / "results" / "runs.jsonl"
    try:
        published = {
            row["run_id"]
            for row, _line in read_validated_run_records(
                results, common_root=config.paths.common_root
            )
        }
    except ArtifactError as exc:
        raise ShadowReplayError("result_index_invalid", {"blocker": str(exc)}) from exc
    if record["run_id"] in published:
        return False
    external = record["artifacts"] if record["source"] == "imported" else None
    writer = ArtifactWriter(
        config.paths, record["run_id"], artifacts_reference=external
    )
    try:
        writer.start()
    except ArtifactError as exc:
        raise ShadowReplayError("publication_failed", {"blocker": str(exc)}) from exc
    try:
        if external is None:
            writer.write_json(
                "shadow-summary.json",
                {
                    "schema_version": RUN_SCHEMA_VERSION,
                    "run_id": record["run_id"],
                    "partition": record["config"]["partition"],
                    "local_run_uid": document["run_uid"],
                    "summary": record["summary"],
                    "metrics": record["metrics"],
                },
            )
        writer.finalize(record, secrets=())
    except ArtifactError as exc:
        if not writer.publication_started():
            writer.abort()
        raise ShadowReplayError("publication_failed", {"blocker": str(exc)}) from exc
    return True


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------


def _print(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _verify(config: RuntimeConfig, teacher_private_dir: Path) -> dict[str, Any]:
    load_metric_contract(config.paths.worktree_root)
    batch = load_teacher_batch(
        worktree_root=config.paths.worktree_root, private_dir=teacher_private_dir
    )
    return {
        "status": "ready_for_replay",
        "teacher": batch_identity(batch),
        "metric_contract": METRIC_CONTRACT_NAME,
        "metric_contract_version": METRIC_CONTRACT_VERSION,
        "harness": harness_state(config.paths.worktree_root),
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="L3 Local-static shadow replay of the frozen Sol teacher batch"
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name in ("verify", "run"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--teacher-private-dir", type=Path, required=True)
    publish_parser = subparsers.add_parser("publish")
    publish_parser.add_argument("--teacher-private-dir", type=Path, required=True)
    publish_parser.add_argument("--private-run-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        config = load_runtime_config(RepoPaths.discover(args.repo))
        if args.command == "verify":
            _print(_verify(config, args.teacher_private_dir))
        elif args.command == "run":
            _print(run_replay(config, teacher_private_dir=args.teacher_private_dir))
        else:
            _print(
                publish(
                    config,
                    private_run_dir=args.private_run_dir,
                    teacher_private_dir=args.teacher_private_dir,
                )
            )
    except ShadowReplayError as error:
        report = {"status": "blocked", "blocker": error.code}
        if error.facts:
            report["facts"] = error.facts
        _print(report)
        return error.exit_code
    except LocalApprovalError as error:
        _print({"status": "blocked", "blocker": type(error).__name__})
        return error.exit_code
    except ConfigError:
        _print({"status": "blocked", "blocker": "configuration"})
        return CONFIG_ERROR
    return SUCCESS


if __name__ == "__main__":
    raise SystemExit(main())
