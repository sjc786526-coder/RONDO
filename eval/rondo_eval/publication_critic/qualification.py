"""Validation-only decision configuration and fixed qualification metrics."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from .identity import canonical_json_bytes
from .successor_task import (
    DIMENSION_CLASSES,
    HARD_DIMENSIONS,
    TASK_AUTHORITY,
    TASK_NAME,
    TASK_VERSION,
    derive_verdict,
    validate_labels,
    validate_structured_output,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
DECISION_CONFIG_SCHEMA = "rondo-publication-critic-decision-config@v1"
DECISION_CONTRACT_NAME = "rondo-publication-critic-decision"
DECISION_CONTRACT_VERSION = "v1"
DECISION_CONTRACT_AUTHORITY = Path(
    "doc/rondo-multi-publication-critic-decision-contract-v1.md"
)
DECISION_IMPLEMENTATION_LOCK = Path(
    "eval/templates/publication-critic/decision-implementation-lock-v1.json"
)
DECISION_IMPLEMENTATION_COMPONENT_PATHS = (
    DECISION_CONTRACT_AUTHORITY.as_posix(),
    "eval/rondo_eval/publication_critic/qualification.py",
    "eval/templates/publication-critic/decision-config-contract-v1.json",
    "eval/templates/publication-critic/qualification-metrics-contract-v1.json",
)
BINARY_DIMENSIONS = tuple(
    dimension for dimension in HARD_DIMENSIONS if dimension != "conditional_continuity"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")


class QualificationError(ValueError):
    """A decision config, decoder input, or qualification metric is invalid."""


def task_content_sha256(repo_root: Path | str = REPO_ROOT) -> str:
    return _file_sha256(Path(repo_root) / TASK_AUTHORITY, "task authority")


def decision_contract_sha256(repo_root: Path | str = REPO_ROOT) -> str:
    return _file_sha256(
        Path(repo_root) / DECISION_CONTRACT_AUTHORITY,
        "decision contract authority",
    )


def decision_implementation_identity(
    repo_root: Path | str = REPO_ROOT,
) -> dict[str, Any]:
    """Validate and return the frozen decoder/metrics implementation bundle."""

    root = Path(repo_root)
    lock_path = root / DECISION_IMPLEMENTATION_LOCK
    if not lock_path.is_file() or lock_path.is_symlink():
        raise QualificationError("decision implementation lock is missing or unsafe")
    try:
        value = json.loads(lock_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError("decision implementation lock is invalid") from exc
    lock = _object(value, "decision implementation lock")
    _exact_keys(
        lock,
        {"schema", "algorithm", "components", "bundle_sha256"},
        "decision implementation lock",
    )
    _literal(
        lock["schema"],
        "rondo-publication-critic-decision-implementation-lock@v1",
        "decision implementation lock.schema",
    )
    _literal(
        lock["algorithm"],
        "sha256-canonical-component-list-v1",
        "decision implementation lock.algorithm",
    )
    components = lock["components"]
    if not isinstance(components, list):
        raise QualificationError("decision implementation lock.components differs")
    _literal(
        [component.get("path") for component in components],
        list(DECISION_IMPLEMENTATION_COMPONENT_PATHS),
        "decision implementation lock.component paths",
    )
    normalized_components: list[dict[str, str]] = []
    for component_value in components:
        component = _object(
            component_value,
            "decision implementation lock.component",
        )
        _exact_keys(
            component,
            {"path", "sha256"},
            "decision implementation lock.component",
        )
        path = component["path"]
        if (
            not isinstance(path, str)
            or Path(path).is_absolute()
            or ".." in Path(path).parts
        ):
            raise QualificationError("decision implementation component path is unsafe")
        expected_sha256 = _file_sha256(
            root / path,
            f"decision implementation component {path}",
        )
        _literal(
            component["sha256"],
            expected_sha256,
            f"decision implementation component {path}.sha256",
        )
        normalized_components.append({"path": path, "sha256": component["sha256"]})
    bundle_sha256 = hashlib.sha256(
        canonical_json_bytes(normalized_components)
    ).hexdigest()
    _literal(
        lock["bundle_sha256"],
        bundle_sha256,
        "decision implementation lock.bundle_sha256",
    )
    return {
        "algorithm": lock["algorithm"],
        "components": normalized_components,
        "bundle_sha256": bundle_sha256,
    }


def freeze_decision_config(
    *,
    model_artifact_sha256: str,
    development_revision: str,
    development_manifest_sha256: str,
    validation_candidates_sha256: str,
    validation_rows: int,
    selection_method: str,
    selection_split: str,
    head_margins: Mapping[str, Mapping[str, Any]],
    repo_root: Path | str = REPO_ROOT,
) -> dict[str, Any]:
    """Freeze one model/data-bound config selected without a test entrypoint."""

    config = {
        "schema": DECISION_CONFIG_SCHEMA,
        "task": {
            "name": TASK_NAME,
            "version": TASK_VERSION,
            "authority_path": TASK_AUTHORITY.as_posix(),
            "content_sha256": task_content_sha256(repo_root),
        },
        "decision_contract": {
            "name": DECISION_CONTRACT_NAME,
            "version": DECISION_CONTRACT_VERSION,
            "authority_path": DECISION_CONTRACT_AUTHORITY.as_posix(),
            "content_sha256": decision_contract_sha256(repo_root),
        },
        "decision_implementation": decision_implementation_identity(repo_root),
        "model": {"artifact_sha256": model_artifact_sha256},
        "development_data": {
            "revision": development_revision,
            "manifest_sha256": development_manifest_sha256,
            "validation_candidates_sha256": validation_candidates_sha256,
        },
        "selection": {
            "split": selection_split,
            "method": selection_method,
            "test_access": "forbidden",
            "frozen": True,
            "validation_rows": validation_rows,
        },
        "heads": {
            dimension: dict(head_margins[dimension]) for dimension in HARD_DIMENSIONS
        },
    }
    validate_decision_config(config, repo_root=repo_root)
    return config


def validate_decision_config(
    value: Mapping[str, Any],
    *,
    repo_root: Path | str = REPO_ROOT,
) -> None:
    config = _object(value, "decision config")
    _exact_keys(
        config,
        {
            "schema",
            "task",
            "decision_contract",
            "decision_implementation",
            "model",
            "development_data",
            "selection",
            "heads",
        },
        "decision config",
    )
    _literal(config["schema"], DECISION_CONFIG_SCHEMA, "decision config.schema")
    task = _object(config["task"], "decision config.task")
    _exact_keys(
        task,
        {"name", "version", "authority_path", "content_sha256"},
        "decision config.task",
    )
    _literal(task["name"], TASK_NAME, "decision config.task.name")
    _literal(task["version"], TASK_VERSION, "decision config.task.version")
    _literal(
        task["authority_path"],
        TASK_AUTHORITY.as_posix(),
        "decision config.task.authority_path",
    )
    _literal(
        task["content_sha256"],
        task_content_sha256(repo_root),
        "decision config.task.content_sha256",
    )
    contract = _object(
        config["decision_contract"],
        "decision config.decision_contract",
    )
    _exact_keys(
        contract,
        {"name", "version", "authority_path", "content_sha256"},
        "decision config.decision_contract",
    )
    _literal(
        contract["name"],
        DECISION_CONTRACT_NAME,
        "decision config.decision_contract.name",
    )
    _literal(
        contract["version"],
        DECISION_CONTRACT_VERSION,
        "decision config.decision_contract.version",
    )
    _literal(
        contract["authority_path"],
        DECISION_CONTRACT_AUTHORITY.as_posix(),
        "decision config.decision_contract.authority_path",
    )
    _literal(
        contract["content_sha256"],
        decision_contract_sha256(repo_root),
        "decision config.decision_contract.content_sha256",
    )
    _literal(
        config["decision_implementation"],
        decision_implementation_identity(repo_root),
        "decision config.decision_implementation",
    )
    model = _object(config["model"], "decision config.model")
    _exact_keys(model, {"artifact_sha256"}, "decision config.model")
    _sha256(model["artifact_sha256"], "decision config.model.artifact_sha256")
    data = _object(config["development_data"], "decision config.development_data")
    _exact_keys(
        data,
        {"revision", "manifest_sha256", "validation_candidates_sha256"},
        "decision config.development_data",
    )
    _identifier(data["revision"], "decision config.development_data.revision")
    _sha256(
        data["manifest_sha256"],
        "decision config.development_data.manifest_sha256",
    )
    _sha256(
        data["validation_candidates_sha256"],
        "decision config.development_data.validation_candidates_sha256",
    )
    selection = _object(config["selection"], "decision config.selection")
    _exact_keys(
        selection,
        {"split", "method", "test_access", "frozen", "validation_rows"},
        "decision config.selection",
    )
    _literal(selection["split"], "validation", "decision config.selection.split")
    _identifier(selection["method"], "decision config.selection.method")
    _literal(
        selection["test_access"],
        "forbidden",
        "decision config.selection.test_access",
    )
    _literal(selection["frozen"], True, "decision config.selection.frozen")
    if (
        isinstance(selection["validation_rows"], bool)
        or not isinstance(selection["validation_rows"], int)
        or selection["validation_rows"] <= 0
    ):
        raise QualificationError("decision config validation_rows must be positive")
    heads = _object(config["heads"], "decision config.heads")
    _exact_keys(heads, set(HARD_DIMENSIONS), "decision config.heads")
    for dimension in BINARY_DIMENSIONS:
        head = _object(heads[dimension], f"decision config.heads.{dimension}")
        _exact_keys(
            head,
            {"pass_over_fail_margin"},
            f"decision config.heads.{dimension}",
        )
        _margin(
            head["pass_over_fail_margin"],
            f"decision config.heads.{dimension}.pass_over_fail_margin",
            strictly_positive=False,
        )
    continuity = _object(
        heads["conditional_continuity"],
        "decision config.heads.conditional_continuity",
    )
    _exact_keys(
        continuity,
        {"pass_over_fail_margin", "na_over_applicable_margin"},
        "decision config.heads.conditional_continuity",
    )
    _margin(
        continuity["pass_over_fail_margin"],
        "decision config.heads.conditional_continuity.pass_over_fail_margin",
        strictly_positive=False,
    )
    _margin(
        continuity["na_over_applicable_margin"],
        "decision config.heads.conditional_continuity.na_over_applicable_margin",
        strictly_positive=True,
    )


def decision_config_sha256(
    value: Mapping[str, Any],
    *,
    repo_root: Path | str = REPO_ROOT,
) -> str:
    validate_decision_config(value, repo_root=repo_root)
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def decode_with_decision_config(
    output: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    repo_root: Path | str = REPO_ROOT,
) -> tuple[dict[str, str], ...]:
    """Decode five independent heads, with conservative continuity exclusion."""

    validate_structured_output(output)
    validate_decision_config(config, repo_root=repo_root)
    decoded: list[dict[str, str]] = []
    for index in range(output["batch_size"]):
        labels: dict[str, str] = {}
        for dimension in BINARY_DIMENSIONS:
            logits = output["heads"][dimension]["logits"][index]
            margin = config["heads"][dimension]["pass_over_fail_margin"]
            labels[dimension] = (
                "PASS" if float(logits[0]) - float(logits[1]) > margin else "FAIL"
            )
        logits = output["heads"]["conditional_continuity"]["logits"][index]
        continuity = config["heads"]["conditional_continuity"]
        if (
            float(logits[2]) - max(float(logits[0]), float(logits[1]))
            > continuity["na_over_applicable_margin"]
        ):
            labels["conditional_continuity"] = "N/A"
        else:
            labels["conditional_continuity"] = (
                "PASS"
                if float(logits[0]) - float(logits[1])
                > continuity["pass_over_fail_margin"]
                else "FAIL"
            )
        decoded.append(labels)
    return tuple(decoded)


def select_and_freeze_decision_config(
    *,
    validation_output: Mapping[str, Any],
    validation_labels: Sequence[Mapping[str, Any]],
    candidate_head_margins: Sequence[Mapping[str, Mapping[str, Any]]],
    model_artifact_sha256: str,
    development_revision: str,
    development_manifest_sha256: str,
    validation_candidates_sha256: str,
    repo_root: Path | str = REPO_ROOT,
) -> dict[str, Any]:
    """Select deterministically from a bounded validation-only candidate set."""

    validate_structured_output(validation_output)
    if len(validation_labels) != validation_output["batch_size"]:
        raise QualificationError("validation labels and logits have different rows")
    gold = [validate_labels(row) for row in validation_labels]
    if not candidate_head_margins or len(candidate_head_margins) > 1024:
        raise QualificationError("decision selection requires 1..1024 candidates")
    best: dict[str, Any] | None = None
    best_score: tuple[float | int, ...] | None = None
    best_bytes: bytes | None = None
    for margins in candidate_head_margins:
        config = freeze_decision_config(
            model_artifact_sha256=model_artifact_sha256,
            development_revision=development_revision,
            development_manifest_sha256=development_manifest_sha256,
            validation_candidates_sha256=validation_candidates_sha256,
            validation_rows=len(gold),
            selection_method="bounded_validation_grid_v1",
            selection_split="validation",
            head_margins=margins,
            repo_root=repo_root,
        )
        predicted = decode_with_decision_config(
            validation_output,
            config,
            repo_root=repo_root,
        )
        metrics = evaluate_qualification_predictions(gold, predicted)
        score = _selection_score(metrics)
        encoded = canonical_json_bytes(config)
        if (
            best_score is None
            or score > best_score
            or (score == best_score and encoded < best_bytes)
        ):
            best = config
            best_score = score
            best_bytes = encoded
    if best is None:
        raise QualificationError("decision selection did not produce a config")
    return best


def evaluate_qualification_predictions(
    gold_rows: Sequence[Mapping[str, Any]],
    predicted_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Return fixed confusion/failure-recall metrics for qualification."""

    if not gold_rows or len(gold_rows) != len(predicted_rows):
        raise QualificationError(
            "qualification evaluation requires equal non-empty rows"
        )
    gold = [validate_labels(row) for row in gold_rows]
    predicted = [validate_labels(row) for row in predicted_rows]
    per_dimension: dict[str, dict[str, Any]] = {}
    for dimension in HARD_DIMENSIONS:
        classes = DIMENSION_CLASSES[dimension]
        confusion = {
            expected: {actual: 0 for actual in classes} for expected in classes
        }
        for expected, actual in zip(gold, predicted, strict=True):
            confusion[expected[dimension]][actual[dimension]] += 1
        gold_fail = sum(confusion["FAIL"].values())
        fail_detected = confusion["FAIL"]["FAIL"]
        per_dimension[dimension] = {
            "classes": list(classes),
            "confusion": confusion,
            "total": len(gold),
            "correct": sum(confusion[label][label] for label in classes),
            "gold_pass": sum(confusion["PASS"].values()),
            "gold_fail": gold_fail,
            "fail_detected": fail_detected,
            "fail_to_pass": confusion["FAIL"]["PASS"],
            "fail_to_na": confusion["FAIL"].get("N/A", 0),
            "pass_to_fail": confusion["PASS"]["FAIL"],
            "pass_to_na": confusion["PASS"].get("N/A", 0),
            "failure_recall": _recall(fail_detected, gold_fail),
        }
    gate_pairs = [
        (derive_verdict(expected), derive_verdict(actual))
        for expected, actual in zip(gold, predicted, strict=True)
    ]
    return {
        "schema": "rondo-publication-critic-qualification-metrics@v1",
        "per_dimension": per_dimension,
        "gate": {
            "total": len(gate_pairs),
            "correct": sum(expected == actual for expected, actual in gate_pairs),
            "false_pass": sum(
                expected == "REWRITE" and actual == "PASS"
                for expected, actual in gate_pairs
            ),
            "false_rewrite": sum(
                expected == "PASS" and actual == "REWRITE"
                for expected, actual in gate_pairs
            ),
        },
    }


def _selection_score(metrics: Mapping[str, Any]) -> tuple[float | int, ...]:
    macro_recalls: list[float] = []
    total_correct = 0
    for details in metrics["per_dimension"].values():
        class_recalls: list[float] = []
        for label in details["classes"]:
            denominator = sum(details["confusion"][label].values())
            if denominator:
                class_recalls.append(details["confusion"][label][label] / denominator)
        macro_recalls.append(sum(class_recalls) / len(class_recalls))
        total_correct += details["correct"]
    gate = metrics["gate"]
    return (
        min(macro_recalls),
        -gate["false_pass"],
        gate["correct"],
        -gate["false_rewrite"],
        total_correct,
    )


def _recall(numerator: int, denominator: int) -> dict[str, Any]:
    if denominator == 0:
        return {
            "status": "unavailable",
            "numerator": 0,
            "denominator": 0,
            "value": None,
        }
    return {
        "status": "available",
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator,
    }


def _file_sha256(path: Path, where: str) -> str:
    if not path.is_file() or path.is_symlink():
        raise QualificationError(f"{where} is missing or unsafe")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _object(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise QualificationError(f"{where} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], where: str) -> None:
    if set(value) != expected:
        raise QualificationError(f"{where} keys differ")


def _literal(value: Any, expected: Any, where: str) -> None:
    if value != expected or isinstance(value, bool) != isinstance(expected, bool):
        raise QualificationError(f"{where} differs")


def _sha256(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise QualificationError(f"{where} is not a SHA-256")
    return value


def _identifier(value: Any, where: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise QualificationError(f"{where} is not a bounded identifier")
    return value


def _margin(value: Any, where: str, *, strictly_positive: bool) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QualificationError(f"{where} is not numeric")
    numeric = float(value)
    if (
        not math.isfinite(numeric)
        or numeric < 0
        or (strictly_positive and numeric == 0)
    ):
        raise QualificationError(f"{where} is outside its conservative range")
    return numeric
