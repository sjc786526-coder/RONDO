"""Shared raw-scalar Binary and Pair objectives.

The scalar reference helpers are pure Python and form the focused-test oracle.
The autograd implementation imports Torch only when called.
"""

from __future__ import annotations

import math
from typing import Any, Sequence

from .contract import FullModelTrainingError


def _softplus(value: float) -> float:
    if value > 0:
        return value + math.log1p(math.exp(-value))
    return math.log1p(math.exp(value))


def _sigmoid(value: float) -> float:
    if value >= 0:
        inverse = math.exp(-value)
        return 1.0 / (1.0 + inverse)
    exponent = math.exp(value)
    return exponent / (1.0 + exponent)


def binary_reference(score: float, label: str) -> tuple[float, float]:
    """Return stable loss and d(loss)/d(score) for the frozen direction."""

    if not math.isfinite(score) or label not in {"PASS", "REWRITE"}:
        raise FullModelTrainingError("binary_objective_input_invalid")
    target = 1.0 if label == "PASS" else -1.0
    signed = -target * score
    return _softplus(signed), -target * _sigmoid(signed)


def pair_reference(
    preferred: float,
    dispreferred: float,
    *,
    margin: float = 0.0,
    temperature: float = 1.0,
) -> tuple[float, float, float]:
    """Return loss and derivatives for preferred-higher pair supervision."""

    if (
        not math.isfinite(preferred)
        or not math.isfinite(dispreferred)
        or not math.isfinite(margin)
        or not math.isfinite(temperature)
        or margin < 0
        or temperature <= 0
    ):
        raise FullModelTrainingError("pair_objective_input_invalid")
    argument = (margin - (preferred - dispreferred)) / temperature
    derivative = _sigmoid(argument) / temperature
    return _softplus(argument), -derivative, derivative


def extract_raw_scalar(logits: Any) -> Any:
    """Return exactly ``logits[:, 0]`` after shape and finite checks."""

    torch = _torch()
    shape = tuple(getattr(logits, "shape", ()))
    if len(shape) != 2 or shape[1] != 1 or shape[0] <= 0:
        raise FullModelTrainingError("model_scalar_shape_invalid")
    scalar = logits[:, 0]
    if not bool(torch.isfinite(scalar).all().item()):
        raise FullModelTrainingError("model_scalar_nonfinite")
    return scalar


def binary_loss(scalars: Any, labels: Sequence[str]) -> Any:
    torch = _torch()
    functional = torch.nn.functional
    if tuple(getattr(scalars, "shape", ())) != (len(labels),) or not labels:
        raise FullModelTrainingError("binary_objective_shape_invalid")
    if any(label not in {"PASS", "REWRITE"} for label in labels):
        raise FullModelTrainingError("binary_objective_label_invalid")
    targets = torch.tensor(
        [1.0 if label == "PASS" else -1.0 for label in labels],
        dtype=scalars.dtype,
        device=scalars.device,
    )
    loss = functional.softplus(-targets * scalars).mean()
    _require_finite_tensor(loss, "binary_objective_nonfinite")
    return loss


def pair_loss(
    preferred: Any,
    dispreferred: Any,
    *,
    margin: float,
    temperature: float,
) -> Any:
    torch = _torch()
    if (
        tuple(getattr(preferred, "shape", ())) != tuple(getattr(dispreferred, "shape", ()))
        or len(tuple(getattr(preferred, "shape", ()))) != 1
        or preferred.shape[0] <= 0
        or not math.isfinite(margin)
        or margin < 0
        or not math.isfinite(temperature)
        or temperature <= 0
    ):
        raise FullModelTrainingError("pair_objective_shape_invalid")
    loss = torch.nn.functional.softplus(
        (margin - (preferred - dispreferred)) / temperature
    ).mean()
    _require_finite_tensor(loss, "pair_objective_nonfinite")
    return loss


def _require_finite_tensor(value: Any, code: str) -> None:
    torch = _torch()
    if not bool(torch.isfinite(value).all().item()):
        raise FullModelTrainingError(code)


def _torch() -> Any:
    try:
        import torch
    except ImportError as exc:
        raise FullModelTrainingError("torch_dependency_missing") from exc
    return torch
