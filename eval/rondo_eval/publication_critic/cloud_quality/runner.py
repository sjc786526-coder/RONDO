"""Blind Plan 096 scalar runner, Rust adapter, and independent recomputation."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
from typing import Any, ClassVar, Protocol

from ..identity import canonical_json_bytes, sha256_bytes
from ..selection.metrics import (
    PASS,
    REWRITE,
    build_score_only_labeled_rows,
    candidate_metrics,
    quality_gate_failures,
    select_threshold,
)
from ..selection.release import release_sha256, validate_release
from .archive import CloudQualityArchive
from .contract import (
    BUDGET_CAP_RMB,
    FORMAL_INCOMPLETE,
    HEADROOM_RULE,
    QUALITY_FLOORS,
    REQUESTED_MODEL,
    RESULT_SCHEMA,
    SCORES_SCHEMA,
    TERMINALS,
    TRACKED_RESULT_SCHEMA,
    VALIDATION_COUNTS,
    VALIDATION_RELEASE_SHA256,
    CloudQualityError,
    freeze_sha256,
    require_exact_candidate_order,
    validate_attempt,
    validate_call_record,
    validate_freeze,
    validate_scores_document,
)
from .cost import (
    attempts_cost_rmb,
    decimal_text,
    require_next_logical_call_budget,
    scan_plan_cost_rmb,
)


class ScalarEvaluator(Protocol):
    def evaluate(self, candidate_id: str, packet: Mapping[str, Any]) -> Mapping[str, Any]:
        """Return one body-free success/failure outcome for one bounded packet."""


@dataclass(frozen=True)
class RustSubprocessEvaluator:
    """One-shot adapter; stdin is the packet JSON and never supervision metadata."""

    executable: Path
    arguments: tuple[str, ...]
    credential_env: Mapping[str, str]
    timeout_seconds: float

    _SYSTEM_ENV: ClassVar[tuple[str, ...]] = (
        "PATH",
        "LANG",
        "LC_ALL",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    )

    def _environment(self) -> dict[str, str]:
        environment = {
            name: os.environ[name]
            for name in self._SYSTEM_ENV
            if name in os.environ and os.environ[name]
        }
        for name, value in self.credential_env.items():
            if not isinstance(name, str) or not name or not isinstance(value, str) or not value:
                raise CloudQualityError("subprocess_credential_invalid")
            environment[name] = value
        return environment

    def evaluate(self, candidate_id: str, packet: Mapping[str, Any]) -> Mapping[str, Any]:
        del candidate_id  # Identity remains local; the provider subprocess sees only the packet.
        if (
            self.executable.is_symlink()
            or not self.executable.is_file()
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise CloudQualityError("subprocess_configuration_invalid")
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                [str(self.executable), *self.arguments],
                input=canonical_json_bytes(dict(packet)) + b"\n",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
                env=self._environment(),
            )
        except subprocess.TimeoutExpired as exc:
            # A timed-out child may already have emitted the body-free scorer marker.
            # Without one, count one possible in-flight HTTP attempt conservatively.
            return _adapter_failure(
                "TimeoutExpired",
                "subprocess_timeout",
                "retryable_infrastructure",
                time.perf_counter() - started,
                attempts=max(1, _stderr_attempts(exc.stderr)),
            )
        if completed.returncode != 0 or len(completed.stdout) > 64 * 1024:
            return _adapter_failure(
                "SubprocessError",
                "subprocess_failed",
                "implementation_invalid",
                time.perf_counter() - started,
                attempts=max(1, _stderr_attempts(completed.stderr)),
            )
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError:
            return _adapter_failure(
                "ResponseParseError",
                "subprocess_output_invalid",
                "implementation_invalid",
                time.perf_counter() - started,
                attempts=max(1, _stderr_attempts(completed.stderr)),
            )
        if not isinstance(value, Mapping):
            raise CloudQualityError("subprocess_output_invalid")
        return _normalize_rust_observation(value)


def _adapter_failure(
    kind: str,
    code: str,
    disposition: str,
    elapsed_seconds: float,
    *,
    attempts: int,
) -> dict[str, Any]:
    return {
        "status": "failure",
        "score": None,
        "requested_model": REQUESTED_MODEL,
        "effective_model": REQUESTED_MODEL,
        "attempts": [
            {
                "attempt": index,
                "outcome": "failure",
                "usage": None,
                "failure_kind": kind,
                "failure_code": code,
            }
            for index in range(1, attempts + 1)
        ],
        "elapsed_ms": elapsed_seconds * 1000.0,
        "failure_kind": kind,
        "failure_code": code,
        "failure_disposition": disposition,
    }


_TERMINAL_ATTEMPT_MARKER = re.compile(
    rb"publication_critic_cloud_(?:call|failed) attempts=([0-9]+)(?:\s|$)"
)
_STARTED_ATTEMPT_MARKER = re.compile(
    rb"publication_critic_cloud_attempt attempt=([0-9]+)(?:\s|$)"
)


def _stderr_attempts(stderr: bytes | str | None) -> int:
    if stderr is None:
        return 0
    body = stderr.encode("utf-8", errors="ignore") if isinstance(stderr, str) else stderr
    observed = [
        int(match.group(1))
        for pattern in (_TERMINAL_ATTEMPT_MARKER, _STARTED_ATTEMPT_MARKER)
        for match in pattern.finditer(body)
    ]
    return max(observed, default=0)


def _normalize_usage(value: Any) -> dict[str, int | None] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise CloudQualityError("subprocess_usage_invalid")
    prompt = value.get("prompt_tokens")
    completion = value.get("completion_tokens")
    # A partial provider usage without the two price-bearing totals is not
    # reliably chargeable and therefore falls back to 1 RMB for that attempt.
    if (
        type(prompt) is not int
        or prompt < 0
        or type(completion) is not int
        or completion < 0
    ):
        return None
    return {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cache_hit_tokens": value.get("prompt_cache_hit_tokens"),
        "cache_miss_tokens": value.get("prompt_cache_miss_tokens"),
    }


def _normalize_rust_observation(value: Mapping[str, Any]) -> dict[str, Any]:
    required = {
        "requested_model",
        "served_model",
        "score",
        "attempts",
        "elapsed_ms",
        "usage",
        "outcome",
    }
    if set(value) != required:
        raise CloudQualityError("subprocess_observation_fields_invalid")
    requested = value.get("requested_model")
    served = value.get("served_model")
    count = value.get("attempts")
    elapsed = value.get("elapsed_ms")
    outcome = value.get("outcome")
    if (
        requested != REQUESTED_MODEL
        or served is not None and not isinstance(served, str)
        or type(count) is not int
        or not 1 <= count <= 255
        or type(elapsed) is not int
        or elapsed < 0
        or not isinstance(outcome, Mapping)
    ):
        raise CloudQualityError("subprocess_observation_invalid")
    usage = _normalize_usage(value.get("usage"))
    outcome_type = outcome.get("type")
    success = outcome_type == "success"
    if success:
        if set(outcome) != {"type"}:
            raise CloudQualityError("subprocess_success_invalid")
        failure_kind = failure_code = failure_disposition = None
        final_attempt_outcome = "success"
    elif outcome_type == "failure" and set(outcome) == {"type", "kind", "http_status"}:
        kind = outcome.get("kind")
        status = outcome.get("http_status")
        if not isinstance(kind, str) or status is not None and type(status) is not int:
            raise CloudQualityError("subprocess_failure_invalid")
        failure_kind = "CloudEvaluationFailure"
        failure_code = f"{kind}:{status}" if status is not None else kind
        if kind == "provider_transport" or (
            kind == "provider_http_status"
            and status in {408, 425, 429, 500, 502, 503}
        ):
            failure_disposition = "retryable_infrastructure"
        elif kind == "provider_http_status":
            failure_disposition = "permanent_failure"
        else:
            failure_disposition = "effective_model_failure"
        final_attempt_outcome = "failure"
    else:
        raise CloudQualityError("subprocess_outcome_invalid")
    attempts = [
        {
            "attempt": index,
            "outcome": "transient_failure" if index < count else final_attempt_outcome,
            "usage": usage if index == count else None,
            "failure_kind": (
                "ProviderTransientFailure"
                if index < count
                else failure_kind
            ),
            "failure_code": "retryable_attempt" if index < count else failure_code,
        }
        for index in range(1, count + 1)
    ]
    return {
        "status": "success" if success else "failure",
        "score": value.get("score") if success else None,
        "requested_model": requested,
        "effective_model": served or requested,
        "attempts": attempts,
        "elapsed_ms": float(elapsed),
        "failure_kind": failure_kind,
        "failure_code": failure_code,
        "failure_disposition": failure_disposition,
    }


def _call_record(
    freeze: Mapping[str, Any], candidate_id: str, outcome_value: Any
) -> dict[str, Any]:
    if not isinstance(outcome_value, Mapping):
        raise CloudQualityError("evaluator_outcome_invalid")
    required = {
        "status",
        "score",
        "requested_model",
        "effective_model",
        "attempts",
        "elapsed_ms",
        "failure_kind",
        "failure_code",
        "failure_disposition",
    }
    if set(outcome_value) != required:
        raise CloudQualityError("evaluator_outcome_fields_invalid")
    attempts_value = outcome_value.get("attempts")
    if not isinstance(attempts_value, list) or not attempts_value:
        raise CloudQualityError("evaluator_attempts_invalid")
    attempts = [validate_attempt(item) for item in attempts_value]
    max_attempts = freeze["retry"]["max_attempts"]
    if len(attempts) > max_attempts:
        raise CloudQualityError("evaluator_attempt_limit_exceeded")
    record = {
        "candidate_id": candidate_id,
        "status": outcome_value["status"],
        "score": outcome_value["score"],
        "requested_model": outcome_value["requested_model"],
        "effective_model": outcome_value["effective_model"],
        "freeze_sha256": freeze_sha256(freeze),
        "scorer_identity": freeze["scorer"]["scorer_identity"],
        "attempts": attempts,
        "conservative_cost_rmb": decimal_text(attempts_cost_rmb(attempts)),
        "elapsed_ms": outcome_value["elapsed_ms"],
        "failure_kind": outcome_value["failure_kind"],
        "failure_code": outcome_value["failure_code"],
        "failure_disposition": outcome_value["failure_disposition"],
    }
    return validate_call_record(record)


def score_items(
    freeze_value: Any,
    items: Sequence[Mapping[str, Any]],
    *,
    archive: CloudQualityArchive,
    evaluator: ScalarEvaluator,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Score blind items; formal stops at its first failure and never resumes rows."""

    freeze = validate_freeze(freeze_value)
    if archive.mode != freeze["namespace"]["mode"]:
        raise CloudQualityError("runner_archive_mode_mismatch")
    expected_freeze = freeze_sha256(freeze)
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, Mapping) or set(item) != {"candidate_id", "packet"}:
            raise CloudQualityError("runner_item_fields_invalid")
        candidate_id = item.get("candidate_id")
        packet = item.get("packet")
        if (
            not isinstance(candidate_id, str)
            or not candidate_id
            or candidate_id in seen
            or not isinstance(packet, Mapping)
        ):
            raise CloudQualityError("runner_item_invalid")
        seen.add(candidate_id)
        prior = archive.load_success(
            candidate_id, expected_freeze_sha256=expected_freeze
        )
        if prior is not None:
            if archive.mode != "commissioning":
                raise CloudQualityError("formal_namespace_not_empty")
            rows.append(prior)
            continue
        require_next_logical_call_budget(
            archive.runs_root, max_attempts=freeze["retry"]["max_attempts"]
        )
        outcome = evaluator.evaluate(candidate_id, packet)
        record = _call_record(freeze, candidate_id, outcome)
        archive.write_call(candidate_id, record)
        if scan_plan_cost_rmb(archive.runs_root) > BUDGET_CAP_RMB:
            raise CloudQualityError("budget_cap_exceeded")
        if record["status"] == "success":
            rows.append(record)
        else:
            failures.append(record)
            if archive.mode == "formal":
                break
    return rows, failures


def build_scores_document(
    freeze_value: Any,
    rows: Sequence[Mapping[str, Any]],
    failures: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    freeze = validate_freeze(freeze_value)
    return validate_scores_document(
        {
            "schema": SCORES_SCHEMA,
            "freeze_sha256": freeze_sha256(freeze),
            "release_sha256": VALIDATION_RELEASE_SHA256,
            "rows": [dict(row) for row in rows],
            "failures": [dict(row) for row in failures],
        },
        freeze,
    )


def _validate_exact_release(value: Any) -> dict[str, Any]:
    try:
        release = validate_release(value)
    except Exception as exc:  # noqa: BLE001 - normalize the shared release contract
        raise CloudQualityError("validation_release_invalid") from exc
    if (
        release["split"] != "validation"
        or release["dataset_revision"] != "v8"
        or release_sha256(release) != VALIDATION_RELEASE_SHA256
        or len(release["items"]) != VALIDATION_COUNTS["candidate_count"]
        or sum(row["binary_label"] == PASS for row in release["supervision"])
        != VALIDATION_COUNTS["pass_count"]
        or sum(row["binary_label"] == REWRITE for row in release["supervision"])
        != VALIDATION_COUNTS["rewrite_count"]
        or sum(row["kind"] == "boundary" for row in release["pairs"])
        != VALIDATION_COUNTS["boundary_pair_count"]
        or sum(row["kind"] == "within_pass" for row in release["pairs"])
        != VALIDATION_COUNTS["within_pass_pair_count"]
    ):
        raise CloudQualityError("validation_release_identity_mismatch")
    return release


def _usage_summary(records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    prompt = completion = hit = miss = attempts = 0
    cost = Decimal("0")
    for record in records:
        attempts += len(record["attempts"])
        cost += Decimal(str(record["conservative_cost_rmb"]))
        for attempt in record["attempts"]:
            usage = attempt["usage"]
            if usage is None:
                continue
            prompt += usage["prompt_tokens"]
            completion += usage["completion_tokens"]
            hit += usage["cache_hit_tokens"] or 0
            miss += usage["cache_miss_tokens"] or 0
    return {
        "http_attempt_count": attempts,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "cache_hit_tokens_reported": hit,
        "cache_miss_tokens_reported": miss,
        "conservative_cost_rmb": decimal_text(cost),
    }


def _terminal(gate_failures: Sequence[str], metrics: Mapping[str, Any]) -> str:
    if not gate_failures:
        return TERMINALS[0]
    auc_pass = metrics["roc_auc"] >= QUALITY_FLOORS["min_roc_auc"]
    boundary_pass = (
        metrics["boundary_pairs"]["strict_win_rate"]
        >= QUALITY_FLOORS["min_boundary_pair_strict_win_rate"]
    )
    if auc_pass and boundary_pass:
        return TERMINALS[1]
    if not auc_pass and not boundary_pass:
        return TERMINALS[2]
    return TERMINALS[3]


def recompute(freeze_value: Any, release_value: Any, scores_value: Any) -> dict[str, Any]:
    """Reconstruct completeness, curve, gates, terminal, and disagreements."""

    freeze = validate_freeze(freeze_value)
    if freeze["namespace"]["mode"] != "formal":
        raise CloudQualityError("recompute_requires_formal_freeze")
    release = _validate_exact_release(release_value)
    scores = validate_scores_document(scores_value, freeze)
    expected_ids = [str(item["candidate_id"]) for item in release["items"]]
    row_ids = [str(row["candidate_id"]) for row in scores["rows"]]
    failure_ids = [str(row["candidate_id"]) for row in scores["failures"]]
    observed = [*row_ids, *failure_ids]
    require_exact_candidate_order(observed, expected_ids, allow_prefix=True)
    complete = not failure_ids and row_ids == expected_ids
    records = [*scores["rows"], *scores["failures"]]
    search: dict[str, Any] | None = None
    metrics: dict[str, Any] | None = None
    gate_failures: list[str]
    disagreements: list[dict[str, Any]] = []
    if complete:
        labeled = build_score_only_labeled_rows(
            release,
            {
                row["candidate_id"]: {"score": float(row["score"])}
                for row in scores["rows"]
            },
        )
        search = select_threshold(labeled, QUALITY_FLOORS)
        metrics = candidate_metrics(release, labeled, search["threshold"])
        gate_failures = quality_gate_failures(search, metrics, 0, QUALITY_FLOORS)
        terminal = _terminal(gate_failures, metrics)
        disagreements = [
            {
                "candidate_id": row["candidate_id"],
                "label": row["label"],
                "score": row["score"],
                "predicted": row["predicted"],
                "margin_to_threshold": row["margin_to_threshold"],
                "error_type": (
                    "false_pass" if row["label"] == REWRITE else "false_rewrite"
                ),
            }
            for row in metrics["rows"]
            if row["label"] != row["predicted"]
        ]
    else:
        gate_failures = ["formal_score_cohort_incomplete"]
        terminal = FORMAL_INCOMPLETE
    return {
        "schema": RESULT_SCHEMA,
        "freeze_sha256": freeze_sha256(freeze),
        "release_sha256": VALIDATION_RELEASE_SHA256,
        "scores_sha256": sha256_bytes(canonical_json_bytes(scores)),
        "complete": complete,
        "terminal": terminal,
        "scored_count": len(scores["rows"]),
        "typed_failure_count": len(scores["failures"]),
        "gate_failures": gate_failures,
        "threshold_search": search,
        "metrics": metrics,
        "headroom_rule": HEADROOM_RULE,
        "disagreements": disagreements,
        "usage_and_cost": _usage_summary(records),
    }


def run_formal(
    freeze_value: Any,
    release_value: Any,
    *,
    runs_root: Path,
    evaluator: ScalarEvaluator,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run one new formal namespace; join supervision only after scoring closes."""

    freeze = validate_freeze(freeze_value)
    if freeze["namespace"]["mode"] != "formal":
        raise CloudQualityError("formal_runner_mode_invalid")
    release = _validate_exact_release(release_value)
    archive = CloudQualityArchive(
        runs_root, freeze["namespace"]["run_id"], "formal"
    ).create(freeze)
    # The evaluator receives this narrow projection, never release supervision or pairs.
    items = [
        {"candidate_id": item["candidate_id"], "packet": item["packet"]}
        for item in release["items"]
    ]
    rows, failures = score_items(freeze, items, archive=archive, evaluator=evaluator)
    scores = build_scores_document(freeze, rows, failures)
    archive.bind_json("scores.json", scores)
    result = recompute(freeze, release, scores)
    archive.bind_json("result.json", result)
    if result["complete"]:
        archive.claim_formal_result(freeze, result)
    return scores, result


def run_commissioning(
    freeze_value: Any,
    items: Sequence[Mapping[str, Any]],
    *,
    runs_root: Path,
    evaluator: ScalarEvaluator,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Run/resume a 55-item synthetic commissioning batch and bind its evidence."""

    freeze = validate_freeze(freeze_value)
    if freeze["namespace"]["mode"] != "commissioning" or len(items) != 55:
        raise CloudQualityError("commissioning_batch_invalid")
    archive = CloudQualityArchive(
        runs_root, freeze["namespace"]["run_id"], "commissioning"
    ).create(freeze)
    rows, failures = score_items(freeze, items, archive=archive, evaluator=evaluator)
    complete = len(rows) == 55 and not failures
    result = {
        "schema": "rondo-publication-critic-plan096-commissioning-result-v1",
        "freeze_sha256": freeze_sha256(freeze),
        "input_sha256": sha256_bytes(canonical_json_bytes(list(items))),
        "scored_count": len(rows),
        "typed_failure_count": len(failures),
        "complete": complete,
        "usage_and_cost": _usage_summary([*rows, *failures]),
    }
    if not complete:
        raise CloudQualityError("commissioning_incomplete")
    scores_body = {
        "schema": "rondo-publication-critic-plan096-commissioning-scores-v1",
        "freeze_sha256": freeze_sha256(freeze),
        "rows": rows,
    }
    binding = {
        "run_id": freeze["namespace"]["run_id"],
        "input_sha256": result["input_sha256"],
        "scores_sha256": sha256_bytes(canonical_json_bytes(scores_body)),
        "result_sha256": sha256_bytes(canonical_json_bytes(result)),
    }
    archive.bind_json("commissioning-scores.json", scores_body)
    archive.bind_json("commissioning-result.json", result)
    archive.bind_json("commissioning-binding.json", binding)
    return result, binding


def tracked_projection(
    freeze_value: Any,
    result_value: Any,
    *,
    historical: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Body-free tracked projection with all material needed to recompute scores."""

    freeze = validate_freeze(freeze_value)
    if not isinstance(result_value, Mapping) or result_value.get("schema") != RESULT_SCHEMA:
        raise CloudQualityError("tracked_result_invalid")
    if (
        result_value.get("complete") is not True
        or result_value.get("terminal") not in TERMINALS
        or result_value.get("freeze_sha256") != freeze_sha256(freeze)
    ):
        raise CloudQualityError("tracked_result_incomplete")
    metrics = result_value.get("metrics")
    if not isinstance(metrics, Mapping) or len(metrics.get("rows", [])) != 55:
        raise CloudQualityError("tracked_result_rows_invalid")
    return {
        "schema": TRACKED_RESULT_SCHEMA,
        "terminal": result_value["terminal"],
        "complete": True,
        "freeze": freeze,
        "identity": {
            "freeze_sha256": result_value["freeze_sha256"],
            "release_sha256": result_value["release_sha256"],
            "scores_sha256": result_value["scores_sha256"],
            "requested_model": REQUESTED_MODEL,
        },
        "cohort": {
            **VALIDATION_COUNTS,
            "typed_failure_count": 0,
        },
        "quality_floors": QUALITY_FLOORS,
        "threshold_search": result_value["threshold_search"],
        "metrics": {
            name: metrics[name]
            for name in (
                "overall",
                "roc_auc",
                "boundary_pairs",
                "within_pass_pairs",
                "score_distribution",
                "errors",
            )
        },
        "rows": [
            {
                "candidate_id": row["candidate_id"],
                "label": row["label"],
                "score": row["score"],
            }
            for row in metrics["rows"]
        ],
        "disagreements": list(result_value["disagreements"]),
        "usage_and_cost": dict(result_value["usage_and_cost"]),
        "historical_comparison": dict(historical) if historical is not None else None,
        "comparison_note": (
            "Same release/labels/pairs/curve/gates only; raw logits, absolute thresholds, "
            "calibration, tokenizer/window, templates, latency, and resources are not compared."
        ),
    }
