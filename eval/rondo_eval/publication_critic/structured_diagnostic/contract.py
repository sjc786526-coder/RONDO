"""Strict output contracts for the Plan 100 A/B/C diagnostic tasks."""

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from ..successor_task import DIMENSION_CLASSES, HARD_DIMENSIONS, SuccessorTaskError
from ..successor_task import derive_verdict as _derive_successor_verdict

MAX_OUTPUT_BYTES = 4096


class DiagnosticTask(str, Enum):
    SCALAR = "A"
    DIRECT = "B"
    STRUCTURED = "C"


class OutputContractError(ValueError):
    """A model response is not exactly one valid Plan 100 output object."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ScalarOutput:
    score: float


@dataclass(frozen=True)
class DirectOutput:
    verdict: str


@dataclass(frozen=True)
class StructuredOutput:
    decisions: Mapping[str, str]
    verdict: str


ParsedOutput = ScalarOutput | DirectOutput | StructuredOutput


def parse_output(task: DiagnosticTask | str, raw: str) -> ParsedOutput:
    """Parse one response with duplicate-key, non-finite, and exact-key checks."""

    try:
        normalized_task = DiagnosticTask(task)
    except ValueError as exc:
        raise OutputContractError(
            "unknown_task", "diagnostic task must be A, B, or C"
        ) from exc
    value = _strict_json_object(raw)
    if normalized_task is DiagnosticTask.SCALAR:
        return _parse_scalar(value)
    if normalized_task is DiagnosticTask.DIRECT:
        return _parse_direct(value)
    return _parse_structured(value)


def parse_scalar_output(raw: str) -> ScalarOutput:
    parsed = parse_output(DiagnosticTask.SCALAR, raw)
    assert isinstance(parsed, ScalarOutput)
    return parsed


def parse_direct_output(raw: str) -> DirectOutput:
    parsed = parse_output(DiagnosticTask.DIRECT, raw)
    assert isinstance(parsed, DirectOutput)
    return parsed


def parse_structured_output(raw: str) -> StructuredOutput:
    parsed = parse_output(DiagnosticTask.STRUCTURED, raw)
    assert isinstance(parsed, StructuredOutput)
    return parsed


def derive_verdict(decisions: Mapping[str, Any]) -> str:
    """Apply the task-v2 non-compensating local AND aggregation."""

    try:
        return _derive_successor_verdict(decisions)
    except SuccessorTaskError as exc:
        raise OutputContractError("invalid_structured_value", str(exc)) from exc


def _parse_scalar(value: Mapping[str, Any]) -> ScalarOutput:
    _exact_keys(value, {"quality"}, "A")
    quality = value["quality"]
    if isinstance(quality, bool) or not isinstance(quality, (int, float)):
        raise OutputContractError("invalid_scalar_type", "A.quality must be numeric")
    try:
        score = float(quality)
    except OverflowError as exc:
        raise OutputContractError(
            "non_finite_scalar", "A.quality must be finite"
        ) from exc
    if not math.isfinite(score):
        raise OutputContractError("non_finite_scalar", "A.quality must be finite")
    if not 0.0 <= score <= 1.0:
        raise OutputContractError("scalar_out_of_range", "A.quality must be in [0, 1]")
    return ScalarOutput(score=score)


def _parse_direct(value: Mapping[str, Any]) -> DirectOutput:
    _exact_keys(value, {"verdict"}, "B")
    verdict = value["verdict"]
    if verdict not in {"PASS", "REWRITE"}:
        raise OutputContractError(
            "invalid_direct_verdict",
            "B.verdict must be PASS or REWRITE",
        )
    return DirectOutput(verdict=verdict)


def _parse_structured(value: Mapping[str, Any]) -> StructuredOutput:
    _exact_keys(value, set(HARD_DIMENSIONS), "C")
    decisions: dict[str, str] = {}
    for dimension in HARD_DIMENSIONS:
        decision = value[dimension]
        if decision not in DIMENSION_CLASSES[dimension]:
            raise OutputContractError(
                "invalid_structured_value",
                f"C.{dimension} has an invalid decision",
            )
        decisions[dimension] = decision
    return StructuredOutput(decisions=decisions, verdict=derive_verdict(decisions))


def _strict_json_object(raw: str) -> Mapping[str, Any]:
    if not isinstance(raw, str):
        raise OutputContractError("response_not_text", "model response must be text")
    try:
        response_bytes = len(raw.encode("utf-8"))
    except UnicodeError as exc:
        raise OutputContractError(
            "invalid_json", "model response must be UTF-8 text"
        ) from exc
    if not raw or response_bytes > MAX_OUTPUT_BYTES:
        raise OutputContractError(
            "response_size", "model response size is outside the contract"
        )

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, nested in pairs:
            if key in result:
                raise OutputContractError("duplicate_key", f"duplicate JSON key: {key}")
            result[key] = nested
        return result

    def reject_constant(value: str) -> None:
        raise OutputContractError("non_finite_json", f"non-finite JSON value: {value}")

    try:
        value = json.loads(
            raw,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except OutputContractError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise OutputContractError(
            "invalid_json",
            "response must contain exactly one JSON value and no prose or trailing content",
        ) from exc
    if not isinstance(value, Mapping):
        raise OutputContractError("wrong_top_level", "response must be a JSON object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], task: str) -> None:
    observed = set(value)
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise OutputContractError(
            "object_keys",
            f"{task} output keys differ; missing={missing}, extra={extra}",
        )
