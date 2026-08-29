"""Typed v10 train/validation access and exact-input preparation for Plan 099."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..directional_data import DevelopmentRelease
from ..successor_task import HARD_DIMENSIONS
from ..tokenization import ExactTokenizer, TokenizedInput
from .contract import FullModelTrainingError, canonical_json_bytes, sha256_file
from .plan099_contract import REPO_ROOT, V10_ROOT, load_freeze


DATASET_SCHEMA = "rondo-publication-critic-plan099-dataset-v1"
TOKENIZED_SCHEMA = "rondo-publication-critic-plan099-tokenized-dataset-v1"
FEATURE_CACHE_SCHEMA = "rondo-publication-critic-plan099-feature-cache-identity-v1"


@dataclass(frozen=True)
class Plan099Dataset:
    split: str
    candidates: tuple[Mapping[str, Any], ...]
    pairs: tuple[Mapping[str, Any], ...]
    rubric: str
    manifest_sha256: str
    candidates_sha256: str
    pairs_sha256: str

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(str(row["candidate_id"]) for row in self.candidates)

    @property
    def labels_by_id(self) -> dict[str, dict[str, str]]:
        return {
            str(row["candidate_id"]): dict(row["labels"]) for row in self.candidates
        }

    def identity(self) -> dict[str, Any]:
        core = {
            "schema": DATASET_SCHEMA,
            "split": self.split,
            "candidate_ids": list(self.candidate_ids),
            "candidate_rows": len(self.candidates),
            "pair_ids": [str(row["pair_id"]) for row in self.pairs],
            "pair_rows": len(self.pairs),
            "manifest_sha256": self.manifest_sha256,
            "candidates_sha256": self.candidates_sha256,
            "pairs_sha256": self.pairs_sha256,
        }
        return {
            **core,
            "content_sha256": hashlib.sha256(canonical_json_bytes(core)).hexdigest(),
        }


@dataclass(frozen=True)
class TokenizedDataset:
    dataset: Plan099Dataset
    inputs: tuple[TokenizedInput, ...]
    identity: Mapping[str, Any]


def load_train_dataset(repo_root: Path | str = REPO_ROOT) -> Plan099Dataset:
    return _load_dataset("train", Path(repo_root))


def load_validation_dataset(repo_root: Path | str = REPO_ROOT) -> Plan099Dataset:
    """The only Plan 099 validation entrypoint; never exposes test/qualification."""

    return _load_dataset("validation", Path(repo_root))


def commissioning_dataset(
    train: Plan099Dataset,
    *,
    boundary_dimensions: Sequence[str] = HARD_DIMENSIONS,
) -> Plan099Dataset:
    """Select one boundary per hard head plus one soft pair deterministically."""

    if train.split != "train":
        raise FullModelTrainingError("plan099_commissioning_requires_train")
    selected = []
    for dimension in boundary_dimensions:
        matches = [
            row
            for row in train.pairs
            if row["kind"] == "boundary" and row["target_dimension"] == dimension
        ]
        if not matches:
            raise FullModelTrainingError(
                "plan099_commissioning_pair_missing", dimension
            )
        selected.append(matches[0])
    soft = [row for row in train.pairs if row["kind"] == "soft_only_invariance"]
    if not soft:
        raise FullModelTrainingError("plan099_commissioning_pair_missing", "soft")
    selected.append(soft[0])
    endpoint_ids = {
        str(candidate_id)
        for pair in selected
        for candidate_id in (pair["left_candidate_id"], pair["right_candidate_id"])
    }
    candidates = tuple(
        row for row in train.candidates if row["candidate_id"] in endpoint_ids
    )
    if len(candidates) != len(endpoint_ids):
        raise FullModelTrainingError("plan099_commissioning_endpoint_missing")
    return Plan099Dataset(
        split="commissioning",
        candidates=candidates,
        pairs=tuple(selected),
        rubric=train.rubric,
        manifest_sha256=train.manifest_sha256,
        candidates_sha256=train.candidates_sha256,
        pairs_sha256=train.pairs_sha256,
    )


def tokenize_dataset(
    dataset: Plan099Dataset,
    tokenizer: ExactTokenizer,
    *,
    model_input_identity: Mapping[str, Any],
) -> TokenizedDataset:
    adopted_window = int(model_input_identity.get("adopted_window_tokens", 0))
    if adopted_window != 16_384:
        raise FullModelTrainingError("plan099_input_window_invalid")
    inputs = tuple(
        tokenizer.fit_packet(
            row["packet"], dataset.rubric, adopted_window=adopted_window
        )
        for row in dataset.candidates
    )
    rows = [
        {
            "candidate_id": candidate_id,
            "rendered_chat_sha256": hashlib.sha256(
                item.rendered_chat.encode("utf-8")
            ).hexdigest(),
            "input_ids_sha256": hashlib.sha256(
                canonical_json_bytes(list(item.input_ids))
            ).hexdigest(),
            "token_count": len(item.input_ids),
        }
        for candidate_id, item in zip(dataset.candidate_ids, inputs, strict=True)
    ]
    core = {
        "schema": TOKENIZED_SCHEMA,
        "dataset": dataset.identity(),
        "model_input_identity": json.loads(json.dumps(model_input_identity)),
        "rows": rows,
    }
    identity = {
        **core,
        "content_sha256": hashlib.sha256(canonical_json_bytes(core)).hexdigest(),
    }
    return TokenizedDataset(dataset=dataset, inputs=inputs, identity=identity)


def feature_cache_identity(
    tokenized: TokenizedDataset,
    *,
    model_identity_sha256: str,
    feature_shape: Sequence[int],
    feature_dtype: str,
    feature_content_sha256: str,
) -> dict[str, Any]:
    if (
        len(model_identity_sha256) != 64
        or any(
            character not in "0123456789abcdef" for character in model_identity_sha256
        )
        or tuple(feature_shape) != (len(tokenized.inputs), 2048)
        or feature_dtype != "bfloat16"
        or len(feature_content_sha256) != 64
        or any(
            character not in "0123456789abcdef" for character in feature_content_sha256
        )
    ):
        raise FullModelTrainingError("plan099_feature_cache_identity_invalid")
    core = {
        "schema": FEATURE_CACHE_SCHEMA,
        "tokenized_dataset_sha256": tokenized.identity["content_sha256"],
        "candidate_ids": list(tokenized.dataset.candidate_ids),
        "model_identity_sha256": model_identity_sha256,
        "feature_shape": list(feature_shape),
        "feature_dtype": feature_dtype,
        "feature_content_sha256": feature_content_sha256,
    }
    return {
        **core,
        "content_sha256": hashlib.sha256(canonical_json_bytes(core)).hexdigest(),
    }


def _load_dataset(split: str, root: Path) -> Plan099Dataset:
    if split not in {"train", "validation"}:
        raise FullModelTrainingError("plan099_split_forbidden", split)
    freeze = load_freeze(root)
    release = DevelopmentRelease.open(root / V10_ROOT, repo_root=root)
    candidates, pairs = (
        release.load_train() if split == "train" else release.load_validation()
    )
    expected = freeze["data"]
    candidates_digest = sha256_file(
        root / V10_ROOT / f"splits/{split}/candidates.jsonl"
    )
    pairs_digest = sha256_file(root / V10_ROOT / f"splits/{split}/pairs.jsonl")
    if candidates_digest != expected[f"{split}_candidates_sha256"]:
        raise FullModelTrainingError("plan099_candidate_identity_drifted")
    if pairs_digest != expected[f"{split}_pairs_sha256"]:
        raise FullModelTrainingError("plan099_pair_identity_drifted")
    rubric_path = root / freeze["model"]["input"]["rubric"]
    rubric = rubric_path.read_text(encoding="utf-8")
    return Plan099Dataset(
        split=split,
        candidates=candidates,
        pairs=pairs,
        rubric=rubric,
        manifest_sha256=expected["manifest_sha256"],
        candidates_sha256=candidates_digest,
        pairs_sha256=pairs_digest,
    )


__all__ = [
    "Plan099Dataset",
    "TokenizedDataset",
    "commissioning_dataset",
    "feature_cache_identity",
    "load_train_dataset",
    "load_validation_dataset",
    "tokenize_dataset",
]
