"""Cloud-only guard for the shared exact Skywork scalar backend."""

from __future__ import annotations

import os
from pathlib import Path
import time
from typing import Any

from ..backend import BackendError, SkyworkBackend
from ..tokenization import ExactTokenizer
from .snapshot import verify_snapshot


class Plan079CloudBackend(SkyworkBackend):
    """Use the shared tokenizer/model/scalar path inside an explicit cloud run.

    Local callers still receive the canonical watchdog through
    :class:`SkyworkBackend`.  This subclass is intentionally namespaced to Plan
    079 and requires both the exact snapshot verifier and an explicit cloud
    process marker before the parent loads any model bytes.
    """

    def __init__(self, snapshot: Path, *, model_lock_path: Path, **kwargs: Any) -> None:
        if (
            kwargs.get("device", "cpu") != "cuda"
            or kwargs.get("dtype", "bfloat16") != "bfloat16"
        ):
            raise BackendError("Plan 079 cloud backend requires CUDA BF16")
        self.model_lock_path = model_lock_path
        self.snapshot_receipt: dict[str, Any] | None = None
        self._cloud_guard_started = False
        super().__init__(snapshot, **kwargs)

    def load(self) -> None:
        if os.environ.get("RONDO_PLAN079_CLOUD_RUN") != "1":
            raise BackendError("Plan 079 cloud run marker is absent")
        self.snapshot_receipt = verify_snapshot(self.snapshot, self.model_lock_path)
        self._cloud_guard_started = True
        self._require_lease()
        started = time.perf_counter()
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise BackendError("locked model dependencies are unavailable") from exc
        self.torch = torch
        torch.set_num_threads(self.cpu_threads)
        if not torch.cuda.is_available():
            raise BackendError("requested CUDA device is unavailable")
        device = torch.device("cuda:0")
        try:
            tokenizer = AutoTokenizer.from_pretrained(
                self.snapshot,
                local_files_only=True,
                trust_remote_code=False,
            )
            model = AutoModelForSequenceClassification.from_pretrained(
                self.snapshot,
                local_files_only=True,
                trust_remote_code=False,
                torch_dtype=torch.bfloat16,
            )
        except Exception as exc:
            raise BackendError(
                "exact Skywork model or tokenizer failed to load"
            ) from exc
        config = model.config
        if (
            type(model).__name__ != "Qwen3ForSequenceClassification"
            or config.model_type != "qwen3"
            or config.num_labels != 1
            or config.pad_token_id != 151654
            or config.max_position_embeddings != 40960
        ):
            raise BackendError("exact model configuration drifted")
        model.to(device)
        model.eval()
        self.model = model
        self.device = device
        self.exact_tokenizer = ExactTokenizer(tokenizer)
        self.load_seconds = time.perf_counter() - started
        self._require_lease()

    def _require_lease(self) -> None:
        if (
            not self._cloud_guard_started
            or os.environ.get("RONDO_PLAN079_CLOUD_RUN") != "1"
        ):
            raise BackendError("Plan 079 cloud runtime guard is not active")

    def cloud_runtime_snapshot(self) -> dict[str, str]:
        if self.torch is None or getattr(self, "device", None) is None:
            raise BackendError("Plan 079 cloud backend is not loaded")
        try:
            import transformers
        except ImportError as exc:
            raise BackendError("locked transformers dependency is unavailable") from exc
        capability = self.torch.cuda.get_device_capability(self.device)
        return {
            "torch_version": str(self.torch.__version__),
            "transformers_version": str(transformers.__version__),
            "cuda_runtime_version": str(self.torch.version.cuda),
            "gpu_name": str(self.torch.cuda.get_device_name(self.device)),
            "gpu_capability": f"{capability[0]}.{capability[1]}",
        }
