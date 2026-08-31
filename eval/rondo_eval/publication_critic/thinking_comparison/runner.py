"""Plan 101 batch runner, recovery, and independent recomputation."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from ..identity import canonical_json_bytes, sha256_bytes
from ..structured_diagnostic.contract import (
    DiagnosticTask,
    DirectOutput,
    OutputContractError,
    ScalarOutput,
    StructuredOutput,
    parse_output,
)
from ..structured_diagnostic.cost import (
    DiagnosticCostError,
    Plan100BudgetLedger,
    settle_attempt,
    worst_case_reservation_rmb,
)
from ..structured_diagnostic.release import PublicItem, ValidationRelease
from ..structured_diagnostic.runner import (
    AmbiguousAttemptError,
    DiagnosticEvaluator,
    DiagnosticRunnerError,
)
from .archive import RECEIPT_SCHEMA, TERMINAL_SCHEMA, ComparisonArchive
from .freeze import (
    ARMS,
    CONDITIONS,
    REQUESTED_MODEL,
    expected_observation_count,
    freeze_sha256,
    repeats_for,
    validate_freeze,
)
from .metrics import (
    SENSITIVE_CANDIDATE_IDS,
    difference_table,
    majority_discrete,
    mean_score,
    unit_metrics,
)

RESULT_SCHEMA = "rondo-publication-critic-plan101-comparison-result@v1"
COMMISSIONING_RESULT_SCHEMA = (
    "rondo-publication-critic-plan101-commissioning-result@v1"
)
COMMISSIONING_BINDING_SCHEMA = (
    "rondo-publication-critic-plan101-commissioning-binding@v1"
)
TRACKED_RESULT_SCHEMA = "rondo-publication-critic-plan101-comparison-summary@v1"


class ComparisonRunnerError(DiagnosticRunnerError):
    """A Plan 101 runner, archive, or recomputation invariant failed."""


def logical_key(condition: str, task: DiagnosticTask, candidate_id: str, repeat: int) -> str:
    return f"{condition}:{task.value}:{candidate_id}:r{repeat:02d}"


def iter_matrix(
    freeze: Mapping[str, Any], items: Sequence[PublicItem]
) -> list[tuple[str, DiagnosticTask, PublicItem, int]]:
    rows: list[tuple[str, DiagnosticTask, PublicItem, int]] = []
    for condition in CONDITIONS:
        repeats = repeats_for(freeze, condition)
        for task in DiagnosticTask:
            for item in items:
                for repeat in range(1, repeats + 1):
                    rows.append((condition, task, item, repeat))
    return rows


def run_batch(
    freeze_value: Mapping[str, Any],
    items: Sequence[PublicItem],
    *,
    archive: ComparisonArchive,
    ledger: Plan100BudgetLedger,
    evaluators: Mapping[str, DiagnosticEvaluator],
    allow_technical_retry: bool = False,
) -> dict[str, Any]:
    freeze = validate_freeze(freeze_value)
    if archive.mode != freeze["mode"] or archive.run_id != freeze["run_id"]:
        raise ComparisonRunnerError("runner_freeze_archive_mismatch")
    expected_items = 3 if archive.mode == "commissioning" else 27
    if (
        len(items) != expected_items
        or len({item.candidate_id for item in items}) != expected_items
    ):
        raise ComparisonRunnerError("runner_item_cohort_invalid")
    if set(evaluators) != set(CONDITIONS):
        raise ComparisonRunnerError("runner_evaluators_incomplete")
    missing_usage = Decimal(str(freeze["budget"]["missing_usage_rmb"]))
    reserve = worst_case_reservation_rmb(
        max_attempts=freeze["request"]["max_attempts"],
        max_prompt_tokens=16_384,
        max_completion_tokens=max(freeze["request"]["max_output_tokens"], 131_072),
        missing_usage_rmb=missing_usage,
    )
    completed: list[dict[str, Any]] = []
    stopped: dict[str, Any] | None = None
    for condition, task, item, repeat in iter_matrix(freeze, items):
        key = logical_key(condition, task, item.candidate_id, repeat)
        terminal = archive.load_terminal(key)
        if terminal is not None:
            _validate_terminal(terminal, freeze, item, condition, task, repeat)
            completed.append(terminal)
            continue
        receipts = archive.load_receipts(key)
        if receipts:
            for receipt in receipts:
                _validate_receipt(receipt, freeze, item, condition, task, repeat)
                _settle_or_verify(ledger, freeze, receipt)
            prior = receipts[-1]
            if prior["observation"]["outcome"]["type"] != "technical_failure":
                terminal = _terminal_from_receipt(prior)
                archive.write_terminal(key, terminal)
                completed.append(terminal)
                continue
            if not allow_technical_retry:
                stopped = {"reason": "technical_failure", "logical_key": key}
                break
        ordinal = len(receipts) + 1
        budget_key = f"{archive.run_id}:{key}:{ordinal}"
        _reserve_or_ambiguous(ledger, budget_key, reserve)
        public_packet = json.loads(item.packet_bytes)
        observation = _normalize_evaluator_observation(
            task, evaluators[condition].evaluate(task, public_packet)
        )
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "logical_key": key,
            "freeze_sha256": freeze_sha256(freeze),
            "condition": condition,
            "arm": task.value,
            "candidate_id": item.candidate_id,
            "repeat": repeat,
            "packet_sha256": sha256_bytes(item.packet_bytes),
            "budget_key": budget_key,
            "observation": observation,
        }
        archive.write_receipt(key, receipt)
        ledger.settle(budget_key, observation["attempts"])
        if observation["outcome"]["type"] == "technical_failure":
            stopped = {"reason": "technical_failure", "logical_key": key}
            break
        terminal = _terminal_from_receipt(receipt)
        archive.write_terminal(key, terminal)
        completed.append(terminal)
    expected = expected_observation_count(freeze, item_count=expected_items)
    successful = sum(row["status"] == "success" for row in completed)
    return {
        "mode": archive.mode,
        "run_id": archive.run_id,
        "terminal_observation_count": len(completed),
        "expected_terminal_observation_count": expected,
        "successful_terminal_observation_count": successful,
        "parse_failure_count": len(completed) - successful,
        "complete": len(completed) == expected and stopped is None,
        "stopped": stopped,
        "ledger": ledger.snapshot(),
    }


def recompute_commissioning(
    freeze_value: Mapping[str, Any],
    items: Sequence[PublicItem],
    archive: ComparisonArchive,
    ledger: Plan100BudgetLedger,
) -> dict[str, Any]:
    freeze = validate_freeze(freeze_value)
    if freeze["mode"] != "commissioning" or archive.mode != "commissioning":
        raise ComparisonRunnerError("recompute_requires_commissioning")
    terminals: list[dict[str, Any]] = []
    receipts: list[dict[str, Any]] = []
    response_texts: dict[str, list[str]] = {f"{c}:{a}": [] for c in CONDITIONS for a in ARMS}
    completion_tokens: dict[str, list[int]] = {
        f"{c}:{a}": [] for c in CONDITIONS for a in ARMS
    }
    for condition, task, item, repeat in iter_matrix(freeze, items):
        key = logical_key(condition, task, item.candidate_id, repeat)
        terminal = archive.load_terminal(key)
        if terminal is None:
            return {
                "schema": COMMISSIONING_RESULT_SCHEMA,
                "complete": False,
                "reason": "commissioning_terminal_missing",
                "task_budget": ledger.snapshot(),
            }
        _validate_terminal(terminal, freeze, item, condition, task, repeat)
        matching = [
            receipt
            for receipt in archive.load_receipts(key)
            if sha256_bytes(canonical_json_bytes(receipt)) == terminal["receipt_sha256"]
        ]
        if len(matching) != 1:
            raise ComparisonRunnerError("terminal_receipt_binding_invalid")
        _validate_receipt(matching[0], freeze, item, condition, task, repeat)
        terminals.append(terminal)
        receipts.append(matching[0])
        unit = f"{condition}:{task.value}"
        text = matching[0]["observation"].get("response_text")
        if isinstance(text, str):
            response_texts[unit].append(text)
        for attempt in matching[0]["observation"]["attempts"]:
            usage = attempt.get("usage")
            if isinstance(usage, Mapping) and type(usage.get("completion_tokens")) is int:
                completion_tokens[unit].append(usage["completion_tokens"])
    success = all(row["status"] == "success" for row in terminals)
    expected = expected_observation_count(freeze, item_count=len(items))
    non_degenerate = all(
        len(set(texts)) > 1 for texts in response_texts.values() if texts
    )
    scalar_non_boundary = any(
        row["status"] == "success"
        and row["arm"] == "A"
        and row["parsed_output"]["quality"] not in {0.0, 1.0}
        for row in terminals
    )
    thinking_effect = _thinking_token_effect(completion_tokens)
    checks = {
        "six_units_complete": len(terminals) == expected == 18 and success,
        "thinking_switch_effect": thinking_effect["passed"],
        "outputs_non_degenerate": non_degenerate and scalar_non_boundary,
    }
    return {
        "schema": COMMISSIONING_RESULT_SCHEMA,
        "complete": all(checks.values()),
        "checks": checks,
        "thinking_token_effect": thinking_effect,
        "non_boundary_scalar_present": scalar_non_boundary,
        "unit_response_distinct": {
            unit: len(set(texts)) for unit, texts in response_texts.items()
        },
        "terminal_observation_count": len(terminals),
        "usage_and_cost": _usage_and_cost(receipts),
        "task_budget": ledger.snapshot(),
    }


def build_commissioning_binding(
    freeze: Mapping[str, Any], result: Mapping[str, Any]
) -> dict[str, Any]:
    if result.get("complete") is not True:
        raise ComparisonRunnerError("commissioning_binding_requires_success")
    return {
        "schema": COMMISSIONING_BINDING_SCHEMA,
        "run_id": freeze["run_id"],
        "commissioning_freeze": freeze,
        "freeze_sha256": freeze_sha256(freeze),
        "commissioning_result": result,
        "result_sha256": sha256_bytes(canonical_json_bytes(result)),
    }


def validate_commissioning_binding(
    binding: Any, freeze: Mapping[str, Any]
) -> dict[str, Any]:
    if not isinstance(binding, Mapping) or set(binding) != {
        "schema",
        "run_id",
        "commissioning_freeze",
        "freeze_sha256",
        "commissioning_result",
        "result_sha256",
    }:
        raise ComparisonRunnerError("commissioning_binding_invalid")
    commissioned = validate_freeze(binding["commissioning_freeze"])
    if (
        binding.get("schema") != COMMISSIONING_BINDING_SCHEMA
        or binding.get("run_id") != commissioned["run_id"]
        or binding.get("freeze_sha256") != freeze_sha256(commissioned)
        or binding.get("result_sha256")
        != sha256_bytes(canonical_json_bytes(binding["commissioning_result"]))
    ):
        raise ComparisonRunnerError("commissioning_binding_invalid")
    commissioned_source = commissioned["source"]
    formal_source = freeze["source"]
    for field in (
        "diagnostic_contract_sha256",
        "diagnostic_executable_sha256",
        "descriptor_sha256",
    ):
        if commissioned_source[field] != formal_source[field]:
            raise ComparisonRunnerError("commissioning_binding_source_drifted")
    if (
        commissioned["provider"] != freeze["provider"]
        or commissioned["request"] != freeze["request"]
        or commissioned["release"] != freeze["release"]
        or commissioned["budget"]["price_card_sha256"]
        != freeze["budget"]["price_card_sha256"]
        or commissioned["matrix"]["conditions"] != freeze["matrix"]["conditions"]
        or commissioned["matrix"]["arm_order"] != freeze["matrix"]["arm_order"]
    ):
        raise ComparisonRunnerError("commissioning_binding_identity_drifted")
    return dict(binding)


def recompute_formal(
    freeze_value: Mapping[str, Any],
    release: ValidationRelease,
    archive: ComparisonArchive,
    ledger: Plan100BudgetLedger,
) -> dict[str, Any]:
    freeze = validate_freeze(freeze_value)
    if freeze["mode"] != "formal" or archive.mode != "formal":
        raise ComparisonRunnerError("recompute_requires_formal")
    items = release.public_items
    terminals: dict[str, list[dict[str, Any]]] = {
        f"{condition}:{arm}": [] for condition in CONDITIONS for arm in ARMS
    }
    receipts: list[dict[str, Any]] = []
    for condition, task, item, repeat in iter_matrix(freeze, items):
        key = logical_key(condition, task, item.candidate_id, repeat)
        terminal = archive.load_terminal(key)
        if terminal is None:
            return {
                "schema": RESULT_SCHEMA,
                "freeze_sha256": freeze_sha256(freeze),
                "complete": False,
                "observations_complete": False,
                "reason": "formal_terminal_missing",
                "task_budget": ledger.snapshot(),
                "metrics": None,
            }
        _validate_terminal(terminal, freeze, item, condition, task, repeat)
        matching = [
            receipt
            for receipt in archive.load_receipts(key)
            if sha256_bytes(canonical_json_bytes(receipt)) == terminal["receipt_sha256"]
        ]
        if len(matching) != 1:
            raise ComparisonRunnerError("terminal_receipt_binding_invalid")
        _validate_receipt(matching[0], freeze, item, condition, task, repeat)
        receipts.append(matching[0])
        terminals[f"{condition}:{task.value}"].append(terminal)
    expected = expected_observation_count(freeze, item_count=len(items))
    observed = sum(len(rows) for rows in terminals.values())
    supervision = release.supervision_by_id()
    ids = [item.candidate_id for item in items]
    gold_verdicts = [supervision[item_id].gold_verdict for item_id in ids]
    gold_labels = [supervision[item_id].labels for item_id in ids]
    units: dict[str, Any] = {}
    for condition in CONDITIONS:
        for arm, task in zip(ARMS, DiagnosticTask, strict=True):
            unit_key = f"{condition}:{arm}"
            rows = terminals[unit_key]
            by_candidate: dict[str, list[dict[str, Any]]] = {item_id: [] for item_id in ids}
            for row in rows:
                by_candidate[row["candidate_id"]].append(row)
            aggregated_verdicts: list[str | None] = []
            aggregated_labels: list[dict[str, str] | None] = []
            aggregated_scores: list[float | None] = []
            repeat_values: dict[str, list[Any]] = {}
            for item_id in ids:
                candidate_rows = by_candidate[item_id]
                parsed = [
                    None if row["status"] != "success" else row["parsed_output"]
                    for row in candidate_rows
                ]
                if task is DiagnosticTask.SCALAR:
                    scores = [
                        None if item is None else item["quality"] for item in parsed
                    ]
                    score = mean_score(scores)
                    aggregated_scores.append(score)
                    aggregated_verdicts.append(None)
                    aggregated_labels.append(None)
                    repeat_values[item_id] = scores
                elif task is DiagnosticTask.DIRECT:
                    verdicts = [
                        None if item is None else item["verdict"] for item in parsed
                    ]
                    aggregated_verdicts.append(majority_discrete(verdicts))
                    aggregated_scores.append(None)
                    aggregated_labels.append(None)
                    repeat_values[item_id] = verdicts
                else:
                    decisions = [
                        None if item is None else item["decisions"] for item in parsed
                    ]
                    if any(item is None for item in decisions):
                        label = None
                    else:
                        label = {}
                        for dimension in decisions[0]:
                            chosen = majority_discrete(
                                [item[dimension] for item in decisions]
                            )
                            if chosen is None:
                                label = None
                                break
                            label[dimension] = chosen
                    aggregated_labels.append(label)
                    aggregated_verdicts.append(
                        None if label is None else derive_verdict(label)
                    )
                    aggregated_scores.append(None)
                    repeat_values[item_id] = [
                        None if item is None else tuple(sorted(item.items()))
                        for item in decisions
                    ]
            if task is DiagnosticTask.SCALAR:
                curve_scores = aggregated_scores
                selected = _selected_scalar_verdicts(ids, gold_verdicts, curve_scores)
                unit = unit_metrics(
                    arm="A",
                    candidate_ids=ids,
                    gold_verdicts=gold_verdicts,
                    gold_labels=gold_labels,
                    predicted_verdicts=selected,
                    predicted_labels=[None] * len(ids),
                    scores=curve_scores,
                    pairs=release.pair_supervision,
                    per_candidate_repeats=repeat_values,
                )
            elif task is DiagnosticTask.DIRECT:
                unit = unit_metrics(
                    arm="B",
                    candidate_ids=ids,
                    gold_verdicts=gold_verdicts,
                    gold_labels=gold_labels,
                    predicted_verdicts=aggregated_verdicts,
                    predicted_labels=[None] * len(ids),
                    scores=[None] * len(ids),
                    pairs=release.pair_supervision,
                    per_candidate_repeats=repeat_values,
                )
            else:
                unit = unit_metrics(
                    arm="C",
                    candidate_ids=ids,
                    gold_verdicts=gold_verdicts,
                    gold_labels=gold_labels,
                    predicted_verdicts=aggregated_verdicts,
                    predicted_labels=aggregated_labels,
                    scores=[None] * len(ids),
                    pairs=release.pair_supervision,
                    per_candidate_repeats=repeat_values,
                )
            units[unit_key] = unit
    sensitive = set(SENSITIVE_CANDIDATE_IDS)
    kept = [index for index, item_id in enumerate(ids) if item_id not in sensitive]
    sensitive_slice = None
    if len(kept) == len(ids) - len(sensitive & set(ids)):
        sensitive_slice = {
            "excluded_candidate_ids": list(SENSITIVE_CANDIDATE_IDS),
            "remaining": len(kept),
        }
    return {
        "schema": RESULT_SCHEMA,
        "freeze_sha256": freeze_sha256(freeze),
        "complete": observed == expected,
        "observations_complete": observed == expected,
        "terminal_observation_count": observed,
        "expected_terminal_observation_count": expected,
        "thinking_off_repeats": freeze["matrix"]["thinking_off_repeats"],
        "thinking_on_repeats": freeze["matrix"]["thinking_on_repeats"],
        "parse_failure_count": {
            key: sum(row["status"] == "parse_failure" for row in rows)
            for key, rows in terminals.items()
        },
        "provider_identity": {
            "requested_model": REQUESTED_MODEL,
            "served_models": sorted(
                {
                    row["served_model"]
                    for rows in terminals.values()
                    for row in rows
                    if row["served_model"] is not None
                }
            ),
            "serving_revision": "provider-managed-unverifiable",
        },
        "usage_and_cost": _usage_and_cost(receipts),
        "task_budget": ledger.snapshot(),
        "metrics": units,
        "differences": difference_table(units),
        "sensitive_label_slice": sensitive_slice,
    }


def tracked_projection(result: Mapping[str, Any]) -> dict[str, Any]:
    if result.get("schema") != RESULT_SCHEMA:
        raise ComparisonRunnerError("tracked_result_invalid")
    metrics = result.get("metrics")
    compact = None
    if isinstance(metrics, Mapping):
        compact = {}
        for key, unit in metrics.items():
            compact[key] = {
                "balanced_accuracy": unit["binary"]["balanced_accuracy"],
                "balanced_accuracy_wilson": unit["binary"]["balanced_accuracy_wilson"],
                "false_pass": unit["binary"]["false_pass"],
                "false_rewrite": unit["binary"]["false_rewrite"],
                "class_recall": unit["binary"]["class_recall"],
                "typed_failures": unit["binary"]["typed_failures"],
                "pairs_closed": unit["pairs"]["closed"],
                "repeat_consistency_rate": unit["repeat_consistency"]["rate"],
            }
            if "scalar" in unit:
                compact[key]["auc"] = unit["scalar"]["auc"]
                compact[key]["ties"] = {
                    name: unit["scalar"]["ties"][name]
                    for name in (
                        "distinct_values",
                        "cross_class_pairs",
                        "exact_ties",
                        "tie_ratio",
                    )
                }
            if "structured" in unit:
                compact[key]["continuity_na_recall"] = unit["structured"][
                    "per_dimension"
                ]["continuity_na_recall"]
                compact[key]["failure_recall"] = {
                    dimension: table["failure_recall"]
                    for dimension, table in unit["structured"]["per_dimension"][
                        "per_dimension"
                    ].items()
                }
                compact[key]["drawers"] = {
                    name: unit["structured"]["drawers"][name]
                    for name in (
                        "exact_fail_set",
                        "wrong_drawer",
                        "gate_miss",
                        "wrong_drawer_miss",
                        "unnoticed_miss",
                    )
                }
    return {
        "schema": TRACKED_RESULT_SCHEMA,
        "freeze_sha256": result.get("freeze_sha256"),
        "complete": result.get("complete"),
        "terminal_observation_count": result.get("terminal_observation_count"),
        "expected_terminal_observation_count": result.get(
            "expected_terminal_observation_count"
        ),
        "thinking_off_repeats": result.get("thinking_off_repeats"),
        "thinking_on_repeats": result.get("thinking_on_repeats"),
        "parse_failure_count": result.get("parse_failure_count"),
        "usage_and_cost": result.get("usage_and_cost"),
        "task_budget": {
            name: result["task_budget"][name]
            for name in (
                "schema",
                "cap_rmb",
                "settled_rmb",
                "outstanding_reserved_rmb",
                "remaining_unreserved_rmb",
            )
        }
        if isinstance(result.get("task_budget"), Mapping)
        else None,
        "metrics": compact,
        "differences": result.get("differences"),
    }


def _selected_scalar_verdicts(
    candidate_ids: Sequence[str],
    gold_verdicts: Sequence[str],
    scores: Sequence[float | None],
) -> list[str | None]:
    from .metrics import _scalar_curve

    curve = _scalar_curve(candidate_ids, gold_verdicts, scores, ())
    if not curve:
        return [None for _ in candidate_ids]
    best = max(
        curve,
        key=lambda point: (
            point["balanced_accuracy"],
            -point["false_pass"],
            point["correct"],
            -point["false_rewrite"],
            -1.0 if point["threshold"] is None else point["threshold"],
        ),
    )
    threshold = best["threshold"]
    return [
        None
        if score is None
        else "REWRITE"
        if threshold is None or score < threshold
        else "PASS"
        for score in scores
    ]


def _thinking_token_effect(
    completion_tokens: Mapping[str, Sequence[int]],
) -> dict[str, Any]:
    rows = {}
    passed = True
    for arm in ARMS:
        off = list(completion_tokens.get(f"thinking_off:{arm}", ()))
        on = list(completion_tokens.get(f"thinking_on:{arm}", ()))
        off_mean = None if not off else sum(off) / len(off)
        on_mean = None if not on else sum(on) / len(on)
        significant = (
            off_mean is not None
            and on_mean is not None
            and on_mean >= max(off_mean * 3, off_mean + 20)
            and off_mean <= 64
        )
        passed = passed and significant
        rows[arm] = {
            "thinking_off_mean": off_mean,
            "thinking_on_mean": on_mean,
            "thinking_off_max": None if not off else max(off),
            "thinking_on_max": None if not on else max(on),
            "passed": significant,
        }
    return {"passed": passed, "arms": rows}


def _usage_and_cost(receipts: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    attempts = 0
    prompt = 0
    completion = 0
    elapsed = 0
    for receipt in receipts:
        observation = receipt["observation"]
        elapsed += int(observation["elapsed_ms"])
        for attempt in observation["attempts"]:
            attempts += 1
            usage = attempt.get("usage")
            if isinstance(usage, Mapping):
                prompt += int(usage.get("prompt_tokens") or 0)
                completion += int(usage.get("completion_tokens") or 0)
    settled = sum(
        (
            Decimal(settle_attempt(attempt)["charge_rmb"])
            for receipt in receipts
            for attempt in receipt["observation"]["attempts"]
        ),
        Decimal(0),
    )
    from ..structured_diagnostic.cost import decimal_text

    return {
        "attempts": attempts,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "elapsed_ms": elapsed,
        "settled_rmb": decimal_text(settled),
    }


def _normalize_evaluator_observation(
    task: DiagnosticTask, value: Any
) -> dict[str, Any]:
    expected = {
        "requested_model",
        "served_model",
        "response_text",
        "attempts",
        "elapsed_ms",
        "outcome",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise ComparisonRunnerError("evaluator_observation_fields_invalid")
    if value.get("requested_model") != REQUESTED_MODEL:
        raise ComparisonRunnerError("evaluator_requested_model_invalid")
    served = value.get("served_model")
    response = value.get("response_text")
    attempts = value.get("attempts")
    elapsed = value.get("elapsed_ms")
    outcome = value.get("outcome")
    if (
        (served is not None and not isinstance(served, str))
        or (response is not None and not isinstance(response, str))
        or not isinstance(attempts, list)
        or not 1 <= len(attempts) <= 2
        or type(elapsed) is not int
        or elapsed < 0
        or not isinstance(outcome, Mapping)
    ):
        raise ComparisonRunnerError("evaluator_observation_invalid")
    parsed = None
    parse_code = None
    if outcome == {"type": "success"}:
        if response is None:
            raise ComparisonRunnerError("evaluator_success_missing_body")
        try:
            parsed = parse_output(task, response)
        except OutputContractError as exc:
            raise ComparisonRunnerError("evaluator_success_contract_mismatch") from exc
        status_outcome = {"type": "success"}
    elif (
        set(outcome) == {"type", "kind", "http_status"}
        and outcome.get("type") == "output_contract_failure"
    ):
        if response is None:
            raise ComparisonRunnerError("evaluator_contract_failure_missing_body")
        try:
            parse_output(task, response)
        except OutputContractError as exc:
            parse_code = exc.code
        else:
            raise ComparisonRunnerError("evaluator_contract_failure_mismatch")
        status_outcome = dict(outcome)
    elif (
        set(outcome) == {"type", "kind", "http_status"}
        and outcome.get("type") == "technical_failure"
    ):
        status_outcome = dict(outcome)
    else:
        raise ComparisonRunnerError("evaluator_outcome_invalid")
    return {
        "requested_model": REQUESTED_MODEL,
        "served_model": served,
        "response_text": response,
        "attempts": list(attempts),
        "elapsed_ms": elapsed,
        "outcome": status_outcome,
        "parsed_output": _parsed_document(parsed),
        "parse_failure_code": parse_code,
    }


def _parsed_document(value: Any) -> dict[str, Any] | None:
    if isinstance(value, ScalarOutput):
        return {"quality": value.score}
    if isinstance(value, DirectOutput):
        return {"verdict": value.verdict}
    if isinstance(value, StructuredOutput):
        return {"decisions": dict(value.decisions), "local_verdict": value.verdict}
    return None


def _reserve_or_ambiguous(
    ledger: Plan100BudgetLedger, budget_key: str, reserve: Decimal
) -> None:
    try:
        ledger.reserve(budget_key, reserve)
    except DiagnosticCostError as exc:
        if str(exc) == "logical_key_already_reserved":
            raise AmbiguousAttemptError("reserved_action_has_no_durable_receipt") from exc
        raise


def _settle_or_verify(
    ledger: Plan100BudgetLedger, freeze: Mapping[str, Any], receipt: Mapping[str, Any]
) -> None:
    key = receipt["budget_key"]
    matches = [
        row for row in ledger.snapshot()["reservations"] if row["logical_key"] == key
    ]
    if len(matches) != 1:
        raise ComparisonRunnerError("receipt_budget_reservation_missing")
    missing = Decimal(str(freeze["budget"]["missing_usage_rmb"]))
    if matches[0]["state"] == "reserved":
        needed = sum(
            (
                Decimal(settle_attempt(item, missing_usage_rmb=missing)["charge_rmb"])
                for item in receipt["observation"]["attempts"]
            ),
            Decimal(0),
        )
        reserved = Decimal(matches[0]["reserved_rmb"])
        if needed > reserved:
            ledger.top_up_reservation(key, needed)
        ledger.settle(key, receipt["observation"]["attempts"])
    else:
        expected = [
            settle_attempt(item, missing_usage_rmb=missing)
            for item in receipt["observation"]["attempts"]
        ]
        if matches[0]["attempts"] != expected:
            raise ComparisonRunnerError("receipt_budget_settlement_drifted")


def _validate_receipt(
    value: Mapping[str, Any],
    freeze: Mapping[str, Any],
    item: PublicItem,
    condition: str,
    task: DiagnosticTask,
    repeat: int,
) -> None:
    expected = {
        "schema",
        "logical_key",
        "freeze_sha256",
        "condition",
        "arm",
        "candidate_id",
        "repeat",
        "packet_sha256",
        "budget_key",
        "observation",
    }
    key = logical_key(condition, task, item.candidate_id, repeat)
    if (
        set(value) != expected
        or value.get("schema") != RECEIPT_SCHEMA
        or value.get("logical_key") != key
        or value.get("freeze_sha256") != freeze_sha256(freeze)
        or value.get("condition") != condition
        or value.get("arm") != task.value
        or value.get("candidate_id") != item.candidate_id
        or value.get("repeat") != repeat
        or value.get("packet_sha256") != sha256_bytes(item.packet_bytes)
        or not isinstance(value.get("budget_key"), str)
    ):
        raise ComparisonRunnerError("receipt_identity_invalid")
    _validate_stored_observation(task, value.get("observation"))


def _terminal_from_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    observation = receipt["observation"]
    outcome = observation["outcome"]["type"]
    if outcome not in {"success", "output_contract_failure"}:
        raise ComparisonRunnerError("technical_receipt_has_no_quality_terminal")
    return {
        "schema": TERMINAL_SCHEMA,
        "logical_key": receipt["logical_key"],
        "freeze_sha256": receipt["freeze_sha256"],
        "condition": receipt["condition"],
        "arm": receipt["arm"],
        "candidate_id": receipt["candidate_id"],
        "repeat": receipt["repeat"],
        "packet_sha256": receipt["packet_sha256"],
        "status": "success" if outcome == "success" else "parse_failure",
        "parsed_output": observation["parsed_output"],
        "parse_failure_code": observation["parse_failure_code"],
        "requested_model": observation["requested_model"],
        "served_model": observation["served_model"],
        "elapsed_ms": observation["elapsed_ms"],
        "receipt_sha256": sha256_bytes(canonical_json_bytes(dict(receipt))),
    }


def _validate_terminal(
    value: Mapping[str, Any],
    freeze: Mapping[str, Any],
    item: PublicItem,
    condition: str,
    task: DiagnosticTask,
    repeat: int,
) -> None:
    expected = {
        "schema",
        "logical_key",
        "freeze_sha256",
        "condition",
        "arm",
        "candidate_id",
        "repeat",
        "packet_sha256",
        "status",
        "parsed_output",
        "parse_failure_code",
        "requested_model",
        "served_model",
        "elapsed_ms",
        "receipt_sha256",
    }
    key = logical_key(condition, task, item.candidate_id, repeat)
    if (
        set(value) != expected
        or value.get("schema") != TERMINAL_SCHEMA
        or value.get("logical_key") != key
        or value.get("freeze_sha256") != freeze_sha256(freeze)
        or value.get("condition") != condition
        or value.get("arm") != task.value
        or value.get("candidate_id") != item.candidate_id
        or value.get("repeat") != repeat
        or value.get("packet_sha256") != sha256_bytes(item.packet_bytes)
        or value.get("requested_model") != REQUESTED_MODEL
        or value.get("status") not in {"success", "parse_failure"}
        or type(value.get("elapsed_ms")) is not int
    ):
        raise ComparisonRunnerError("terminal_identity_invalid")


def _validate_stored_observation(task: DiagnosticTask, value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != {
        "requested_model",
        "served_model",
        "response_text",
        "attempts",
        "elapsed_ms",
        "outcome",
        "parsed_output",
        "parse_failure_code",
    }:
        raise ComparisonRunnerError("stored_observation_invalid")
    outcome = value.get("outcome")
    if not isinstance(outcome, Mapping):
        raise ComparisonRunnerError("stored_observation_outcome_invalid")
    if outcome.get("type") == "success":
        if value.get("response_text") is None or value.get("parsed_output") is None:
            raise ComparisonRunnerError("stored_observation_success_invalid")
        parsed = parse_output(task, value["response_text"])
        if value.get("parsed_output") != _parsed_document(parsed):
            raise ComparisonRunnerError("stored_observation_projection_invalid")
    elif outcome.get("type") == "output_contract_failure":
        if value.get("response_text") is None or value.get("parse_failure_code") is None:
            raise ComparisonRunnerError("stored_observation_contract_failure_invalid")
    elif outcome.get("type") != "technical_failure":
        raise ComparisonRunnerError("stored_observation_outcome_invalid")
    for attempt in value.get("attempts") or ():
        settle_attempt(attempt)
