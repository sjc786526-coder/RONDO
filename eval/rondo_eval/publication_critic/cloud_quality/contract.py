"""Frozen identities and schemas for Plan 096 cloud-scorer qualification."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
import math
import re
from typing import Any

from ..identity import canonical_json_bytes, sha256_bytes
from ..selection.contract import SELECTION_METHOD, publication_quality_floors


FREEZE_SCHEMA = "rondo-publication-critic-plan096-cloud-quality-freeze-v1"
SCORES_SCHEMA = "rondo-publication-critic-plan096-cloud-scores-v1"
RESULT_SCHEMA = "rondo-publication-critic-plan096-cloud-quality-result-v1"
TRACKED_RESULT_SCHEMA = "rondo-publication-critic-plan096-cloud-quality-summary-v1"
AUTHORITY_SCHEMA = "rondo-publication-critic-plan096-formal-authority-v1"

REQUESTED_MODEL = "deepseek-v4-flash"
V8_MANIFEST_CONTENT_SHA256 = (
    "a9a31a61e0a1e070ee8d076dd313b7efabb5e01ffa42773a841b123a2686cb98"
)
V8_MANIFEST_FILE_SHA256 = (
    "70cbbbd1b754227b3c84f9117c1e74ee630713ae12d7041e48522bd751ea5661"
)
PLAN066_BUNDLE_MANIFEST_SHA256 = (
    "2970c693fa32d1118d3b8e949a04231970bf96dfc27f7c7d14a22f98a4ed2252"
)
VALIDATION_RELEASE_SHA256 = (
    "757dd624c3d47f87dd5683d24f9f1753b1dbbffb42fdeff567c9e3e5e0b71a91"
)
VALIDATION_COUNTS = {
    "candidate_count": 55,
    "pass_count": 34,
    "rewrite_count": 21,
    "boundary_pair_count": 19,
    "within_pass_pair_count": 7,
    "unseen_test_rows_available": 0,
}
QUALITY_FLOORS = publication_quality_floors()

PRICE_RATES_RMB_PER_MILLION = {
    "cache_hit_input": Decimal("0.05"),
    "cache_miss_input": Decimal("1.5"),
    "output": Decimal("4.5"),
}
UNKNOWN_ATTEMPT_FALLBACK_RMB = Decimal("1")
BUDGET_CAP_RMB = Decimal("30")

TERMINALS = (
    "CLOUD_SCORER_QUALIFIED",
    "CLOUD_SCORER_NOT_QUALIFIED_HEADROOM_HIGH",
    "CLOUD_SCORER_TASK_HEADROOM_LOW",
    "CLOUD_SCORER_RESULT_INCONCLUSIVE",
)
FORMAL_INCOMPLETE = "FORMAL_INCOMPLETE"
HEADROOM_RULE = {
    "qualified": "all_quality_gates_pass_v1",
    "high": "not_qualified_and_auc_and_boundary_pass_v1",
    "low": "not_qualified_and_auc_and_boundary_fail_v1",
    "inconclusive": "not_qualified_and_exactly_one_of_auc_or_boundary_passes_v1",
}

FROZEN_PROVIDER = {
    "provider_identity": "deepseek-official",
    "api_shape": "chat-completions-json-object-v1",
    "endpoint_identity": "https://api.deepseek.com/chat/completions",
    "requested_model": REQUESTED_MODEL,
    "documented_model_version": "DeepSeek-V4-Flash-0731",
    "serving_revision": "provider-managed-unverifiable",
    "effective_model_policy": "exact-requested-and-served-model-v1",
    "response_model_policy": "required-exact-echo-reject-drift-v1",
    "thinking": "request-omitted-provider-default-documented-enabled",
    "reasoning_effort": "request-omitted-provider-default-documented-high",
}
FROZEN_SCORER = {
    "descriptor": "eval/locks/publication-critic-plan096-cloud-descriptor-v1.json",
    "scorer_identity": "rondo-cloud-reference-deepseek-v4-flash@v1",
    "template_identity": "rondo-publication-cloud-template@v1",
    "projection_identity": "rondo-cloud-json-quality-scalar@v1",
    "domain": "finite-unit-interval-higher-is-better",
    "strict_parser": "single-json-quality-number-finish-stop-v1",
}
FROZEN_REQUEST = {
    "temperature": 0.0,
    "top_p": None,
    "max_completion_tokens": 4096,
    "seed": None,
    "stream": False,
    "response_format": "json_object",
}
FROZEN_RETRY = {
    "max_attempts": 2,
    "retryable_http_statuses": [408, 425, 429, 500, 502, 503],
    "retryable_failure_kinds": ["provider_transport"],
    "backoff_seconds": [1.0],
    "connect_timeout_seconds": 10.0,
    "request_timeout_seconds": 60.0,
}

_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_GIT_COMMIT = re.compile(r"[0-9a-f]{40}\Z")
RUN_ID = re.compile(
    r"plan096-(commissioning|formal)-[0-9]{8}T[0-9]{6}Z-[a-z0-9][a-z0-9-]{0,47}\Z"
)


class CloudQualityError(RuntimeError):
    """Stable body-free Plan 096 validation, run, or result error."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def freeze_sha256(value: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(value)))


def require_sha256(value: Any, code: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise CloudQualityError(code)
    return value


def require_text(value: Any, code: str) -> str:
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CloudQualityError(code)
    return value


def require_decimal(value: Any, code: str, *, minimum: Decimal = Decimal("0")) -> Decimal:
    if isinstance(value, bool):
        raise CloudQualityError(code)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise CloudQualityError(code) from exc
    if not number.is_finite() or number < minimum:
        raise CloudQualityError(code)
    return number


def require_count(value: Any, code: str) -> int:
    if type(value) is not int or value < 0:
        raise CloudQualityError(code)
    return value


def require_exact(value: Any, keys: set[str], code: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise CloudQualityError(code)
    return value


def _validate_source(value: Any) -> dict[str, Any]:
    source = require_exact(
        value,
        {
            "git_commit",
            "tracked_source_clean",
            "tracked_contract_sha256",
            "environment_lock_sha256",
            "scalar_executable_sha256",
        },
        "freeze_source_fields_invalid",
    )
    if (
        not isinstance(source.get("git_commit"), str)
        or _GIT_COMMIT.fullmatch(source["git_commit"]) is None
        or source.get("tracked_source_clean") is not True
    ):
        raise CloudQualityError("freeze_source_identity_invalid")
    for name in (
        "tracked_contract_sha256",
        "environment_lock_sha256",
        "scalar_executable_sha256",
    ):
        require_sha256(source.get(name), f"freeze_source_{name}_invalid")
    return dict(source)


def _validate_provider(value: Any) -> dict[str, Any]:
    provider = require_exact(
        value,
        {
            "provider_identity",
            "api_shape",
            "endpoint_identity",
            "requested_model",
            "documented_model_version",
            "serving_revision",
            "effective_model_policy",
            "response_model_policy",
            "thinking",
            "reasoning_effort",
        },
        "freeze_provider_fields_invalid",
    )
    for name in (
        "provider_identity",
        "api_shape",
        "endpoint_identity",
        "effective_model_policy",
        "response_model_policy",
        "thinking",
        "reasoning_effort",
    ):
        require_text(provider.get(name), f"freeze_provider_{name}_invalid")
    if provider.get("requested_model") != REQUESTED_MODEL:
        raise CloudQualityError("freeze_requested_model_invalid")
    if dict(provider) != FROZEN_PROVIDER:
        raise CloudQualityError("freeze_provider_identity_invalid")
    return dict(provider)


def _validate_scorer(value: Any) -> dict[str, Any]:
    scorer = require_exact(
        value,
        {
            "descriptor",
            "descriptor_sha256",
            "scorer_identity",
            "template_identity",
            "projection_identity",
            "domain",
            "strict_parser",
        },
        "freeze_scorer_fields_invalid",
    )
    for name in (
        "descriptor",
        "scorer_identity",
        "template_identity",
        "projection_identity",
        "domain",
        "strict_parser",
    ):
        require_text(scorer.get(name), f"freeze_scorer_{name}_invalid")
    require_sha256(scorer.get("descriptor_sha256"), "freeze_descriptor_sha256_invalid")
    if {name: scorer[name] for name in FROZEN_SCORER} != FROZEN_SCORER:
        raise CloudQualityError("freeze_scorer_identity_invalid")
    return dict(scorer)


def _validate_request(value: Any) -> dict[str, Any]:
    request = require_exact(
        value,
        {
            "temperature",
            "top_p",
            "max_completion_tokens",
            "seed",
            "stream",
            "response_format",
        },
        "freeze_request_fields_invalid",
    )
    if dict(request) != FROZEN_REQUEST:
        raise CloudQualityError("freeze_request_identity_invalid")
    return dict(request)


def _validate_retry(value: Any) -> dict[str, Any]:
    retry = require_exact(
        value,
        {
            "max_attempts",
            "retryable_http_statuses",
            "retryable_failure_kinds",
            "backoff_seconds",
            "connect_timeout_seconds",
            "request_timeout_seconds",
        },
        "freeze_retry_fields_invalid",
    )
    if dict(retry) != FROZEN_RETRY:
        raise CloudQualityError("freeze_retry_identity_invalid")
    return dict(retry)


def _validate_validation(value: Any) -> dict[str, Any]:
    validation = require_exact(
        value,
        {
            "dataset_revision",
            "manifest_content_sha256",
            "manifest_file_sha256",
            "bundle_manifest_sha256",
            "release_sha256",
            *VALIDATION_COUNTS,
        },
        "freeze_validation_fields_invalid",
    )
    expected = {
        "dataset_revision": "v8",
        "manifest_content_sha256": V8_MANIFEST_CONTENT_SHA256,
        "manifest_file_sha256": V8_MANIFEST_FILE_SHA256,
        "bundle_manifest_sha256": PLAN066_BUNDLE_MANIFEST_SHA256,
        "release_sha256": VALIDATION_RELEASE_SHA256,
        **VALIDATION_COUNTS,
    }
    if dict(validation) != expected:
        raise CloudQualityError("freeze_validation_identity_invalid")
    return dict(validation)


def _validate_metrics(value: Any) -> dict[str, Any]:
    metrics = require_exact(
        value,
        {"threshold_search", "threshold_rule", "quality_floors", "headroom_rule"},
        "freeze_metrics_fields_invalid",
    )
    if (
        metrics.get("threshold_search") != SELECTION_METHOD["threshold_search"]
        or metrics.get("threshold_rule") != SELECTION_METHOD["threshold_rule"]
        or metrics.get("quality_floors") != QUALITY_FLOORS
        or metrics.get("headroom_rule") != HEADROOM_RULE
    ):
        raise CloudQualityError("freeze_metrics_identity_invalid")
    return dict(metrics)


def _validate_cost(value: Any) -> dict[str, Any]:
    cost = require_exact(
        value,
        {
            "currency",
            "price_source_url",
            "price_observed_at",
            "rates_per_million_tokens",
            "price_tier",
            "price_tier_rule",
            "unknown_attempt_fallback_rmb",
            "budget_cap_rmb",
        },
        "freeze_cost_fields_invalid",
    )
    if cost.get("currency") != "CNY":
        raise CloudQualityError("freeze_cost_currency_invalid")
    require_text(cost.get("price_source_url"), "freeze_price_source_invalid")
    require_text(cost.get("price_observed_at"), "freeze_price_observed_at_invalid")
    if (
        cost.get("price_tier") != "off_peak"
        or cost.get("price_tier_rule")
        != "beijing_weekdays_09:00-12:00_and_14:00-18:00_peak_otherwise_off_peak"
    ):
        raise CloudQualityError("freeze_price_tier_invalid")
    rates = require_exact(
        cost.get("rates_per_million_tokens"),
        set(PRICE_RATES_RMB_PER_MILLION),
        "freeze_price_rates_invalid",
    )
    if any(
        require_decimal(rates.get(name), "freeze_price_rates_invalid") != expected
        for name, expected in PRICE_RATES_RMB_PER_MILLION.items()
    ):
        raise CloudQualityError("freeze_price_rates_invalid")
    if (
        require_decimal(
            cost.get("unknown_attempt_fallback_rmb"), "freeze_cost_fallback_invalid"
        )
        != UNKNOWN_ATTEMPT_FALLBACK_RMB
        or require_decimal(cost.get("budget_cap_rmb"), "freeze_cost_cap_invalid")
        != BUDGET_CAP_RMB
    ):
        raise CloudQualityError("freeze_cost_identity_invalid")
    return dict(cost)


def _validate_commissioning(value: Any) -> dict[str, Any]:
    binding = require_exact(
        value,
        {"run_id", "input_sha256", "scores_sha256", "result_sha256"},
        "freeze_commissioning_fields_invalid",
    )
    match = (
        RUN_ID.fullmatch(binding.get("run_id", ""))
        if isinstance(binding.get("run_id"), str)
        else None
    )
    if match is None or match.group(1) != "commissioning":
        raise CloudQualityError("freeze_commissioning_run_id_invalid")
    for name in ("input_sha256", "scores_sha256", "result_sha256"):
        require_sha256(binding.get(name), f"freeze_commissioning_{name}_invalid")
    return dict(binding)


def _validate_namespace(value: Any) -> dict[str, Any]:
    namespace = require_exact(
        value,
        {
            "run_id",
            "mode",
            "runs_root_identity",
            "formal_empty_required",
            "write_once",
        },
        "freeze_namespace_fields_invalid",
    )
    match = (
        RUN_ID.fullmatch(namespace.get("run_id", ""))
        if isinstance(namespace.get("run_id"), str)
        else None
    )
    mode = namespace.get("mode")
    if (
        match is None
        or mode not in {"commissioning", "formal"}
        or match.group(1) != mode
        or namespace.get("formal_empty_required") is not (mode == "formal")
        or namespace.get("write_once") != "write-once-namespace-v1"
    ):
        raise CloudQualityError("freeze_namespace_identity_invalid")
    require_text(namespace.get("runs_root_identity"), "freeze_runs_root_identity_invalid")
    return dict(namespace)


def validate_freeze(value: Any) -> dict[str, Any]:
    freeze = require_exact(
        value,
        {
            "schema",
            "source",
            "provider",
            "scorer",
            "request",
            "retry",
            "validation",
            "metrics",
            "cost",
            "commissioning",
            "namespace",
        },
        "freeze_fields_invalid",
    )
    if freeze.get("schema") != FREEZE_SCHEMA:
        raise CloudQualityError("freeze_schema_invalid")
    _validate_source(freeze["source"])
    _validate_provider(freeze["provider"])
    _validate_scorer(freeze["scorer"])
    _validate_request(freeze["request"])
    _validate_retry(freeze["retry"])
    _validate_validation(freeze["validation"])
    _validate_metrics(freeze["metrics"])
    _validate_cost(freeze["cost"])
    namespace = _validate_namespace(freeze["namespace"])
    if namespace["mode"] == "commissioning":
        if freeze["commissioning"] is not None:
            raise CloudQualityError("commissioning_freeze_binding_invalid")
    else:
        _validate_commissioning(freeze["commissioning"])
    return dict(freeze)


def build_freeze(
    *,
    source: Mapping[str, Any],
    descriptor_sha256: str,
    price_observed_at: str,
    commissioning: Mapping[str, Any] | None,
    run_id: str,
    mode: str,
) -> dict[str, Any]:
    """Build the exact Plan 096 freeze around its run-specific source and namespace."""

    return validate_freeze(
        {
            "schema": FREEZE_SCHEMA,
            "source": dict(source),
            "provider": dict(FROZEN_PROVIDER),
            "scorer": {
                **FROZEN_SCORER,
                "descriptor_sha256": descriptor_sha256,
            },
            "request": dict(FROZEN_REQUEST),
            "retry": {
                **FROZEN_RETRY,
                "retryable_http_statuses": list(
                    FROZEN_RETRY["retryable_http_statuses"]
                ),
                "retryable_failure_kinds": list(
                    FROZEN_RETRY["retryable_failure_kinds"]
                ),
                "backoff_seconds": list(FROZEN_RETRY["backoff_seconds"]),
            },
            "validation": {
                "dataset_revision": "v8",
                "manifest_content_sha256": V8_MANIFEST_CONTENT_SHA256,
                "manifest_file_sha256": V8_MANIFEST_FILE_SHA256,
                "bundle_manifest_sha256": PLAN066_BUNDLE_MANIFEST_SHA256,
                "release_sha256": VALIDATION_RELEASE_SHA256,
                **VALIDATION_COUNTS,
            },
            "metrics": {
                "threshold_search": SELECTION_METHOD["threshold_search"],
                "threshold_rule": SELECTION_METHOD["threshold_rule"],
                "quality_floors": dict(QUALITY_FLOORS),
                "headroom_rule": dict(HEADROOM_RULE),
            },
            "cost": {
                "currency": "CNY",
                "price_source_url": (
                    "https://api-docs.deepseek.com/zh-cn/quick_start/pricing/"
                ),
                "price_observed_at": price_observed_at,
                "rates_per_million_tokens": {
                    "cache_hit_input": "0.05",
                    "cache_miss_input": "1.5",
                    "output": "4.5",
                },
                "price_tier": "off_peak",
                "price_tier_rule": (
                    "beijing_weekdays_09:00-12:00_and_14:00-18:00_peak_"
                    "otherwise_off_peak"
                ),
                "unknown_attempt_fallback_rmb": "1",
                "budget_cap_rmb": "30",
            },
            "commissioning": (
                None if commissioning is None else dict(commissioning)
            ),
            "namespace": {
                "run_id": run_id,
                "mode": mode,
                "runs_root_identity": "eval-data/publication-critic/plan096",
                "formal_empty_required": mode == "formal",
                "write_once": "write-once-namespace-v1",
            },
        }
    )


def validate_attempt(value: Any) -> dict[str, Any]:
    attempt = require_exact(
        value,
        {"attempt", "outcome", "usage", "failure_kind", "failure_code"},
        "attempt_fields_invalid",
    )
    if type(attempt.get("attempt")) is not int or attempt["attempt"] <= 0:
        raise CloudQualityError("attempt_index_invalid")
    if attempt.get("outcome") not in {"success", "transient_failure", "failure"}:
        raise CloudQualityError("attempt_outcome_invalid")
    for name in ("failure_kind", "failure_code"):
        if attempt[name] is not None:
            require_text(attempt[name], f"attempt_{name}_invalid")
    if attempt["outcome"] == "success" and (
        attempt["failure_kind"] is not None or attempt["failure_code"] is not None
    ):
        raise CloudQualityError("attempt_success_failure_invalid")
    usage = attempt.get("usage")
    if usage is not None:
        usage = require_exact(
            usage,
            {
                "prompt_tokens",
                "completion_tokens",
                "cache_hit_tokens",
                "cache_miss_tokens",
            },
            "attempt_usage_fields_invalid",
        )
        for name in ("prompt_tokens", "completion_tokens"):
            require_count(usage.get(name), f"attempt_usage_{name}_invalid")
        for name in ("cache_hit_tokens", "cache_miss_tokens"):
            if usage[name] is not None:
                require_count(usage[name], f"attempt_usage_{name}_invalid")
    return dict(attempt)


def validate_call_record(value: Any) -> dict[str, Any]:
    record = require_exact(
        value,
        {
            "candidate_id",
            "status",
            "score",
            "requested_model",
            "effective_model",
            "freeze_sha256",
            "scorer_identity",
            "attempts",
            "conservative_cost_rmb",
            "elapsed_ms",
            "failure_kind",
            "failure_code",
            "failure_disposition",
        },
        "call_record_fields_invalid",
    )
    require_text(record.get("candidate_id"), "call_candidate_id_invalid")
    if record.get("status") not in {"success", "failure"}:
        raise CloudQualityError("call_status_invalid")
    if record.get("requested_model") != REQUESTED_MODEL:
        raise CloudQualityError("call_requested_model_invalid")
    require_text(record.get("effective_model"), "call_effective_model_invalid")
    require_sha256(record.get("freeze_sha256"), "call_freeze_sha256_invalid")
    require_text(record.get("scorer_identity"), "call_scorer_identity_invalid")
    attempts = record.get("attempts")
    if not isinstance(attempts, list) or not attempts:
        raise CloudQualityError("call_attempts_invalid")
    validated_attempts = [validate_attempt(item) for item in attempts]
    if [item["attempt"] for item in validated_attempts] != list(
        range(1, len(validated_attempts) + 1)
    ):
        raise CloudQualityError("call_attempt_order_invalid")
    require_decimal(record.get("conservative_cost_rmb"), "call_cost_invalid")
    elapsed = record.get("elapsed_ms")
    if (
        not isinstance(elapsed, (int, float))
        or isinstance(elapsed, bool)
        or not math.isfinite(float(elapsed))
        or float(elapsed) < 0
    ):
        raise CloudQualityError("call_elapsed_invalid")
    if record["status"] == "success":
        if record["effective_model"] != REQUESTED_MODEL:
            raise CloudQualityError("call_effective_model_mismatch")
        score = record.get("score")
        if (
            not isinstance(score, (int, float))
            or isinstance(score, bool)
            or not math.isfinite(float(score))
            or not 0.0 <= float(score) <= 1.0
        ):
            raise CloudQualityError("call_score_invalid")
        if any(record[name] is not None for name in (
            "failure_kind",
            "failure_code",
            "failure_disposition",
        )):
            raise CloudQualityError("call_success_failure_invalid")
        if validated_attempts[-1]["outcome"] != "success":
            raise CloudQualityError("call_success_attempt_invalid")
    else:
        if record.get("score") is not None:
            raise CloudQualityError("call_failure_score_invalid")
        for name in ("failure_kind", "failure_code", "failure_disposition"):
            require_text(record.get(name), f"call_{name}_invalid")
        if record["failure_disposition"] not in {
            "retryable_infrastructure",
            "implementation_invalid",
            "effective_model_failure",
            "permanent_failure",
            "budget_exhausted",
        }:
            raise CloudQualityError("call_failure_disposition_invalid")
    return dict(record)


def validate_scores_document(value: Any, freeze: Mapping[str, Any]) -> dict[str, Any]:
    scores = require_exact(
        value,
        {"schema", "freeze_sha256", "release_sha256", "rows", "failures"},
        "scores_fields_invalid",
    )
    expected_freeze = freeze_sha256(freeze)
    if (
        scores.get("schema") != SCORES_SCHEMA
        or scores.get("freeze_sha256") != expected_freeze
        or scores.get("release_sha256") != VALIDATION_RELEASE_SHA256
        or not isinstance(scores.get("rows"), list)
        or not isinstance(scores.get("failures"), list)
    ):
        raise CloudQualityError("scores_identity_invalid")
    rows = [validate_call_record(row) for row in scores["rows"]]
    failures = [validate_call_record(row) for row in scores["failures"]]
    if any(row["status"] != "success" for row in rows) or any(
        row["status"] != "failure" for row in failures
    ):
        raise CloudQualityError("scores_status_invalid")
    identifiers = [row["candidate_id"] for row in [*rows, *failures]]
    if len(identifiers) != len(set(identifiers)):
        raise CloudQualityError("scores_candidate_duplicate")
    if any(row["freeze_sha256"] != expected_freeze for row in [*rows, *failures]):
        raise CloudQualityError("scores_freeze_mismatch")
    expected_scorer = freeze["scorer"]["scorer_identity"]
    if any(row["scorer_identity"] != expected_scorer for row in [*rows, *failures]):
        raise CloudQualityError("scores_scorer_mismatch")
    return {
        "schema": SCORES_SCHEMA,
        "freeze_sha256": expected_freeze,
        "release_sha256": VALIDATION_RELEASE_SHA256,
        "rows": rows,
        "failures": failures,
    }


def require_exact_candidate_order(
    observed: Sequence[str], expected: Sequence[str], *, allow_prefix: bool
) -> None:
    if len(observed) != len(set(observed)):
        raise CloudQualityError("score_candidate_duplicate")
    target = list(expected[: len(observed)]) if allow_prefix else list(expected)
    if list(observed) != target:
        raise CloudQualityError("score_candidate_order_mismatch")
