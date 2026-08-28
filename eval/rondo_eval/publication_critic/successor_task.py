"""Pure reference semantics for `rondo-publication-critic-task@v2`."""

import hashlib
import json
import math
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
TASK_NAME = "rondo-publication-critic-task"
TASK_VERSION = "v2"
TASK_AUTHORITY = Path("doc/rondo-multi-publication-critic-task-contract-v2.md")
TASK_PROJECTION = Path("eval/templates/publication-critic/task-contract-v2.json")
STRUCTURED_OUTPUT_SCHEMA = "rondo-publication-critic-structured-output@v1"

HARD_DIMENSIONS = (
    "useful_state_transfer",
    "honest_uncertainty",
    "conditional_continuity",
    "scope_and_signal",
    "internal_consistency",
)
CONDITIONAL_CONTINUITY = "conditional_continuity"
FORBIDDEN_MODEL_INPUT_FIELDS = (
    "completion_state",
    "public_state",
    "candidate_brief",
    "hidden_generation_intent",
    "split",
    "labels",
    "defects",
    "source",
    "generator",
    "reviewer",
    "pair_direction",
    "rationale",
)
DIMENSION_CLASSES = MappingProxyType(
    {
        **{dimension: ("PASS", "FAIL") for dimension in HARD_DIMENSIONS},
        CONDITIONAL_CONTINUITY: ("PASS", "FAIL", "N/A"),
    }
)


class SuccessorTaskError(ValueError):
    """The successor task, output, or supervision violates the authority contract."""


def task_content_sha256(repo_root: Path | str = REPO_ROOT) -> str:
    path = Path(repo_root) / TASK_AUTHORITY
    try:
        content = path.read_bytes()
    except OSError as exc:
        raise SuccessorTaskError("task authority document is unavailable") from exc
    return hashlib.sha256(content).hexdigest()


def load_task_projection(repo_root: Path | str = REPO_ROOT) -> Mapping[str, Any]:
    path = Path(repo_root) / TASK_PROJECTION
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SuccessorTaskError("task projection is unavailable or invalid") from exc
    _validate_task_projection(value)
    return value


def _validate_task_projection(value: Any) -> None:
    obj = _object(value, "task projection")
    _exact_keys(
        obj,
        {
            "schema",
            "authority",
            "input",
            "dimensions",
            "output",
            "aggregation",
            "loss",
            "evaluation",
        },
        "task projection",
    )
    _literal(
        obj["schema"],
        "rondo-publication-critic-task-contract-projection@v1",
        "task projection.schema",
    )
    authority = _object(obj["authority"], "task projection.authority")
    _exact_keys(authority, {"name", "version", "path"}, "task projection.authority")
    _literal(authority["name"], TASK_NAME, "task projection.authority.name")
    _literal(authority["version"], TASK_VERSION, "task projection.authority.version")
    _literal(authority["path"], TASK_AUTHORITY.as_posix(), "task projection.authority.path")

    task_input = _object(obj["input"], "task projection.input")
    _exact_keys(
        task_input,
        {
            "packet_schema",
            "qualification",
            "input_contract",
            "rubric",
            "render_contract",
            "render_implementation",
            "applicability_source",
            "forbidden_model_input_fields",
        },
        "task projection.input",
    )
    _literal(
        task_input["packet_schema"],
        "rondo-publication-packet@v1",
        "task projection.input.packet_schema",
    )
    _literal(
        task_input["qualification"],
        "rondo-publication-qualification@v2",
        "task projection.input.qualification",
    )
    _literal(
        task_input["input_contract"],
        "eval/templates/publication-critic/input-contract-v3.md",
        "task projection.input.input_contract",
    )
    _literal(
        task_input["rubric"],
        "eval/templates/publication-critic/qualification-rubric-v2.md",
        "task projection.input.rubric",
    )
    _literal(
        task_input["render_contract"],
        "eval/templates/publication-critic/render-contract-v4.json",
        "task projection.input.render_contract",
    )
    _literal(
        task_input["render_implementation"],
        "eval/rondo_eval/publication_critic/render.py",
        "task projection.input.render_implementation",
    )
    _literal(
        task_input["applicability_source"],
        "model_visible_candidate_only",
        "task projection.input.applicability_source",
    )
    if task_input["forbidden_model_input_fields"] != list(
        FORBIDDEN_MODEL_INPUT_FIELDS
    ):
        raise SuccessorTaskError("task projection forbidden model input fields differ")

    dimensions = _object(obj["dimensions"], "task projection.dimensions")
    _exact_keys(dimensions, {"order", "classes"}, "task projection.dimensions")
    if dimensions["order"] != list(HARD_DIMENSIONS):
        raise SuccessorTaskError("task projection dimension order differs from authority")
    classes = _object(dimensions["classes"], "task projection.dimensions.classes")
    _exact_keys(classes, set(HARD_DIMENSIONS), "task projection.dimensions.classes")
    for dimension in HARD_DIMENSIONS:
        if classes[dimension] != list(DIMENSION_CLASSES[dimension]):
            raise SuccessorTaskError(f"task projection classes differ for {dimension}")

    output = _object(obj["output"], "task projection.output")
    _exact_keys(
        output,
        {
            "schema",
            "backbone_forward_count",
            "head_count",
            "global_quality_head",
            "compatibility_scalar_is_derived",
            "decode_tie_policy",
        },
        "task projection.output",
    )
    _literal(output["schema"], STRUCTURED_OUTPUT_SCHEMA, "task projection.output.schema")
    _literal(
        output["backbone_forward_count"],
        1,
        "task projection.output.backbone_forward_count",
    )
    _literal(output["head_count"], 5, "task projection.output.head_count")
    _literal(output["global_quality_head"], None, "task projection.output.global_quality_head")
    _literal(
        output["compatibility_scalar_is_derived"],
        True,
        "task projection.output.compatibility_scalar_is_derived",
    )
    _literal(
        output["decode_tie_policy"],
        "fail_closed_to_FAIL_per_head",
        "task projection.output.decode_tie_policy",
    )

    aggregation = _object(obj["aggregation"], "task projection.aggregation")
    _exact_keys(
        aggregation,
        {"discrete", "pass", "fail", "quality", "compensation"},
        "task projection.aggregation",
    )
    _literal(
        aggregation.get("discrete"),
        "all_applicable_heads_pass",
        "task projection.aggregation.discrete",
    )
    _literal(aggregation.get("pass"), "PASS", "task projection.aggregation.pass")
    _literal(aggregation.get("fail"), "REWRITE", "task projection.aggregation.fail")
    _literal(
        aggregation.get("quality"),
        "min_applicable_pass_satisfaction",
        "task projection.aggregation.quality",
    )
    _literal(
        aggregation.get("compensation"),
        "forbidden",
        "task projection.aggregation.compensation",
    )
    loss = _object(obj["loss"], "task projection.loss")
    _exact_keys(
        loss,
        {
            "formula",
            "primary",
            "gate",
            "boundary",
            "invariance",
            "soft_preference_in_qualification",
        },
        "task projection.loss",
    )
    _literal(
        loss.get("formula"),
        "L_dim + lambda_gate L_gate + lambda_boundary L_boundary + lambda_inv L_invariance",
        "task projection.loss.formula",
    )
    _literal(
        loss.get("primary"),
        "complete_per_dimension_absolute_classification",
        "task projection.loss.primary",
    )
    _literal(loss.get("gate"), "derived_conjunction_only", "task projection.loss.gate")
    _literal(
        loss.get("boundary"),
        "finite_target_margin_plus_absolute_endpoint_gate_and_non_target_prediction_invariance",
        "task projection.loss.boundary",
    )
    _literal(
        loss.get("invariance"),
        "both_endpoints_pass_with_identical_hard_labels_and_gate",
        "task projection.loss.invariance",
    )
    _literal(
        loss.get("soft_preference_in_qualification"),
        False,
        "task projection.loss.soft_preference_in_qualification",
    )
    evaluation = _object(obj["evaluation"], "task projection.evaluation")
    _exact_keys(
        evaluation,
        {"primary", "legacy_scalar_metrics_are_diagnostic_only"},
        "task projection.evaluation",
    )
    _literal(
        evaluation["legacy_scalar_metrics_are_diagnostic_only"],
        True,
        "task projection.evaluation.legacy_scalar_metrics_are_diagnostic_only",
    )
    if evaluation["primary"] != [
        "per_dimension_classification",
        "conditional_continuity_applicability",
        "gate_false_pass",
        "gate_false_rewrite",
        "boundary_absolute_closure",
        "soft_only_invariance",
    ]:
        raise SuccessorTaskError("task projection primary evaluation metrics differ")


def validate_labels(value: Mapping[str, Any]) -> dict[str, str]:
    labels = _object(value, "hard labels")
    _exact_keys(labels, set(HARD_DIMENSIONS), "hard labels")
    normalized: dict[str, str] = {}
    for dimension in HARD_DIMENSIONS:
        label = labels[dimension]
        if label not in DIMENSION_CLASSES[dimension]:
            raise SuccessorTaskError(f"invalid {dimension} label")
        normalized[dimension] = label
    return normalized


def applicable_dimensions(labels: Mapping[str, Any]) -> tuple[str, ...]:
    checked = validate_labels(labels)
    return tuple(
        dimension
        for dimension in HARD_DIMENSIONS
        if not (dimension == CONDITIONAL_CONTINUITY and checked[dimension] == "N/A")
    )


def derive_verdict(labels: Mapping[str, Any]) -> str:
    checked = validate_labels(labels)
    return (
        "PASS"
        if all(checked[dimension] == "PASS" for dimension in applicable_dimensions(checked))
        else "REWRITE"
    )


def derive_quality(
    labels: Mapping[str, Any],
    pass_satisfaction: Mapping[str, Any],
) -> float:
    checked = validate_labels(labels)
    satisfaction = _object(pass_satisfaction, "pass satisfaction")
    _exact_keys(satisfaction, set(HARD_DIMENSIONS), "pass satisfaction")
    normalized: dict[str, float] = {}
    for dimension in HARD_DIMENSIONS:
        value = satisfaction[dimension]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise SuccessorTaskError(f"{dimension} satisfaction is not numeric")
        numeric = float(value)
        if not math.isfinite(numeric) or not 0.0 <= numeric <= 1.0:
            raise SuccessorTaskError(f"{dimension} satisfaction is outside [0, 1]")
        normalized[dimension] = numeric
    return min(normalized[dimension] for dimension in applicable_dimensions(checked))


def derive_loss_targets(
    label_rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Project complete absolute labels into the only legal dimension/gate targets."""

    if not label_rows:
        raise SuccessorTaskError("loss supervision requires at least one candidate")
    targets: list[dict[str, Any]] = []
    for row in label_rows:
        labels = validate_labels(row)
        targets.append(
            {
                "dimension_labels": labels,
                "applicable_dimensions": applicable_dimensions(labels),
                "derived_gate_label": derive_verdict(labels),
            }
        )
    return tuple(targets)


def validate_structured_output(value: Mapping[str, Any]) -> None:
    output = _object(value, "structured output")
    _exact_keys(
        output,
        {"schema", "backbone_forward_count", "batch_size", "heads"},
        "structured output",
    )
    _literal(output["schema"], STRUCTURED_OUTPUT_SCHEMA, "structured output.schema")
    _literal(output["backbone_forward_count"], 1, "structured output.backbone_forward_count")
    batch_size = output["batch_size"]
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size <= 0:
        raise SuccessorTaskError("structured output.batch_size must be positive")
    heads = _object(output["heads"], "structured output.heads")
    _exact_keys(heads, set(HARD_DIMENSIONS), "structured output.heads")
    for dimension in HARD_DIMENSIONS:
        head = _object(heads[dimension], f"structured output.heads.{dimension}")
        _exact_keys(head, {"classes", "logits"}, f"structured output.heads.{dimension}")
        if head["classes"] != list(DIMENSION_CLASSES[dimension]):
            raise SuccessorTaskError(f"structured output classes differ for {dimension}")
        logits = head["logits"]
        if not isinstance(logits, list) or len(logits) != batch_size:
            raise SuccessorTaskError(f"structured output batch differs for {dimension}")
        width = len(DIMENSION_CLASSES[dimension])
        for row in logits:
            if not isinstance(row, list) or len(row) != width:
                raise SuccessorTaskError(f"structured output width differs for {dimension}")
            if any(
                isinstance(item, bool)
                or not isinstance(item, (int, float))
                or not math.isfinite(float(item))
                for item in row
            ):
                raise SuccessorTaskError(f"structured output logits are non-finite for {dimension}")


def decode_structured_output(value: Mapping[str, Any]) -> tuple[dict[str, str], ...]:
    validate_structured_output(value)
    batch_size = value["batch_size"]
    decoded: list[dict[str, str]] = []
    for index in range(batch_size):
        labels: dict[str, str] = {}
        for dimension in HARD_DIMENSIONS:
            logits = value["heads"][dimension]["logits"][index]
            maximum = max(logits)
            winners = [position for position, logit in enumerate(logits) if logit == maximum]
            labels[dimension] = (
                DIMENSION_CLASSES[dimension][winners[0]]
                if len(winners) == 1
                else "FAIL"
            )
        decoded.append(labels)
    return tuple(decoded)


def derive_pair_loss_targets(
    rows: Sequence[Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    """Build complete auxiliary-loss targets after absolute pair validation."""

    if not rows:
        raise SuccessorTaskError("pair loss supervision requires at least one pair")
    targets: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, value in enumerate(rows):
        row = _object(value, f"pair loss[{index}]")
        _exact_keys(
            row,
            {
                "pair_id",
                "kind",
                "left_labels",
                "right_labels",
                "target_dimension",
            },
            f"pair loss[{index}]",
        )
        pair_id = _pair_id(row["pair_id"], f"pair loss[{index}].pair_id")
        if pair_id in seen:
            raise SuccessorTaskError(f"duplicate pair loss id: {pair_id}")
        seen.add(pair_id)
        left = validate_labels(row["left_labels"])
        right = validate_labels(row["right_labels"])
        validate_pair_labels(
            row["kind"],
            left,
            right,
            target_dimension=row["target_dimension"],
        )
        if row["kind"] == "boundary":
            constraints = {
                "target_head": {
                    "dimension": row["target_dimension"],
                    "left_label": "PASS",
                    "right_label": "FAIL",
                    "objective": "finite_margin",
                },
                "absolute_gate": {"left": "PASS", "right": "REWRITE"},
                "prediction_invariance_dimensions": tuple(
                    dimension
                    for dimension in HARD_DIMENSIONS
                    if dimension != row["target_dimension"]
                ),
            }
        else:
            constraints = {
                "target_head": None,
                "absolute_gate": {"left": "PASS", "right": "PASS"},
                "prediction_invariance_dimensions": HARD_DIMENSIONS,
            }
        targets.append(
            {
                "pair_id": pair_id,
                "kind": row["kind"],
                "left_dimension_labels": left,
                "right_dimension_labels": right,
                "left_gate_label": derive_verdict(left),
                "right_gate_label": derive_verdict(right),
                "constraints": constraints,
            }
        )
    return tuple(targets)


def validate_pair_labels(
    kind: str,
    left_labels: Mapping[str, Any],
    right_labels: Mapping[str, Any],
    *,
    target_dimension: str | None,
) -> None:
    left = validate_labels(left_labels)
    right = validate_labels(right_labels)
    if kind == "boundary":
        if target_dimension not in HARD_DIMENSIONS:
            raise SuccessorTaskError("boundary target dimension is invalid")
        if left[target_dimension] != "PASS" or right[target_dimension] != "FAIL":
            raise SuccessorTaskError("boundary target must change PASS to FAIL")
        if any(
            left[dimension] != right[dimension]
            for dimension in HARD_DIMENSIONS
            if dimension != target_dimension
        ):
            raise SuccessorTaskError("boundary non-target labels must be invariant")
        if derive_verdict(left) != "PASS" or derive_verdict(right) != "REWRITE":
            raise SuccessorTaskError("boundary endpoints lack absolute PASS/REWRITE closure")
        return
    if kind == "soft_only_invariance":
        if target_dimension is not None:
            raise SuccessorTaskError("soft-only invariance cannot name a target dimension")
        if left != right:
            raise SuccessorTaskError("soft-only invariance labels must be identical")
        if derive_verdict(left) != "PASS" or derive_verdict(right) != "PASS":
            raise SuccessorTaskError("soft-only invariance endpoints must both PASS")
        return
    raise SuccessorTaskError("pair kind is invalid")


def evaluate_predictions(
    gold_rows: Sequence[Mapping[str, Any]],
    predicted_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    if not gold_rows or len(gold_rows) != len(predicted_rows):
        raise SuccessorTaskError("evaluation requires equal non-empty rows")
    gold = [validate_labels(row) for row in gold_rows]
    predicted = [validate_labels(row) for row in predicted_rows]
    per_dimension: dict[str, dict[str, int]] = {}
    for dimension in HARD_DIMENSIONS:
        per_dimension[dimension] = {
            "total": len(gold),
            "correct": sum(
                expected[dimension] == actual[dimension]
                for expected, actual in zip(gold, predicted, strict=True)
            ),
            "applicable_total": sum(row[dimension] != "N/A" for row in gold),
            "applicable_correct": sum(
                expected[dimension] != "N/A"
                and expected[dimension] == actual[dimension]
                for expected, actual in zip(gold, predicted, strict=True)
            ),
            "applicability_correct": sum(
                (expected[dimension] == "N/A") == (actual[dimension] == "N/A")
                for expected, actual in zip(gold, predicted, strict=True)
            ),
            "gold_na": sum(row[dimension] == "N/A" for row in gold),
            "predicted_na": sum(row[dimension] == "N/A" for row in predicted),
        }
    gate_pairs = [
        (derive_verdict(expected), derive_verdict(actual))
        for expected, actual in zip(gold, predicted, strict=True)
    ]
    return {
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


def evaluate_pair_predictions(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not rows:
        raise SuccessorTaskError("pair evaluation requires at least one pair")
    summary: dict[str, dict[str, int]] = {
        "boundary": {"total": 0, "closed": 0},
        "soft_only_invariance": {"total": 0, "closed": 0},
    }
    pair_results: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, value in enumerate(rows):
        row = _object(value, f"pair evaluation[{index}]")
        _exact_keys(
            row,
            {
                "pair_id",
                "kind",
                "left_labels",
                "right_labels",
                "target_dimension",
            },
            f"pair evaluation[{index}]",
        )
        pair_id = _pair_id(row["pair_id"], f"pair evaluation[{index}].pair_id")
        if pair_id in seen:
            raise SuccessorTaskError(f"duplicate pair evaluation id: {pair_id}")
        seen.add(pair_id)
        kind = row["kind"]
        if kind not in summary:
            raise SuccessorTaskError("pair evaluation kind is invalid")
        summary[kind]["total"] += 1
        try:
            validate_pair_labels(
                kind,
                row["left_labels"],
                row["right_labels"],
                target_dimension=row["target_dimension"],
            )
        except SuccessorTaskError as exc:
            pair_results.append(
                {
                    "pair_id": pair_id,
                    "kind": kind,
                    "closed": False,
                    "reason": str(exc),
                }
            )
            continue
        summary[kind]["closed"] += 1
        pair_results.append(
            {
                "pair_id": pair_id,
                "kind": kind,
                "closed": True,
                "reason": None,
            }
        )
    return {"summary": summary, "pairs": pair_results}


def _object(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise SuccessorTaskError(f"{where} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], where: str) -> None:
    if set(value) != expected:
        raise SuccessorTaskError(f"{where} keys differ from the contract")


def _literal(value: Any, expected: Any, where: str) -> None:
    if value != expected or isinstance(value, bool) != isinstance(expected, bool):
        raise SuccessorTaskError(f"{where} differs from the contract")


def _pair_id(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise SuccessorTaskError(f"{where} must be a bounded non-empty string")
    return value
