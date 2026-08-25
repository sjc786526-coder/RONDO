"""The frozen Plan 073 joint evaluation and selection protocol.

This module is the single place where the M3-C2 comparison rules live.  It is
deliberately declarative: the freeze names one method per decision layer and
carries the numeric floors, so a reader can reconstruct why a candidate was
admitted, how its threshold was chosen and how the winner was ranked without
reading the runner.
"""

from __future__ import annotations

from collections.abc import Mapping
import math
from pathlib import Path
import re
from typing import Any

from ..identity import canonical_json_bytes, sha256_bytes


FREEZE_SCHEMA = "rondo-publication-critic-plan073-selection-freeze-v1"
CANDIDATES = ("base", "c1", "c3")
SPLITS = ("validation", "unseen_test")
MODES = ("commissioning", "formal")

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
RUN_ID = re.compile(
    r"plan073-(commissioning|formal)-[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,47}\Z"
)

# Every decision layer names one frozen method.  The strings are part of the
# freeze identity, so a later run cannot silently switch rules while keeping the
# same numbers.
SELECTION_METHOD = {
    "candidate_input": "plan054_packet_render_tokenizer_window_scalar_unchanged_v1",
    "threshold_search": "validation_score_endpoints_and_adjacent_midpoints_v1",
    "threshold_rule": (
        "feasible_floors_then_max_balanced_accuracy_then_min_false_pass_then_max_threshold_v1"
    ),
    "candidate_admission": "all_quality_floors_and_runtime_gates_at_selected_threshold_v1",
    "ranking": (
        "lexicographic_false_pass_then_balanced_then_boundary_then_false_rewrite_"
        "then_auc_then_judge_then_earlier_stage_v1"
    ),
    "judge_role": "blinded_independent_verdict_tiebreak_and_conditional_sanity_gate_v1",
    "runtime_role": "usability_gates_only_same_architecture_not_a_ranking_key_v1",
    "unseen_confirmation": "locked_combination_same_floors_single_blind_campaign_v1",
}

# Publication quality floors.  False PASS is the product's primary error: a bad
# publication that reaches Team State is exactly what the Critic exists to stop.
# A false REWRITE only costs the Producer a bounded rewrite round, because the
# product contract publishes non-blocking after two rewrites.  The floors are
# therefore asymmetric, and they are set as product-acceptability lines rather
# than as "beat the previous number" lines.
_FLOOR_KEYS = {
    "max_false_pass_rate",
    "max_false_rewrite_rate",
    "min_balanced_accuracy",
    "min_roc_auc",
    "min_boundary_pair_strict_win_rate",
    "max_typed_failures",
}
_RUNTIME_GATE_KEYS = {
    "max_load_seconds",
    "max_warm_p95_latency_ms",
    "max_peak_rss_bytes",
    "max_peak_vram_bytes",
}
_JUDGE_KEYS = {
    "coverage",
    "min_reference_agreement_for_gate",
    "min_selected_agreement",
}
_RUNTIME_KEYS = {
    "device",
    "dtype",
    "cpu_threads",
    "deployment_format",
    "scoring_batch",
    "warm_latency_samples",
    "service_limits",
}
_SERVICE_LIMIT_KEYS = {
    "request_bytes",
    "response_bytes",
    "max_concurrency",
    "queue_capacity",
    "job_timeout_ms",
    "io_timeout_ms",
    "worker_startup_timeout_ms",
    "worker_io_timeout_ms",
    "worker_shutdown_timeout_ms",
    "graceful_shutdown_ms",
    "force_shutdown_ms",
    "call_timeout_ms",
    "startup_timeout_ms",
    "process_timeout_ms",
    "representative_cancel_after_ms",
}
_RATE_FLOORS = {
    "max_false_pass_rate",
    "max_false_rewrite_rate",
    "min_balanced_accuracy",
    "min_roc_auc",
    "min_boundary_pair_strict_win_rate",
}

JUDGE_COVERAGE = "all_released_candidates_v1"


class SelectionError(ValueError):
    """A body-free invalid Plan 073 freeze, release, evidence or invocation."""


def require_exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    if set(value) != expected:
        raise SelectionError(f"{label} fields are invalid")


def require_object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SelectionError(f"{label} must be an object")
    return value


def require_finite(
    value: Any,
    label: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise SelectionError(f"{label} must be numeric")
    number = float(value)
    if (
        not math.isfinite(number)
        or (minimum is not None and number < minimum)
        or (maximum is not None and number > maximum)
    ):
        raise SelectionError(f"{label} is outside its finite domain")
    return number


def require_count(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise SelectionError(f"{label} must be a nonnegative integer")
    return value


def is_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def require_sha256(value: Any, label: str) -> str:
    if not is_sha256(value):
        raise SelectionError(f"{label} identity is invalid")
    return str(value)


def freeze_sha256(freeze: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(freeze)))


def validate_source(value: Any, label: str = "Plan 073 source") -> dict[str, Any]:
    source = require_object(value, label)
    require_exact_keys(
        source,
        {
            "git_commit",
            "tracked_source_clean",
            "environment_lock_path",
            "environment_lock_sha256",
        },
        label,
    )
    if (
        not isinstance(source["git_commit"], str)
        or _GIT_COMMIT.fullmatch(source["git_commit"]) is None
        or source["tracked_source_clean"] is not True
    ):
        raise SelectionError(f"{label} identity is invalid")
    require_sha256(source["environment_lock_sha256"], f"{label} environment lock")
    lock_path = source["environment_lock_path"]
    if (
        not isinstance(lock_path, str)
        or Path(lock_path).is_absolute()
        or ".." in Path(lock_path).parts
        or Path(lock_path).name != "uv.lock"
    ):
        raise SelectionError(f"{label} environment lock path is invalid")
    return dict(source)


def validate_runtime(value: Any, label: str = "Plan 073 runtime") -> dict[str, Any]:
    runtime = require_object(value, label)
    require_exact_keys(runtime, _RUNTIME_KEYS, label)
    if runtime["device"] not in {"cpu", "cuda"} or runtime["dtype"] not in {
        "float32",
        "bfloat16",
    }:
        raise SelectionError(f"{label} device or dtype is invalid")
    if type(runtime["cpu_threads"]) is not int or runtime["cpu_threads"] <= 0:
        raise SelectionError(f"{label} CPU threads are invalid")
    for name in ("deployment_format", "scoring_batch"):
        if not isinstance(runtime[name], str) or not runtime[name].strip():
            raise SelectionError(f"{label} {name} is invalid")
    if type(runtime["warm_latency_samples"]) is not int or runtime[
        "warm_latency_samples"
    ] < 3:
        raise SelectionError(f"{label} warm latency sampling is invalid")
    limits = require_object(runtime["service_limits"], f"{label} service limits")
    require_exact_keys(limits, _SERVICE_LIMIT_KEYS, f"{label} service limits")
    for name in _SERVICE_LIMIT_KEYS:
        if type(limits[name]) is not int or limits[name] <= 0:
            raise SelectionError(f"{label} service limit {name} is invalid")
    return dict(runtime)


def _validate_protocol(value: Any) -> dict[str, Any]:
    protocol = require_object(value, "Plan 073 protocol")
    require_exact_keys(
        protocol,
        {"method", "quality_floors", "runtime_gates", "judge", "rationale"},
        "Plan 073 protocol",
    )
    if protocol["method"] != SELECTION_METHOD:
        raise SelectionError("Plan 073 protocol method identity is invalid")

    floors = require_object(protocol["quality_floors"], "Plan 073 quality floors")
    require_exact_keys(floors, _FLOOR_KEYS, "Plan 073 quality floors")
    for name in _RATE_FLOORS:
        require_finite(floors[name], f"Plan 073 floor {name}", minimum=0.0, maximum=1.0)
    require_count(floors["max_typed_failures"], "Plan 073 floor max_typed_failures")

    gates = require_object(protocol["runtime_gates"], "Plan 073 runtime gates")
    require_exact_keys(gates, _RUNTIME_GATE_KEYS, "Plan 073 runtime gates")
    for name in _RUNTIME_GATE_KEYS:
        require_finite(gates[name], f"Plan 073 runtime gate {name}", minimum=0.0)

    judge = require_object(protocol["judge"], "Plan 073 judge protocol")
    require_exact_keys(judge, _JUDGE_KEYS, "Plan 073 judge protocol")
    if judge["coverage"] != JUDGE_COVERAGE:
        raise SelectionError("Plan 073 judge coverage is invalid")
    for name in ("min_reference_agreement_for_gate", "min_selected_agreement"):
        require_finite(judge[name], f"Plan 073 judge {name}", minimum=0.0, maximum=1.0)

    rationale = require_object(protocol["rationale"], "Plan 073 protocol rationale")
    if not rationale or any(
        not isinstance(name, str)
        or not name
        or not isinstance(text, str)
        or not text.strip()
        for name, text in rationale.items()
    ):
        raise SelectionError("Plan 073 protocol rationale is invalid")
    return dict(protocol)


def validate_freeze(value: Any) -> dict[str, Any]:
    """Validate the protocol freeze that must exist before any formal output."""

    freeze = require_object(value, "Plan 073 selection freeze")
    require_exact_keys(
        freeze,
        {
            "schema",
            "mode",
            "run_id",
            "candidates",
            "dataset",
            "artifacts",
            "runtime",
            "protocol",
            "source",
        },
        "Plan 073 selection freeze",
    )
    run_match = (
        RUN_ID.fullmatch(freeze["run_id"]) if isinstance(freeze["run_id"], str) else None
    )
    if (
        freeze["schema"] != FREEZE_SCHEMA
        or freeze["mode"] not in MODES
        or run_match is None
        or run_match.group(1) != freeze["mode"]
        or list(freeze["candidates"]) != list(CANDIDATES)
    ):
        raise SelectionError("Plan 073 selection freeze identity is invalid")

    dataset = require_object(freeze["dataset"], "Plan 073 dataset binding")
    require_exact_keys(
        dataset,
        {"revision", "root", "manifest_sha256", "unseen_test_sealed_at_freeze"},
        "Plan 073 dataset binding",
    )
    root = dataset["root"]
    if (
        not isinstance(dataset["revision"], str)
        or not dataset["revision"].strip()
        or not isinstance(root, str)
        or not root
        or Path(root).is_absolute()
        or ".." in Path(root).parts
        or dataset["unseen_test_sealed_at_freeze"] is not True
    ):
        raise SelectionError("Plan 073 dataset binding is invalid")
    require_sha256(dataset["manifest_sha256"], "Plan 073 dataset manifest")

    artifacts = require_object(freeze["artifacts"], "Plan 073 artifacts")
    require_exact_keys(artifacts, set(CANDIDATES), "Plan 073 artifacts")
    for candidate in CANDIDATES:
        artifact = require_object(artifacts[candidate], "Plan 073 artifact")
        require_exact_keys(
            artifact,
            {"deployment_artifact_sha256", "lineage"},
            "Plan 073 artifact",
        )
        require_sha256(artifact["deployment_artifact_sha256"], "Plan 073 artifact")
        if not isinstance(artifact["lineage"], str) or not artifact["lineage"].strip():
            raise SelectionError("Plan 073 artifact lineage is invalid")

    validate_runtime(freeze["runtime"])
    _validate_protocol(freeze["protocol"])
    validate_source(freeze["source"])
    return dict(freeze)


def default_runtime() -> dict[str, Any]:
    """The target local deployment runtime, unchanged from Plan 071.

    M3-C2 selects a model and a threshold; it does not re-open the deployment
    route.  Keeping this identical to the qualified configuration is what lets
    the Plan 071 load/RSS/VRAM/latency facts stay comparable.
    """

    return {
        "device": "cuda",
        "dtype": "bfloat16",
        "cpu_threads": 4,
        "deployment_format": "direct-transformers-safetensors-no-conversion-v1",
        "scoring_batch": "single_packet_right_padded_v1",
        "warm_latency_samples": 3,
        "service_limits": {
            "request_bytes": 131072,
            "response_bytes": 16384,
            "max_concurrency": 1,
            "queue_capacity": 8,
            "job_timeout_ms": 25000,
            "io_timeout_ms": 2000,
            "worker_startup_timeout_ms": 20000,
            "worker_io_timeout_ms": 5000,
            "worker_shutdown_timeout_ms": 5000,
            "graceful_shutdown_ms": 3000,
            "force_shutdown_ms": 2000,
            "call_timeout_ms": 30000,
            "startup_timeout_ms": 60000,
            "process_timeout_ms": 60000,
            "representative_cancel_after_ms": 1,
        },
    }


def default_protocol() -> dict[str, Any]:
    """The Plan 073 protocol values, frozen before any formal candidate output.

    The numbers below were chosen from the product contract and the Plan 054
    unfinetuned baseline (balanced accuracy ``0.6875``, ROC AUC ``0.765625``),
    not from any Plan 073 measurement.  They express "good enough to ship a
    publication gate", so an honest ``NO-GO`` is reachable.
    """

    return {
        "method": dict(SELECTION_METHOD),
        "quality_floors": {
            # 21 REWRITE rows in validation: at most 5 may slip through.
            "max_false_pass_rate": 0.25,
            # 34 PASS rows in validation: at most 11 may be blocked.
            "max_false_rewrite_rate": 0.35,
            "min_balanced_accuracy": 0.75,
            "min_roc_auc": 0.80,
            "min_boundary_pair_strict_win_rate": 0.70,
            "max_typed_failures": 0,
        },
        # Identical to the Plan 071 qualification gates: the target deployment
        # runtime is unchanged, so these stay usability gates and are not
        # re-tuned for this task.
        "runtime_gates": {
            "max_load_seconds": 15.0,
            "max_warm_p95_latency_ms": 250.0,
            "max_peak_rss_bytes": 6_000_000_000.0,
            "max_peak_vram_bytes": 4_500_000_000.0,
        },
        "judge": {
            "coverage": JUDGE_COVERAGE,
            "min_reference_agreement_for_gate": 0.70,
            "min_selected_agreement": 0.60,
        },
        "rationale": {
            "error_asymmetry": (
                "False PASS lets an unqualified publication reach Team State, which is the "
                "failure the Critic exists to prevent. False REWRITE only costs a bounded "
                "Producer rewrite round because the product publishes non-blocking after two "
                "rewrites, so its floor is looser and it never outranks False PASS."
            ),
            "threshold_fairness": (
                "All candidates share one search space and one selection rule, but each may "
                "land on a different numeric threshold. Fine-tuning changes score calibration, "
                "so forcing one shared number would report calibration drift as quality."
            ),
            "validation_optimism": (
                "The threshold is fitted on validation and then measured on the same rows, so "
                "validation numbers are optimistic by construction. The single unseen-test "
                "campaign after the lock is what removes that optimism; the same product "
                "floors apply there because they describe shipping readiness, not "
                "non-degradation."
            ),
            "runtime_role": (
                "base, C1 and C3 are the same architecture and size, so latency and memory "
                "cannot meaningfully separate them. They are reported and gated for "
                "usability, never used to rank."
            ),
            "judge_role": (
                "Opus 5 supplies an independent blinded verdict per publication. It never "
                "sees GPT labels, pair direction, split, model identity or model scores, and "
                "it never produces new supervision. It breaks exact ties and, when it broadly "
                "agrees with the frozen reference, guards against selecting a model that both "
                "independent views reject."
            ),
            "slice_reporting": (
                "Every slice is reported with its denominator. No individual slice is a hard "
                "gate: validation slices go down to a single row, so a slice-level gate would "
                "be noise. The boundary-pair rate carries the hard-case axis instead."
            ),
        },
    }
