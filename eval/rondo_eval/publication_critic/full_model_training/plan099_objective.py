"""Task-v2 five-head layout and non-compensating Plan 099 objective."""

import math
from collections.abc import Mapping, Sequence
from typing import Any

from ..successor_task import DIMENSION_CLASSES
from ..successor_task import HARD_DIMENSIONS
from ..successor_task import derive_verdict
from ..successor_task import validate_labels
from ..successor_task import validate_pair_labels
from ..successor_task import validate_structured_output
from .contract import FullModelTrainingError


HEAD_SLICES = {
    "useful_state_transfer": (0, 2),
    "honest_uncertainty": (2, 4),
    "conditional_continuity": (4, 7),
    "scope_and_signal": (7, 9),
    "internal_consistency": (9, 11),
}
FLAT_LOGIT_COUNT = 11


def structured_output_from_flat(rows: Sequence[Sequence[float]]) -> dict[str, Any]:
    normalized = _flat_rows(rows)
    output = {
        "schema": "rondo-publication-critic-structured-output@v1",
        "backbone_forward_count": 1,
        "batch_size": len(normalized),
        "heads": {
            dimension: {
                "classes": list(DIMENSION_CLASSES[dimension]),
                "logits": [list(row[start:stop]) for row in normalized],
            }
            for dimension, (start, stop) in HEAD_SLICES.items()
        },
    }
    validate_structured_output(output)
    return output


def flat_rows_from_tensor(logits: Any) -> tuple[tuple[float, ...], ...]:
    shape = tuple(getattr(logits, "shape", ()))
    if len(shape) != 2 or shape[0] <= 0 or shape[1] != FLAT_LOGIT_COUNT:
        raise FullModelTrainingError("plan099_flat_logits_shape_invalid")
    try:
        rows = logits.detach().float().cpu().tolist()
    except Exception as exc:
        raise FullModelTrainingError("plan099_flat_logits_invalid") from exc
    return tuple(tuple(float(value) for value in row) for row in _flat_rows(rows))


def reference_objective(
    *,
    candidate_ids: Sequence[str],
    flat_logits: Sequence[Sequence[float]],
    labels_by_id: Mapping[str, Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
    recipe: Mapping[str, Any],
) -> dict[str, float]:
    """Pure-Python oracle for the exact tensor objective."""

    ids, rows, labels, normalized_pairs = _objective_inputs(
        candidate_ids, flat_logits, labels_by_id, pairs
    )
    objective = _objective_contract(recipe)
    by_id = dict(zip(ids, rows, strict=True))
    class_weights = objective["dimension_class_weights"]
    dimension_losses: list[float] = []
    gate_losses: list[float] = []
    for candidate_id in ids:
        row = by_id[candidate_id]
        gold = labels[candidate_id]
        for dimension in HARD_DIMENSIONS:
            start, stop = HEAD_SLICES[dimension]
            logits = row[start:stop]
            target = DIMENSION_CLASSES[dimension].index(gold[dimension])
            dimension_losses.append(
                float(class_weights[dimension][target])
                * _cross_entropy_reference(logits, target)
            )
        gate_margin = _gate_margin_reference(row, gold, objective)
        gate_target = 1.0 if derive_verdict(gold) == "PASS" else 0.0
        gate_losses.append(_binary_cross_entropy_with_logits(gate_margin, gate_target))

    boundary_rows: list[float] = []
    invariance_rows: list[float] = []
    for pair in normalized_pairs:
        left_id = str(pair["left_candidate_id"])
        right_id = str(pair["right_candidate_id"])
        left = by_id[left_id]
        right = by_id[right_id]
        left_labels = labels[left_id]
        right_labels = labels[right_id]
        if pair["kind"] == "boundary":
            plus_id, minus_id = _boundary_roles(left_id, right_id, labels)
            plus = by_id[plus_id]
            minus = by_id[minus_id]
            plus_labels = labels[plus_id]
            minus_labels = labels[minus_id]
            target_dimension = str(pair["target_dimension"])
            target = max(
                objective["target_logit_margin"]
                - (
                    _pass_margin_reference(plus, target_dimension, objective)
                    - _pass_margin_reference(minus, target_dimension, objective)
                ),
                0.0,
            )
            endpoint_gate = 0.5 * (
                max(
                    objective["endpoint_gate_margin"]
                    - _gate_margin_reference(plus, plus_labels, objective),
                    0.0,
                )
                + max(
                    objective["endpoint_gate_margin"]
                    + _gate_margin_reference(minus, minus_labels, objective),
                    0.0,
                )
            )
            non_target = _mean_js_reference(
                plus,
                minus,
                tuple(
                    dimension
                    for dimension in HARD_DIMENSIONS
                    if dimension != target_dimension
                ),
            )
            subweights = objective["boundary_subweights"]
            boundary_rows.append(
                subweights["target_absolute_margin"] * target
                + subweights["endpoint_gate"] * endpoint_gate
                + subweights["non_target_invariance"] * non_target
            )
        else:
            heads = _mean_js_reference(left, right, HARD_DIMENSIONS)
            left_gate = _gate_margin_reference(left, left_labels, objective)
            right_gate = _gate_margin_reference(right, right_labels, objective)
            gate = _smooth_l1_reference(left_gate - right_gate)
            subweights = objective["invariance_subweights"]
            invariance_rows.append(
                subweights["heads"] * heads + subweights["gate"] * gate
            )
    if not boundary_rows or not invariance_rows:
        raise FullModelTrainingError("plan099_objective_component_missing")
    components = {
        "dimension": sum(dimension_losses) / len(dimension_losses),
        "gate": sum(gate_losses) / len(gate_losses),
        "boundary": sum(boundary_rows) / len(boundary_rows),
        "invariance": sum(invariance_rows) / len(invariance_rows),
    }
    weights = objective["component_weights"]
    total = sum(float(weights[name]) * value for name, value in components.items())
    result = {**components, "total": total}
    if any(not math.isfinite(value) or value < 0.0 for value in result.values()):
        raise FullModelTrainingError("plan099_objective_nonfinite")
    return result


def torch_objective(
    *,
    candidate_ids: Sequence[str],
    flat_logits: Any,
    labels_by_id: Mapping[str, Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
    recipe: Mapping[str, Any],
) -> dict[str, Any]:
    """Autograd objective over cached pooled features and all v10 supervision."""

    torch = _torch()
    functional = torch.nn.functional
    shape = tuple(getattr(flat_logits, "shape", ()))
    if shape != (len(candidate_ids), FLAT_LOGIT_COUNT) or not candidate_ids:
        raise FullModelTrainingError("plan099_flat_logits_shape_invalid")
    if not bool(torch.isfinite(flat_logits).all().item()):
        raise FullModelTrainingError("plan099_flat_logits_nonfinite")
    ids, _rows, labels, normalized_pairs = _objective_inputs(
        candidate_ids,
        [[0.0] * FLAT_LOGIT_COUNT for _ in candidate_ids],
        labels_by_id,
        pairs,
    )
    objective = _objective_contract(recipe)
    index_by_id = {candidate_id: index for index, candidate_id in enumerate(ids)}
    dimension_losses = []
    pass_margins: dict[str, Any] = {}
    for dimension in HARD_DIMENSIONS:
        start, stop = HEAD_SLICES[dimension]
        head = flat_logits[:, start:stop].float()
        targets = torch.tensor(
            [
                DIMENSION_CLASSES[dimension].index(labels[candidate_id][dimension])
                for candidate_id in ids
            ],
            dtype=torch.long,
            device=flat_logits.device,
        )
        weights = torch.tensor(
            objective["dimension_class_weights"][dimension],
            dtype=head.dtype,
            device=head.device,
        )
        dimension_losses.append(functional.cross_entropy(head, targets, weight=weights))
        pass_margins[dimension] = _pass_margin_tensor(head, dimension, objective)
    dimension_loss = torch.stack(dimension_losses).mean()

    gate_margins = torch.stack(
        [
            _gate_margin_tensor(
                pass_margins,
                index,
                labels[candidate_id],
                objective,
            )
            for index, candidate_id in enumerate(ids)
        ]
    )
    gate_targets = torch.tensor(
        [
            1.0 if derive_verdict(labels[candidate_id]) == "PASS" else 0.0
            for candidate_id in ids
        ],
        dtype=gate_margins.dtype,
        device=gate_margins.device,
    )
    gate_loss = functional.binary_cross_entropy_with_logits(gate_margins, gate_targets)

    boundary_losses = []
    invariance_losses = []
    for pair in normalized_pairs:
        left_id = str(pair["left_candidate_id"])
        right_id = str(pair["right_candidate_id"])
        left_index = index_by_id[left_id]
        right_index = index_by_id[right_id]
        if pair["kind"] == "boundary":
            plus_id, minus_id = _boundary_roles(left_id, right_id, labels)
            plus_index = index_by_id[plus_id]
            minus_index = index_by_id[minus_id]
            target_dimension = str(pair["target_dimension"])
            target = functional.relu(
                float(objective["target_logit_margin"])
                - (
                    pass_margins[target_dimension][plus_index]
                    - pass_margins[target_dimension][minus_index]
                )
            )
            endpoint_gate = 0.5 * (
                functional.relu(
                    float(objective["endpoint_gate_margin"]) - gate_margins[plus_index]
                )
                + functional.relu(
                    float(objective["endpoint_gate_margin"]) + gate_margins[minus_index]
                )
            )
            dimensions = tuple(
                dimension
                for dimension in HARD_DIMENSIONS
                if dimension != target_dimension
            )
            non_target = _mean_js_tensor(
                flat_logits[left_index], flat_logits[right_index], dimensions
            )
            subweights = objective["boundary_subweights"]
            boundary_losses.append(
                float(subweights["target_absolute_margin"]) * target
                + float(subweights["endpoint_gate"]) * endpoint_gate
                + float(subweights["non_target_invariance"]) * non_target
            )
        else:
            heads = _mean_js_tensor(
                flat_logits[left_index], flat_logits[right_index], HARD_DIMENSIONS
            )
            left_gate = gate_margins[left_index]
            right_gate = gate_margins[right_index]
            gate = functional.smooth_l1_loss(left_gate, right_gate)
            subweights = objective["invariance_subweights"]
            invariance_losses.append(
                float(subweights["heads"]) * heads + float(subweights["gate"]) * gate
            )
    if not boundary_losses or not invariance_losses:
        raise FullModelTrainingError("plan099_objective_component_missing")
    components = {
        "dimension": dimension_loss,
        "gate": gate_loss,
        "boundary": torch.stack(boundary_losses).mean(),
        "invariance": torch.stack(invariance_losses).mean(),
    }
    weights = objective["component_weights"]
    total = sum(float(weights[name]) * value for name, value in components.items())
    if not bool(torch.isfinite(total).all().item()):
        raise FullModelTrainingError("plan099_objective_nonfinite")
    return {**components, "total": total}


def _objective_inputs(
    candidate_ids: Sequence[str],
    flat_logits: Sequence[Sequence[float]],
    labels_by_id: Mapping[str, Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
) -> tuple[
    tuple[str, ...],
    tuple[tuple[float, ...], ...],
    dict[str, dict[str, str]],
    tuple[dict[str, Any], ...],
]:
    ids = tuple(candidate_ids)
    if (
        not ids
        or len(set(ids)) != len(ids)
        or any(not isinstance(value, str) or not value for value in ids)
        or set(labels_by_id) != set(ids)
    ):
        raise FullModelTrainingError("plan099_objective_candidates_invalid")
    rows = _flat_rows(flat_logits)
    if len(rows) != len(ids):
        raise FullModelTrainingError("plan099_flat_logits_shape_invalid")
    labels = {
        candidate_id: validate_labels(labels_by_id[candidate_id])
        for candidate_id in ids
    }
    normalized_pairs = []
    for value in pairs:
        if not isinstance(value, Mapping):
            raise FullModelTrainingError("plan099_pair_invalid")
        left_id = value.get("left_candidate_id")
        right_id = value.get("right_candidate_id")
        if left_id not in labels or right_id not in labels:
            raise FullModelTrainingError("plan099_pair_endpoint_invalid")
        kind = value.get("kind")
        target = value.get("target_dimension")
        if kind not in {"boundary", "soft_only_invariance"}:
            raise FullModelTrainingError("plan099_pair_kind_invalid")
        try:
            validate_pair_labels(
                kind=kind,
                left_labels=labels[str(left_id)],
                right_labels=labels[str(right_id)],
                target_dimension=target,
            )
        except Exception as exc:
            raise FullModelTrainingError("plan099_pair_labels_invalid") from exc
        normalized_pairs.append(dict(value))
    if not normalized_pairs:
        raise FullModelTrainingError("plan099_pairs_empty")
    return ids, rows, labels, tuple(normalized_pairs)


def _objective_contract(recipe: Mapping[str, Any]) -> dict[str, Any]:
    try:
        objective = dict(recipe["objective"])
        weights = objective["component_weights"]
        if set(weights) != {"dimension", "gate", "boundary", "invariance"}:
            raise ValueError
        if objective["soft_preference_qualification_weight"] != 0.0:
            raise ValueError
        for dimension in HARD_DIMENSIONS:
            values = objective["dimension_class_weights"][dimension]
            if len(values) != len(DIMENSION_CLASSES[dimension]) or any(
                not math.isfinite(float(value)) or float(value) <= 0.0
                for value in values
            ):
                raise ValueError
        return objective
    except (KeyError, TypeError, ValueError) as exc:
        raise FullModelTrainingError("plan099_objective_contract_invalid") from exc


def _flat_rows(rows: Sequence[Sequence[float]]) -> tuple[tuple[float, ...], ...]:
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes, bytearray)):
        raise FullModelTrainingError("plan099_flat_logits_invalid")
    result = []
    for row in rows:
        if (
            not isinstance(row, Sequence)
            or isinstance(row, (str, bytes, bytearray))
            or len(row) != FLAT_LOGIT_COUNT
        ):
            raise FullModelTrainingError("plan099_flat_logits_shape_invalid")
        normalized = tuple(float(value) for value in row)
        if any(not math.isfinite(value) for value in normalized):
            raise FullModelTrainingError("plan099_flat_logits_nonfinite")
        result.append(normalized)
    if not result:
        raise FullModelTrainingError("plan099_flat_logits_empty")
    return tuple(result)


def _boundary_roles(
    left_id: str,
    right_id: str,
    labels: Mapping[str, Mapping[str, Any]],
) -> tuple[str, str]:
    left = derive_verdict(labels[left_id])
    right = derive_verdict(labels[right_id])
    if (left, right) == ("PASS", "REWRITE"):
        return left_id, right_id
    if (left, right) == ("REWRITE", "PASS"):
        return right_id, left_id
    raise FullModelTrainingError("plan099_boundary_absolute_gate_invalid")


def _pass_margin_reference(
    row: Sequence[float], dimension: str, objective: Mapping[str, Any]
) -> float:
    start, stop = HEAD_SLICES[dimension]
    logits = row[start:stop]
    if dimension == "conditional_continuity":
        return _smooth_min_reference(
            (logits[0] - logits[1], logits[0] - logits[2]),
            float(objective["smooth_min_temperature"]),
        )
    return logits[0] - logits[1]


def _gate_margin_reference(
    row: Sequence[float], labels: Mapping[str, Any], objective: Mapping[str, Any]
) -> float:
    checked = validate_labels(labels)
    margins = [
        _pass_margin_reference(row, dimension, objective)
        for dimension in HARD_DIMENSIONS
        if not (dimension == "conditional_continuity" and checked[dimension] == "N/A")
    ]
    return _smooth_min_reference(margins, float(objective["smooth_min_temperature"]))


def _smooth_min_reference(values: Sequence[float], temperature: float) -> float:
    if not values or temperature <= 0.0:
        raise FullModelTrainingError("plan099_smooth_min_invalid")
    scaled = [-float(value) / temperature for value in values]
    maximum = max(scaled)
    return -temperature * (
        maximum + math.log(sum(math.exp(value - maximum) for value in scaled))
    )


def _cross_entropy_reference(logits: Sequence[float], target: int) -> float:
    maximum = max(logits)
    logsumexp = maximum + math.log(sum(math.exp(value - maximum) for value in logits))
    return logsumexp - logits[target]


def _binary_cross_entropy_with_logits(logit: float, target: float) -> float:
    return max(logit, 0.0) - logit * target + math.log1p(math.exp(-abs(logit)))


def _probabilities(logits: Sequence[float]) -> tuple[float, ...]:
    maximum = max(logits)
    values = [math.exp(value - maximum) for value in logits]
    total = sum(values)
    return tuple(value / total for value in values)


def _mean_js_reference(
    left: Sequence[float], right: Sequence[float], dimensions: Sequence[str]
) -> float:
    values = []
    for dimension in dimensions:
        start, stop = HEAD_SLICES[dimension]
        p = _probabilities(left[start:stop])
        q = _probabilities(right[start:stop])
        middle = tuple((a + b) / 2.0 for a, b in zip(p, q, strict=True))
        values.append(
            0.5
            * sum(
                a * math.log(max(a, 1e-12) / max(m, 1e-12))
                for a, m in zip(p, middle, strict=True)
            )
            + 0.5
            * sum(
                b * math.log(max(b, 1e-12) / max(m, 1e-12))
                for b, m in zip(q, middle, strict=True)
            )
        )
    return sum(values) / len(values)


def _smooth_l1_reference(value: float) -> float:
    absolute = abs(value)
    return 0.5 * absolute * absolute if absolute < 1.0 else absolute - 0.5


def _pass_margin_tensor(head: Any, dimension: str, objective: Mapping[str, Any]) -> Any:
    if dimension != "conditional_continuity":
        return head[:, 0] - head[:, 1]
    torch = _torch()
    values = torch.stack((head[:, 0] - head[:, 1], head[:, 0] - head[:, 2]), dim=1)
    temperature = float(objective["smooth_min_temperature"])
    return -temperature * torch.logsumexp(-values / temperature, dim=1)


def _gate_margin_tensor(
    margins: Mapping[str, Any],
    index: int,
    labels: Mapping[str, Any],
    objective: Mapping[str, Any],
) -> Any:
    torch = _torch()
    checked = validate_labels(labels)
    values = torch.stack(
        [
            margins[dimension][index]
            for dimension in HARD_DIMENSIONS
            if not (
                dimension == "conditional_continuity" and checked[dimension] == "N/A"
            )
        ]
    )
    temperature = float(objective["smooth_min_temperature"])
    return -temperature * torch.logsumexp(-values / temperature, dim=0)


def _mean_js_tensor(left: Any, right: Any, dimensions: Sequence[str]) -> Any:
    torch = _torch()
    functional = torch.nn.functional
    values = []
    for dimension in dimensions:
        start, stop = HEAD_SLICES[dimension]
        log_p = functional.log_softmax(left[start:stop].float(), dim=0)
        log_q = functional.log_softmax(right[start:stop].float(), dim=0)
        p = log_p.exp()
        q = log_q.exp()
        middle = 0.5 * (p + q)
        log_middle = torch.log(middle.clamp_min(1e-12))
        values.append(
            0.5 * torch.sum(p * (log_p - log_middle))
            + 0.5 * torch.sum(q * (log_q - log_middle))
        )
    return torch.stack(values).mean()


def _torch() -> Any:
    try:
        import torch
    except ImportError as exc:
        raise FullModelTrainingError("plan099_torch_dependency_missing") from exc
    return torch


__all__ = [
    "FLAT_LOGIT_COUNT",
    "HEAD_SLICES",
    "flat_rows_from_tensor",
    "reference_objective",
    "structured_output_from_flat",
    "torch_objective",
]
