"""Shared Plan 068 offline/worker inference over the frozen Plan 054 core."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol, Sequence

from ..backend import ScoreOutput, SkyworkBackend
from ..contract import REPO_ROOT, load_fixed_input_contract, load_sample_corpus
from ..tokenization import TokenizedInput


class InferenceError(RuntimeError):
    """A body-free Plan 068 inference orchestration failure."""


class Backend(Protocol):
    exact_tokenizer: Any
    load_seconds: float | None

    def load(self) -> None: ...

    def score(
        self,
        inputs: Sequence[TokenizedInput],
        *,
        padding_side: str = "right",
    ) -> list[ScoreOutput]: ...

    def resource_snapshot(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class InferenceResult:
    sample_id: str | None
    raw_logit: float
    projected_score: float
    token_count: int
    dropped_oldest_publications: int
    model_elapsed_ms: float


class PublicationCriticInference:
    """Loads one artifact and applies the exact frozen packet-to-scalar path."""

    def __init__(
        self,
        snapshot: Path,
        *,
        repo_root: Path = REPO_ROOT,
        device: str = "cuda",
        dtype: str = "bfloat16",
        cpu_threads: int = 4,
        backend_factory: Callable[..., Backend] = SkyworkBackend,
    ) -> None:
        self.repo_root = repo_root
        self.fixed = load_fixed_input_contract(repo_root)
        self.backend = backend_factory(
            snapshot,
            device=device,
            dtype=dtype,
            cpu_threads=cpu_threads,
        )

    def load(self) -> None:
        self.backend.load()
        if self.backend.exact_tokenizer is None or self.backend.load_seconds is None:
            raise InferenceError("model backend did not reach a ready state")

    @property
    def load_seconds(self) -> float:
        value = self.backend.load_seconds
        if value is None:
            raise InferenceError("model backend is not loaded")
        return float(value)

    def score_packet(
        self,
        packet: Mapping[str, Any],
        *,
        sample_id: str | None = None,
    ) -> InferenceResult:
        tokenizer = self.backend.exact_tokenizer
        if tokenizer is None:
            raise InferenceError("model backend is not loaded")
        tokenized = tokenizer.fit_packet(packet, self.fixed.rubric)
        outputs = self.backend.score([tokenized], padding_side="right")
        if len(outputs) != 1:
            raise InferenceError("model backend did not return one scalar")
        output = outputs[0]
        return InferenceResult(
            sample_id=sample_id,
            raw_logit=output.raw_logit,
            projected_score=output.score,
            token_count=len(tokenized.input_ids),
            dropped_oldest_publications=tokenized.plan.dropped_oldest_publications,
            model_elapsed_ms=output.batch_elapsed_ms,
        )

    def score_frozen_cohort(self, sample_ids: Sequence[str]) -> list[dict[str, Any]]:
        corpus = load_sample_corpus(self.repo_root).by_id
        if len(set(sample_ids)) != len(sample_ids):
            raise InferenceError("qualification cohort contains duplicate sample identity")
        rows: list[dict[str, Any]] = []
        for sample_id in sample_ids:
            try:
                sample = corpus[sample_id]
            except KeyError as exc:
                raise InferenceError("qualification cohort contains an unknown sample") from exc
            rows.append(asdict(self.score_packet(sample.packet, sample_id=sample_id)))
        return rows

    def resource_snapshot(self) -> dict[str, Any]:
        return self.backend.resource_snapshot()
