"""Portable, train-only C1/C2/C3 dataset adapter for the Plan 060 bundle."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..render import ADOPTED_CONTEXT_WINDOW
from ..training_data.contract import validate_dataset
from .contract import (
    FullModelTrainingError,
    MODEL_REPOSITORY,
    MODEL_REVISION,
    PORTABLE_INPUT_SCHEMA,
    SMOKE_BUNDLE_SHA256,
    SOURCE_FILES,
    STAGES,
    read_json,
    require_sha256,
    sha256_file,
)


@dataclass(frozen=True)
class StageData:
    name: str
    binary_candidate_ids: tuple[str, ...]
    pair_ids: tuple[str, ...]
    pair_kinds: tuple[str, ...]


@dataclass(frozen=True)
class PortableTrainingDataset:
    dataset_revision: str
    input_identity: Mapping[str, Any]
    rubric: str = field(repr=False)
    packets: Mapping[str, Mapping[str, Any]] = field(repr=False)
    supervision: Mapping[str, Mapping[str, Any]] = field(repr=False)
    pairs: Mapping[str, Mapping[str, Any]] = field(repr=False)
    membership: Mapping[str, Any] = field(repr=False)

    def stage(self, name: str) -> StageData:
        if name not in STAGES:
            raise FullModelTrainingError("stage_name_invalid")
        stage = self.membership["stages"][name]
        candidate_ids = tuple(stage["candidate_ids"])
        pair_ids = tuple(stage["pair_ids"])
        try:
            kinds = tuple(str(self.pairs[pair_id]["kind"]) for pair_id in pair_ids)
        except KeyError as exc:
            raise FullModelTrainingError("stage_pair_missing") from exc
        if any(
            self.supervision[candidate_id]["proposed_split"] != "train"
            for candidate_id in candidate_ids
        ):
            raise FullModelTrainingError("stage_reached_non_train")
        return StageData(
            name=name,
            binary_candidate_ids=candidate_ids,
            pair_ids=pair_ids,
            pair_kinds=kinds,
        )

    def packet(self, candidate_id: str) -> Mapping[str, Any]:
        try:
            return self.packets[candidate_id]["packet"]
        except KeyError as exc:
            raise FullModelTrainingError("candidate_packet_missing") from exc

    def label(self, candidate_id: str) -> str:
        try:
            return str(self.supervision[candidate_id]["binary_label"])
        except KeyError as exc:
            raise FullModelTrainingError("candidate_supervision_missing") from exc

    def pair(self, pair_id: str) -> Mapping[str, Any]:
        try:
            return self.pairs[pair_id]
        except KeyError as exc:
            raise FullModelTrainingError("pair_missing") from exc


def load_portable_dataset(bundle_root: Path) -> PortableTrainingDataset:
    root = Path(bundle_root)
    portable = read_json(root / "contracts/portable-input-v1.json")
    smoke_path = root / "data/train-only-smoke-bundle.json"
    if sha256_file(smoke_path, maximum_bytes=32 * 1024 * 1024) != SMOKE_BUNDLE_SHA256:
        raise FullModelTrainingError("smoke_bundle_hash_mismatch")
    smoke = read_json(smoke_path, maximum_bytes=32 * 1024 * 1024)
    rubric_path = root / "eval/templates/publication-critic/qualification-rubric-v1.md"
    if sha256_file(rubric_path, maximum_bytes=1024 * 1024) != portable.get(
        "qualification_rubric_sha256"
    ):
        raise FullModelTrainingError("portable_rubric_hash_mismatch")
    try:
        rubric = rubric_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FullModelTrainingError("portable_rubric_invalid") from exc
    return dataset_from_values(
        smoke,
        portable,
        rubric=rubric,
        repo_root=root,
    )


def dataset_from_values(
    smoke: Any,
    portable: Any,
    *,
    rubric: str,
    repo_root: Path,
) -> PortableTrainingDataset:
    _validate_portable_contract(portable)
    if not isinstance(smoke, Mapping) or set(smoke) != {
        "schema_version",
        "dataset_revision",
        "source_hashes",
        "packets",
        "supervision",
        "pairs",
        "membership",
    }:
        raise FullModelTrainingError("portable_smoke_shape_invalid")
    if smoke.get("schema_version") != 1 or smoke.get("dataset_revision") != "v7":
        raise FullModelTrainingError("portable_smoke_identity_invalid")
    source_hashes = smoke.get("source_hashes")
    if (
        not isinstance(source_hashes, Mapping)
        or set(source_hashes) != set(SOURCE_FILES)
        or dict(source_hashes) != dict(portable["source_sha256"])
    ):
        raise FullModelTrainingError("portable_source_hashes_invalid")
    packet_rows = _mapping_rows(smoke["packets"], "portable_packets_invalid")
    supervision_rows = _mapping_rows(
        smoke["supervision"], "portable_supervision_invalid"
    )
    pair_rows = _mapping_rows(smoke["pairs"], "portable_pairs_invalid")
    membership = smoke["membership"]
    try:
        validate_dataset(
            packet_rows,
            supervision_rows,
            pair_rows,
            repo_root=repo_root,
            final=True,
            require_review_records=False,
            require_omission_census=False,
        )
    except Exception as exc:
        raise FullModelTrainingError("portable_dataset_contract_invalid") from exc
    expected_membership = _build_membership(
        supervision_rows,
        pair_rows,
        dataset_revision="v7",
    )
    if membership != expected_membership:
        raise FullModelTrainingError("portable_membership_invalid")
    packets = {str(row["candidate_id"]): row for row in packet_rows}
    supervision = {str(row["candidate_id"]): row for row in supervision_rows}
    pairs = {str(row["pair_id"]): row for row in pair_rows}
    labels = {str(row["binary_label"]) for row in supervision_rows}
    kinds = [str(row["kind"]) for row in pair_rows]
    if (
        len(packets) != 6
        or len(supervision) != 6
        or len(pairs) != 2
        or labels != {"PASS", "REWRITE"}
        or kinds.count("boundary") != 1
        or kinds.count("within_pass") != 1
        or any(row["proposed_split"] != "train" for row in supervision_rows)
    ):
        raise FullModelTrainingError("portable_smoke_coverage_invalid")
    dataset = PortableTrainingDataset(
        dataset_revision="v7",
        input_identity=MappingProxyType(dict(portable["input_identity"])),
        rubric=rubric,
        packets=MappingProxyType(packets),
        supervision=MappingProxyType(supervision),
        pairs=MappingProxyType(pairs),
        membership=MappingProxyType(dict(membership)),
    )
    expected_stage_kinds = {
        "C1": (),
        "C2": ("boundary",),
        "C3": ("boundary", "within_pass"),
    }
    for stage_name, expected in expected_stage_kinds.items():
        if dataset.stage(stage_name).pair_kinds != expected:
            raise FullModelTrainingError("portable_stage_coverage_invalid")
    return dataset


def tokenize_dataset(dataset: PortableTrainingDataset, exact_tokenizer: Any) -> dict[str, Any]:
    """Fit every candidate through the frozen tokenizer/window seam exactly once."""

    tokenized: dict[str, Any] = {}
    for candidate_id in sorted(dataset.packets):
        item = exact_tokenizer.fit_packet(
            dataset.packet(candidate_id),
            dataset.rubric,
            adopted_window=int(dataset.input_identity["adopted_window_tokens"]),
        )
        if len(item.input_ids) > ADOPTED_CONTEXT_WINDOW:
            raise FullModelTrainingError("tokenized_candidate_overflow")
        tokenized[candidate_id] = item
    return tokenized


def _validate_portable_contract(value: Any) -> None:
    expected = {
        "schema",
        "dataset_revision",
        "smoke_bundle_sha256",
        "source_sha256",
        "input_identity",
        "qualification_rubric_sha256",
        "render_contract_sha256",
        "product_packet_limits_sha256",
        "model_lock_sha256",
        "model",
        "tokenizer_file_sha256",
    }
    if (
        not isinstance(value, Mapping)
        or set(value) != expected
        or value.get("schema") != PORTABLE_INPUT_SCHEMA
        or value.get("dataset_revision") != "v7"
        or value.get("smoke_bundle_sha256") != SMOKE_BUNDLE_SHA256
    ):
        raise FullModelTrainingError("portable_input_contract_invalid")
    hashes = value.get("source_sha256")
    if not isinstance(hashes, Mapping) or set(hashes) != set(SOURCE_FILES):
        raise FullModelTrainingError("portable_source_identity_invalid")
    for digest in hashes.values():
        require_sha256(digest, "portable_source_identity_invalid")
    for field in (
        "qualification_rubric_sha256",
        "render_contract_sha256",
        "product_packet_limits_sha256",
        "model_lock_sha256",
    ):
        require_sha256(value[field], "portable_input_hash_invalid")
    model = value.get("model")
    if (
        not isinstance(model, Mapping)
        or model.get("repository") != MODEL_REPOSITORY
        or model.get("revision") != MODEL_REVISION
        or model.get("class") != "Qwen3ForSequenceClassification"
        or model.get("num_labels") != 1
        or model.get("parameter_count") != 1_720_577_024
        or model.get("weight_sha256")
        != "117da8e3a6c3e9c9b9b66e74d69373b8f186e7fe27be2d64e0bb18510c9a07d9"
        or model.get("config_file") != "config.json"
        or not isinstance(model.get("config_sha256"), str)
    ):
        raise FullModelTrainingError("portable_model_identity_invalid")
    require_sha256(model["config_sha256"], "portable_model_identity_invalid")
    input_identity = value.get("input_identity")
    if (
        not isinstance(input_identity, Mapping)
        or input_identity.get("tokenizer_revision") != MODEL_REVISION
        or input_identity.get("adopted_window_tokens") != ADOPTED_CONTEXT_WINDOW
        or input_identity.get("candidate_truncation") != "forbidden"
    ):
        raise FullModelTrainingError("portable_plan054_identity_invalid")
    tokenizer_hashes = value.get("tokenizer_file_sha256")
    if not isinstance(tokenizer_hashes, Mapping) or len(tokenizer_hashes) != 7:
        raise FullModelTrainingError("portable_tokenizer_identity_invalid")
    for digest in tokenizer_hashes.values():
        require_sha256(digest, "portable_tokenizer_identity_invalid")


def _mapping_rows(value: Any, code: str) -> list[Mapping[str, Any]]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or any(not isinstance(row, Mapping) for row in value)
    ):
        raise FullModelTrainingError(code)
    return list(value)


def _build_membership(
    supervision_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    *,
    dataset_revision: str,
) -> dict[str, Any]:
    train_candidates = sorted(
        str(row["candidate_id"])
        for row in supervision_rows
        if row["proposed_split"] == "train"
    )
    split_by_candidate = {
        str(row["candidate_id"]): row["proposed_split"] for row in supervision_rows
    }
    boundary: list[str] = []
    within: list[str] = []
    for pair in pair_rows:
        preferred = str(pair["preferred_candidate_id"])
        dispreferred = str(pair["dispreferred_candidate_id"])
        if (
            split_by_candidate.get(preferred) != "train"
            or split_by_candidate.get(dispreferred) != "train"
        ):
            raise FullModelTrainingError("portable_pair_split_invalid")
        if pair["kind"] == "boundary":
            boundary.append(str(pair["pair_id"]))
        elif pair["kind"] == "within_pass":
            within.append(str(pair["pair_id"]))
        else:
            raise FullModelTrainingError("portable_pair_kind_invalid")
    return {
        "schema_version": 1,
        "dataset_revision": dataset_revision,
        "stages": {
            "C1": {"candidate_ids": train_candidates, "pair_ids": []},
            "C2": {"candidate_ids": train_candidates, "pair_ids": sorted(boundary)},
            "C3": {
                "candidate_ids": train_candidates,
                "pair_ids": [*sorted(boundary), *sorted(within)],
            },
        },
    }
