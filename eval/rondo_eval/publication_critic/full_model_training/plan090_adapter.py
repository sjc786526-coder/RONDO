"""Exact Route O adapter with train diagnostics and precision observations."""

from __future__ import annotations

import json
import math
import os
import struct
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .contract import FullModelTrainingError
from .data import PortableTrainingDataset, tokenize_dataset
from .plan081_observation import training_identity_sha256
from .plan087_adapter import Plan087TorchTrainingAdapter, validate_adaptive_recipe
from .plan090_contract import frozen_contract

RUNTIME_KIND = "torch_real_route_o_confirmation_direct_original_parameters"
PRECISION_RECEIPT_SCHEMA = "rondo-publication-critic-plan090-precision-receipt-v1"


def validate_confirmation_recipe(value: Any) -> dict[str, Any]:
    recipe = validate_adaptive_recipe(value)
    allowed = list(frozen_contract()["recipes"].values())
    if recipe not in allowed:
        raise FullModelTrainingError("plan090_recipe_drifted")
    return recipe


class Plan090TorchTrainingAdapter(Plan087TorchTrainingAdapter):
    """Plan 087 mechanics narrowed to the three pre-frozen Plan 090 runs."""

    runtime_kind = RUNTIME_KIND
    image_identity_environment_variable = "RONDO_PLAN090_IMAGE_IDENTITY"
    training_state_codec = "plan090-torch-state-v1"

    @classmethod
    def validate_recipe_value(cls, value: Any) -> dict[str, Any]:
        return validate_confirmation_recipe(value)

    @classmethod
    def from_snapshot(
        cls,
        *,
        snapshot_root: Path,
        model_lock_path: Path,
        recipe: Mapping[str, Any],
    ) -> "Plan090TorchTrainingAdapter":
        adapter = super().from_snapshot(
            snapshot_root=snapshot_root,
            model_lock_path=model_lock_path,
            recipe=recipe,
        )
        adapter._configure_precision_controls()
        adapter._plan090_update_active = False
        adapter._plan090_forward_dtypes: set[str] = set()
        adapter._plan090_gradient_dtypes: dict[str, str] = {}
        adapter._plan090_precision_receipt: dict[str, Any] | None = None
        return adapter

    def plan090_runtime_identity(self) -> dict[str, Any]:
        identity = self.plan082_runtime_identity()
        return {
            **identity,
            "provider_pod_id": os.getenv("RONDO_PLAN090_PROVIDER_POD_ID", ""),
            "provider_pod_name": os.getenv("RONDO_PLAN090_PROVIDER_POD_NAME", ""),
            "precision_controls": self._precision_controls(),
        }

    def evaluate_training(self, dataset: PortableTrainingDataset) -> dict[str, Any]:
        if self.optimizer is None or self.scheduler is None:
            raise FullModelTrainingError("plan090_training_diagnostic_before_scope")
        identity = training_identity_sha256(dataset)
        tokenized = self._training_cache.get(identity)
        if tokenized is None:
            tokenized = tokenize_dataset(dataset, self.exact_tokenizer)
            self._training_cache = {identity: tokenized}
        before = self._training_state_guard()
        self._require_no_gradients()
        training = bool(self.model.training)
        scores: dict[str, float] = {}
        self.model.eval()
        try:
            with self.torch.inference_mode():
                for candidate_id in sorted(dataset.supervision):
                    scalar = self._forward(tokenized, (candidate_id,))
                    score = float(scalar[0].float().item())
                    if not math.isfinite(score):
                        raise FullModelTrainingError(
                            "plan090_training_diagnostic_nonfinite"
                        )
                    scores[candidate_id] = score
        finally:
            if training:
                self.model.train()
        self._require_no_gradients()
        after = self._training_state_guard()
        if not self._values_equal(before, after):
            raise FullModelTrainingError(
                "plan090_training_diagnostic_mutated_training_state"
            )
        return {
            "raw_logits": scores,
            "gradient_access": False,
            "training_state_unchanged": True,
            "training_identity_sha256": identity,
        }

    def apply_update(
        self,
        step: int,
        scope: Any,
        training_dataset: PortableTrainingDataset,
    ) -> dict[str, Any]:
        self._plan090_update_active = True
        self._plan090_forward_dtypes = set()
        self._plan090_gradient_dtypes = {}
        try:
            receipt = super().apply_update(step, scope, training_dataset)
        finally:
            self._plan090_update_active = False
        precision = self._build_precision_receipt(scope)
        self._plan090_precision_receipt = precision
        return {**receipt, "precision_receipt": precision}

    def save_model(self, destination: Path) -> None:
        super().save_model(destination)
        verify_safetensors_storage_dtype(
            destination,
            expected_dtype=self.recipe["parameter_dtype"],
            expected_tensor_count=311,
        )

    def load_model(self, model_root: Path) -> None:
        verify_safetensors_storage_dtype(
            model_root,
            expected_dtype=self.recipe["parameter_dtype"],
            expected_tensor_count=311,
        )
        super().load_model(model_root)

    def precision_receipt(self) -> dict[str, Any]:
        if self._plan090_precision_receipt is None:
            raise FullModelTrainingError("plan090_precision_receipt_unavailable")
        return json.loads(json.dumps(self._plan090_precision_receipt))

    def _forward(
        self, tokenized: Mapping[str, Any], candidate_ids: Sequence[str]
    ) -> Any:
        value = super()._forward(tokenized, candidate_ids)
        if getattr(self, "_plan090_update_active", False):
            self._plan090_forward_dtypes.add(str(getattr(value, "dtype", "")))
        return value

    def _parameter_change_probes(self, scope: Any) -> list[tuple[str, Any, Any]]:
        named = dict(self.model.named_parameters())
        if getattr(self, "_plan090_update_active", False):
            self._plan090_gradient_dtypes = {
                name: str(named[name].grad.dtype)
                for name in scope.parameter_names
                if named[name].grad is not None
            }
        return super()._parameter_change_probes(scope)

    def _configure_precision_controls(self) -> None:
        try:
            self.torch.set_float32_matmul_precision("highest")
            self.torch.backends.cuda.matmul.allow_tf32 = False
            self.torch.backends.cudnn.allow_tf32 = False
        except Exception as exc:
            raise FullModelTrainingError(
                "plan090_precision_controls_unavailable"
            ) from exc
        if self._precision_controls() != {
            "float32_matmul_precision": "highest",
            "cuda_matmul_allow_tf32": False,
            "cudnn_allow_tf32": False,
            "autocast_enabled": False,
        }:
            raise FullModelTrainingError("plan090_precision_controls_drifted")

    def _precision_controls(self) -> dict[str, Any]:
        try:
            return {
                "float32_matmul_precision": str(
                    self.torch.get_float32_matmul_precision()
                ),
                "cuda_matmul_allow_tf32": bool(
                    self.torch.backends.cuda.matmul.allow_tf32
                ),
                "cudnn_allow_tf32": bool(self.torch.backends.cudnn.allow_tf32),
                "autocast_enabled": bool(self.torch.is_autocast_enabled()),
            }
        except Exception as exc:
            raise FullModelTrainingError(
                "plan090_precision_controls_unavailable"
            ) from exc

    def _build_precision_receipt(self, scope: Any) -> dict[str, Any]:
        named = dict(self.model.named_parameters())
        selected = {name: str(named[name].dtype) for name in scope.parameter_names}
        all_parameter_dtypes = sorted(
            {str(parameter.dtype) for parameter in self.model.parameters()}
        )
        optimizer_dtypes: set[str] = set()
        if self.optimizer is None:
            raise FullModelTrainingError("plan090_precision_optimizer_unavailable")
        for state in self.optimizer.state.values():
            for item in state.values():
                if bool(getattr(item, "is_floating_point", lambda: False)()):
                    optimizer_dtypes.add(str(item.dtype))
        expected = {
            "bfloat16": "torch.bfloat16",
            "float32": "torch.float32",
        }[self.recipe["parameter_dtype"]]
        if (
            all_parameter_dtypes != [expected]
            or set(selected.values()) != {expected}
            or set(self._plan090_gradient_dtypes) != set(scope.parameter_names)
            or set(self._plan090_gradient_dtypes.values()) != {expected}
            or expected not in self._plan090_forward_dtypes
            or not optimizer_dtypes
            or (expected == "torch.float32" and optimizer_dtypes != {expected})
            or (
                expected == "torch.bfloat16"
                and not optimizer_dtypes <= {"torch.bfloat16", "torch.float32"}
            )
        ):
            raise FullModelTrainingError("plan090_precision_semantics_drifted")
        return {
            "schema": PRECISION_RECEIPT_SCHEMA,
            "parameter_dtype": self.recipe["parameter_dtype"],
            "model_parameter_dtypes": all_parameter_dtypes,
            "selected_parameter_dtypes": selected,
            "gradient_dtypes": dict(self._plan090_gradient_dtypes),
            "forward_output_dtypes": sorted(self._plan090_forward_dtypes),
            "optimizer_state_dtypes": sorted(optimizer_dtypes),
            "save_parameter_dtype": expected,
            "save_verification": (
                "fail_closed_safetensors_header_before_checkpoint_publish_and_load"
            ),
            "controls": self._precision_controls(),
            "precision_contract": frozen_contract()["precision"][
                self.recipe["parameter_dtype"]
            ],
        }


def verify_safetensors_storage_dtype(
    model_root: Path, *, expected_dtype: str, expected_tensor_count: int
) -> dict[str, Any]:
    expected_code = {"bfloat16": "BF16", "float32": "F32"}.get(expected_dtype)
    root = Path(model_root)
    files = sorted(root.glob("*.safetensors"))
    if expected_code is None or not files or any(path.is_symlink() for path in files):
        raise FullModelTrainingError("plan090_checkpoint_storage_dtype_invalid")
    tensor_count = 0
    observed: set[str] = set()
    try:
        for path in files:
            size = path.stat().st_size
            with path.open("rb") as handle:
                header_size = struct.unpack("<Q", handle.read(8))[0]
                if header_size <= 0 or header_size > 16 * 1024 * 1024:
                    raise ValueError
                header = json.loads(handle.read(header_size).decode("utf-8"))
            data_bytes = size - 8 - header_size
            if not isinstance(header, Mapping) or data_bytes < 0:
                raise ValueError
            for name, row in header.items():
                if name == "__metadata__":
                    continue
                if (
                    not isinstance(name, str)
                    or not name
                    or not isinstance(row, Mapping)
                    or not isinstance(row.get("dtype"), str)
                    or not isinstance(row.get("shape"), list)
                    or any(
                        not isinstance(item, int) or isinstance(item, bool) or item < 0
                        for item in row["shape"]
                    )
                    or not isinstance(row.get("data_offsets"), list)
                    or len(row["data_offsets"]) != 2
                    or any(
                        not isinstance(item, int) or isinstance(item, bool) or item < 0
                        for item in row["data_offsets"]
                    )
                    or row["data_offsets"][0] > row["data_offsets"][1]
                    or row["data_offsets"][1] > data_bytes
                ):
                    raise ValueError
                tensor_count += 1
                observed.add(row["dtype"])
    except (
        OSError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
        struct.error,
    ) as exc:
        raise FullModelTrainingError(
            "plan090_checkpoint_storage_dtype_invalid"
        ) from exc
    if tensor_count != expected_tensor_count or observed != {expected_code}:
        raise FullModelTrainingError("plan090_checkpoint_storage_dtype_invalid")
    return {
        "tensor_count": tensor_count,
        "storage_dtypes": sorted(observed),
        "verification": "safetensors_headers_and_offsets",
    }


__all__ = [
    "PRECISION_RECEIPT_SCHEMA",
    "Plan090TorchTrainingAdapter",
    "RUNTIME_KIND",
    "validate_confirmation_recipe",
    "verify_safetensors_storage_dtype",
]
