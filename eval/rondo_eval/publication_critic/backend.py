"""Exact local Skywork scalar backend, loaded only inside the RONDO watchdog."""

import math
import resource
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from rondo_eval.runtime_bridge import RuntimeBridgeError, WatchdogProof, lease_from_watchdog

from .scoring import project_logit
from .tokenization import ExactTokenizer, TokenizedInput


class BackendError(RuntimeError):
    """A typed, body-free model loading or scalar contract failure."""


@dataclass(frozen=True)
class ScoreOutput:
    raw_logit: float
    score: float
    batch_elapsed_ms: float
    batch_size: int

    @property
    def amortized_batch_compute_ms(self) -> float:
        return self.batch_elapsed_ms / self.batch_size


class SkyworkBackend:
    def __init__(
        self,
        snapshot: Path,
        *,
        device: str = "cpu",
        dtype: str = "bfloat16",
        cpu_threads: int = 4,
    ) -> None:
        self.snapshot = snapshot
        self.device_name = device
        self.dtype_name = dtype
        self.cpu_threads = cpu_threads
        self.proof: WatchdogProof | None = None
        self.torch: Any = None
        self.model: Any = None
        self.exact_tokenizer: ExactTokenizer | None = None
        self.load_seconds: float | None = None

    def load(self) -> None:
        self.proof = lease_from_watchdog()
        self._require_lease()
        if not self.snapshot.is_dir() or self.snapshot.is_symlink():
            raise BackendError("exact model snapshot is missing or unsafe")
        started = time.perf_counter()
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise BackendError("locked model dependencies are unavailable") from exc
        self.torch = torch
        torch.set_num_threads(self.cpu_threads)
        if self.device_name == "cuda":
            if not torch.cuda.is_available():
                raise BackendError("requested CUDA device is unavailable")
            device = torch.device("cuda:0")
        elif self.device_name == "cpu":
            device = torch.device("cpu")
        else:
            raise BackendError("device is not supported by the Plan 054 runner")
        dtype_by_name = {
            "bfloat16": torch.bfloat16,
            "float32": torch.float32,
        }
        try:
            model_dtype = dtype_by_name[self.dtype_name]
        except KeyError as exc:
            raise BackendError("dtype is not supported by the Plan 054 runner") from exc
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
                torch_dtype=model_dtype,
            )
        except Exception as exc:
            raise BackendError("exact Skywork model or tokenizer failed to load") from exc
        if type(model).__name__ != "Qwen3ForSequenceClassification":
            raise BackendError("exact model class drifted")
        config = model.config
        if (
            config.model_type != "qwen3"
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

    def score(self, inputs: Sequence[TokenizedInput], *, padding_side: str = "right") -> list[ScoreOutput]:
        if self.model is None or self.exact_tokenizer is None or self.torch is None:
            raise BackendError("model is not loaded")
        if not inputs:
            raise BackendError("model batch is empty")
        if padding_side not in {"left", "right"}:
            raise BackendError("padding side is invalid")
        self._require_lease()
        tokenizer = self.exact_tokenizer.tokenizer
        original_side = tokenizer.padding_side
        tokenizer.padding_side = padding_side
        try:
            batch = tokenizer.pad(
                {"input_ids": [list(item.input_ids) for item in inputs]},
                padding=True,
                return_attention_mask=True,
                return_tensors="pt",
            )
        finally:
            tokenizer.padding_side = original_side
        batch = {name: tensor.to(self.device) for name, tensor in batch.items()}
        started = time.perf_counter()
        with self.torch.inference_mode():
            output = self.model(**batch)
        if self.device.type == "cuda":
            self.torch.cuda.synchronize(self.device)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        logits = output.logits
        if tuple(logits.shape) != (len(inputs), 1):
            raise BackendError("exact model returned an invalid scalar shape")
        raw = [float(value) for value in logits[:, 0].float().cpu().tolist()]
        if any(not math.isfinite(value) for value in raw):
            raise BackendError("exact model returned a non-finite scalar")
        self._require_lease()
        return [
            ScoreOutput(
                raw_logit=value,
                score=project_logit(value),
                batch_elapsed_ms=elapsed_ms,
                batch_size=len(inputs),
            )
            for value in raw
        ]

    def verify_context_forward(self, token_count: int) -> dict[str, Any]:
        """Verify model mechanics at the adopted length with synthetic tokens.

        This is explicitly not a PublicationPacket score and is never included
        in quality metrics.
        """

        if self.model is None or self.exact_tokenizer is None or self.torch is None:
            raise BackendError("model is not loaded")
        seed = self.exact_tokenizer.tokenizer.encode(
            "bounded context window mechanical smoke ",
            add_special_tokens=False,
        )
        if not seed:
            raise BackendError("context smoke seed is empty")
        input_ids = (seed * (token_count // len(seed) + 1))[:token_count]
        tensor = self.torch.tensor([input_ids], dtype=self.torch.long, device=self.device)
        mask = self.torch.ones_like(tensor)
        self._require_lease()
        started = time.perf_counter()
        with self.torch.inference_mode():
            logits = self.model(input_ids=tensor, attention_mask=mask).logits
        if self.device.type == "cuda":
            self.torch.cuda.synchronize(self.device)
        if tuple(logits.shape) != (1, 1) or not math.isfinite(float(logits[0, 0])):
            raise BackendError("context smoke did not return one finite scalar")
        self._require_lease()
        return {
            "kind": "synthetic_token_context_mechanical_smoke",
            "token_count": token_count,
            "latency_ms": (time.perf_counter() - started) * 1000.0,
            "output_shape": [1, 1],
            "finite": True,
        }

    def resource_snapshot(self) -> dict[str, Any]:
        try:
            import psutil

            rss = psutil.Process().memory_info().rss
        except Exception as exc:
            raise BackendError("process RSS counter is unavailable") from exc
        cuda = None
        if self.torch is not None and getattr(self, "device", None) is not None and self.device.type == "cuda":
            cuda = {
                "allocated_bytes": int(self.torch.cuda.memory_allocated(self.device)),
                "reserved_bytes": int(self.torch.cuda.memory_reserved(self.device)),
                "max_allocated_bytes": int(self.torch.cuda.max_memory_allocated(self.device)),
                "max_reserved_bytes": int(self.torch.cuda.max_memory_reserved(self.device)),
            }
        return {
            "process_rss_bytes": rss,
            "process_peak_rss_bytes": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024,
            "cuda": cuda,
        }

    def _require_lease(self) -> None:
        proof = self.proof
        if proof is None or proof.guard.is_held(proof.lease) is not True:
            raise BackendError("RONDO watchdog lease is not held")


def body_free_exception(exc: BaseException) -> dict[str, str]:
    if isinstance(exc, (BackendError, RuntimeBridgeError)):
        return {"failure_kind": type(exc).__name__, "message": str(exc)}
    return {"failure_kind": type(exc).__name__, "message": "unexpected model runner failure"}
