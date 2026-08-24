"""Plan 066 adapter for the frozen Publication Critic v8 release.

The uploaded body contains train and validation rows only.  Training stages can
only be obtained from ``train``; validation is exposed through a separate type
without a ``stage`` method, and unseen-test bodies are never exported.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any

from ..render import ADOPTED_CONTEXT_WINDOW
from ..training_data import DatasetConsumer
from .contract import FullModelTrainingError, read_json, sha256_file
from .data import PortableTrainingDataset, _build_membership


PLAN066_DATA_SCHEMA = "rondo-publication-critic-plan066-data-v1"
PLAN066_DATA_RELATIVE = "data/plan066-v8-train-validation.json"
PLAN066_PORTABLE_RELATIVE = "contracts/plan066-input-v1.json"
V8_MANIFEST_SHA256 = "70cbbbd1b754227b3c84f9117c1e74ee630713ae12d7041e48522bd751ea5661"
V8_CONTENT_SHA256 = "a9a31a61e0a1e070ee8d076dd313b7efabb5e01ffa42773a841b123a2686cb98"
V8_MEMBERSHIP_SHA256 = "ce04c05eaab49ef04cc335062aefd31f31e7a89857c8321603d70e996661a15f"
V8_SOURCE_FILES = (
    "membership.json",
    "packets.jsonl",
    "pairs.jsonl",
    "supervision.jsonl",
    "token-census.jsonl",
    "train-only-smoke-bundle.json",
)
V8_SOURCE_SHA256 = {
    "membership.json": V8_MEMBERSHIP_SHA256,
    "packets.jsonl": "763f45967cfe172ae862e71a53dfea18be05712d82353785d8b1ca922ee77010",
    "pairs.jsonl": "e567179088d2ba29eaa618b72c8bb49d71da5b79592ec10083a346fac5ff2f03",
    "supervision.jsonl": "99a4a356771c08041bd377743f184c36994687a0e6d50a1858831d9538b1c392",
    "token-census.jsonl": "3bf680c5ef6ff9ad8bd67842e9922da0987edce906d96a05a5b4c10c0b3245e6",
    "train-only-smoke-bundle.json": "0e1e690016fd3f10a47fb4e714dfd00923a9ffcf9e1c022cc1c02177af6a983b",
}


@dataclass(frozen=True)
class ValidationDataset:
    input_identity: Mapping[str, Any]
    rubric: str = field(repr=False)
    packets: Mapping[str, Mapping[str, Any]] = field(repr=False)
    supervision: Mapping[str, Mapping[str, Any]] = field(repr=False)
    pairs: Mapping[str, Mapping[str, Any]] = field(repr=False)

    def packet(self, candidate_id: str) -> Mapping[str, Any]:
        try:
            return self.packets[candidate_id]["packet"]
        except KeyError as exc:
            raise FullModelTrainingError("plan066_validation_packet_missing") from exc

    def label(self, candidate_id: str) -> str:
        try:
            return str(self.supervision[candidate_id]["binary_label"])
        except KeyError as exc:
            raise FullModelTrainingError("plan066_validation_label_missing") from exc


@dataclass(frozen=True)
class Plan066Datasets:
    train: PortableTrainingDataset
    commissioning: PortableTrainingDataset
    validation: ValidationDataset
    source: Mapping[str, Any]
    export_sha256: str


def build_plan066_export(repo_root: Path) -> dict[str, Any]:
    """Derive the bounded remote body from a locally verified v8 freeze."""

    root = Path(repo_root)
    frozen = root / "training/publication-critic-v8"
    manifest_path = frozen / "manifest.json"
    if sha256_file(manifest_path) != V8_MANIFEST_SHA256:
        raise FullModelTrainingError("plan066_v8_manifest_hash_mismatch")
    manifest = read_json(manifest_path)
    if manifest.get("dataset_revision") != "v8" or manifest.get("content_sha256") != V8_CONTENT_SHA256:
        raise FullModelTrainingError("plan066_v8_manifest_identity_mismatch")
    files = manifest.get("files")
    if not isinstance(files, Mapping):
        raise FullModelTrainingError("plan066_v8_manifest_files_invalid")
    for relative, digest in V8_SOURCE_SHA256.items():
        entry = files.get(relative)
        if (
            not isinstance(entry, Mapping)
            or entry.get("sha256") != digest
            or sha256_file(frozen / relative) != digest
        ):
            raise FullModelTrainingError("plan066_v8_source_hash_mismatch", relative)

    # These constructors verify the complete frozen release before any holdout
    # filtering.  Evaluation mode is explicit and never used by stage().
    train_consumer = DatasetConsumer.from_frozen_directory(
        frozen, repo_root=root, allow_evaluation=False
    )
    evaluation_consumer = DatasetConsumer.from_frozen_directory(
        frozen, repo_root=root, allow_evaluation=True
    )
    train_ids = set(train_consumer.supervision)
    validation_ids = {
        str(row["candidate_id"])
        for row in evaluation_consumer.evaluation_split("validation")
    }
    unseen_ids = {
        str(row["candidate_id"])
        for row in evaluation_consumer.evaluation_split("unseen_test")
    }
    if (
        len(train_ids) != 128
        or len(validation_ids) != 55
        or len(unseen_ids) != 45
        or train_ids & validation_ids
        or train_ids & unseen_ids
        or validation_ids & unseen_ids
    ):
        raise FullModelTrainingError("plan066_v8_split_counts_invalid")

    allowed_ids = train_ids | validation_ids
    packets = [
        row
        for candidate_id, row in sorted(evaluation_consumer.packets.items())
        if candidate_id in allowed_ids
    ]
    supervision = [
        row
        for candidate_id, row in sorted(evaluation_consumer.supervision.items())
        if candidate_id in allowed_ids
    ]
    pairs = [
        row
        for _, row in sorted(evaluation_consumer.pairs.items())
        if str(row["preferred_candidate_id"]) in allowed_ids
        and str(row["dispreferred_candidate_id"]) in allowed_ids
    ]
    smoke = read_json(frozen / "train-only-smoke-bundle.json", maximum_bytes=32 * 1024 * 1024)
    token_census = _read_jsonl(frozen / "token-census.jsonl")
    census = {
        str(row["candidate_id"]): {
            "token_count": row["token_count"],
            "rendered_chat_sha256": row["rendered_chat_sha256"],
            "dropped_oldest_publications": row["dropped_oldest_publications"],
        }
        for row in token_census
        if str(row.get("candidate_id")) in allowed_ids
    }
    if len(census) != 183 or any(item["dropped_oldest_publications"] != 0 for item in census.values()):
        raise FullModelTrainingError("plan066_v8_token_census_invalid")
    return {
        "schema": PLAN066_DATA_SCHEMA,
        "dataset_revision": "v8",
        "source": {
            "manifest_file_sha256": V8_MANIFEST_SHA256,
            "manifest_content_sha256": V8_CONTENT_SHA256,
            "files": dict(sorted(V8_SOURCE_SHA256.items())),
        },
        "train": {
            "packets": [row for row in packets if str(row["candidate_id"]) in train_ids],
            "supervision": [row for row in supervision if str(row["candidate_id"]) in train_ids],
            "pairs": [
                row
                for row in pairs
                if str(row["preferred_candidate_id"]) in train_ids
            ],
            "membership": train_consumer.membership,
        },
        "validation": {
            "packets": [row for row in packets if str(row["candidate_id"]) in validation_ids],
            "supervision": [row for row in supervision if str(row["candidate_id"]) in validation_ids],
            "pairs": [
                row
                for row in pairs
                if str(row["preferred_candidate_id"]) in validation_ids
            ],
        },
        "commissioning": smoke,
        "token_census": dict(sorted(census.items())),
        "holdout": {
            "unseen_test_candidate_count": 45,
            "unseen_test_body_files": 0,
            "unseen_test_rows_exported": 0,
        },
    }


def load_plan066_datasets(bundle_root: Path) -> Plan066Datasets:
    root = Path(bundle_root)
    path = root / PLAN066_DATA_RELATIVE
    value = read_json(path, maximum_bytes=32 * 1024 * 1024)
    portable = read_json(root / PLAN066_PORTABLE_RELATIVE)
    return datasets_from_values(
        value,
        portable=portable,
        rubric_path=root / "eval/templates/publication-critic/qualification-rubric-v1.md",
        export_sha256=sha256_file(path),
    )


def datasets_from_values(
    value: Any,
    *,
    portable: Mapping[str, Any],
    rubric_path: Path,
    export_sha256: str,
) -> Plan066Datasets:
    expected = {
        "schema", "dataset_revision", "source", "train", "validation",
        "commissioning", "token_census", "holdout",
    }
    if not isinstance(value, Mapping) or set(value) != expected:
        raise FullModelTrainingError("plan066_data_shape_invalid")
    if value.get("schema") != PLAN066_DATA_SCHEMA or value.get("dataset_revision") != "v8":
        raise FullModelTrainingError("plan066_data_identity_invalid")
    if value.get("source") != {
        "manifest_file_sha256": V8_MANIFEST_SHA256,
        "manifest_content_sha256": V8_CONTENT_SHA256,
        "files": dict(sorted(V8_SOURCE_SHA256.items())),
    }:
        raise FullModelTrainingError("plan066_data_source_invalid")
    if value.get("holdout") != {
        "unseen_test_candidate_count": 45,
        "unseen_test_body_files": 0,
        "unseen_test_rows_exported": 0,
    }:
        raise FullModelTrainingError("plan066_holdout_boundary_invalid")
    input_identity = portable.get("input_identity")
    if (
        portable.get("schema") != "rondo-publication-critic-plan066-input-v1"
        or portable.get("dataset_revision") != "v8"
        or not isinstance(input_identity, Mapping)
        or input_identity.get("adopted_window_tokens") != ADOPTED_CONTEXT_WINDOW
    ):
        raise FullModelTrainingError("plan066_portable_input_invalid")
    if sha256_file(rubric_path) != portable.get("qualification_rubric_sha256"):
        raise FullModelTrainingError("plan066_rubric_hash_mismatch")
    try:
        rubric = rubric_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FullModelTrainingError("plan066_rubric_invalid") from exc
    train = _training_dataset(
        value.get("train"), input_identity=input_identity, rubric=rubric,
        role="formal", expected=(128, 50, 58),
    )
    commissioning = _training_dataset(
        value.get("commissioning"), input_identity=input_identity, rubric=rubric,
        role="commissioning", expected=(6, 1, 2),
    )
    validation = _validation_dataset(
        value.get("validation"), input_identity=input_identity, rubric=rubric
    )
    train_ids = set(train.supervision)
    validation_ids = set(validation.supervision)
    if train_ids & validation_ids:
        raise FullModelTrainingError("plan066_train_validation_overlap")
    census = value.get("token_census")
    if not isinstance(census, Mapping) or set(census) != train_ids | validation_ids:
        raise FullModelTrainingError("plan066_token_census_identity_invalid")
    for candidate_id, item in census.items():
        if (
            not isinstance(item, Mapping)
            or set(item) != {"token_count", "rendered_chat_sha256", "dropped_oldest_publications"}
            or item.get("dropped_oldest_publications") != 0
            or not isinstance(item.get("token_count"), int)
            or item["token_count"] <= 0
            or not _is_sha256(item.get("rendered_chat_sha256"))
        ):
            raise FullModelTrainingError("plan066_token_census_invalid", str(candidate_id))
    return Plan066Datasets(
        train=train,
        commissioning=commissioning,
        validation=validation,
        source=MappingProxyType(dict(value["source"])),
        export_sha256=export_sha256,
    )


def tokenize_validation(dataset: ValidationDataset, exact_tokenizer: Any) -> dict[str, Any]:
    tokenized: dict[str, Any] = {}
    for candidate_id in sorted(dataset.packets):
        item = exact_tokenizer.fit_packet(
            dataset.packet(candidate_id),
            dataset.rubric,
            adopted_window=int(dataset.input_identity["adopted_window_tokens"]),
        )
        if len(item.input_ids) > ADOPTED_CONTEXT_WINDOW:
            raise FullModelTrainingError("plan066_validation_overflow")
        tokenized[candidate_id] = item
    return tokenized


def _training_dataset(
    value: Any,
    *,
    input_identity: Mapping[str, Any],
    rubric: str,
    role: str,
    expected: tuple[int, int, int],
) -> PortableTrainingDataset:
    if not isinstance(value, Mapping):
        raise FullModelTrainingError("plan066_training_rows_invalid")
    required = {"packets", "supervision", "pairs", "membership"}
    if role == "commissioning":
        required |= {"schema_version", "dataset_revision", "source_hashes"}
    if set(value) != required:
        raise FullModelTrainingError("plan066_training_rows_invalid")
    if role == "commissioning" and (
        value.get("schema_version") != 1
        or value.get("dataset_revision") != "v8"
        or value.get("source_hashes")
        != {
            relative: V8_SOURCE_SHA256[relative]
            for relative in (
                "membership.json", "packets.jsonl", "pairs.jsonl", "supervision.jsonl"
            )
        }
    ):
        raise FullModelTrainingError("plan066_commissioning_identity_invalid")
    packets = _rows_by_id(value.get("packets"), "candidate_id", "plan066_packets_invalid")
    supervision = _rows_by_id(value.get("supervision"), "candidate_id", "plan066_supervision_invalid")
    pairs = _rows_by_id(value.get("pairs"), "pair_id", "plan066_pairs_invalid")
    if set(packets) != set(supervision):
        raise FullModelTrainingError("plan066_candidate_rows_mismatch")
    if any(row.get("proposed_split") != "train" for row in supervision.values()):
        raise FullModelTrainingError("plan066_training_reached_holdout")
    membership = value.get("membership")
    expected_membership = _build_membership(
        list(supervision.values()), list(pairs.values()), dataset_revision="v8"
    )
    if membership != expected_membership:
        raise FullModelTrainingError("plan066_membership_invalid")
    dataset = PortableTrainingDataset(
        dataset_revision="v8",
        input_identity=MappingProxyType(dict(input_identity)),
        rubric=rubric,
        packets=MappingProxyType(packets),
        supervision=MappingProxyType(supervision),
        pairs=MappingProxyType(pairs),
        membership=MappingProxyType(dict(membership)),
    )
    candidate_count, c2_pairs, c3_pairs = expected
    if (
        len(dataset.supervision) != candidate_count
        or len(dataset.stage("C2").pair_ids) != c2_pairs
        or len(dataset.stage("C3").pair_ids) != c3_pairs
        or any(kind != "boundary" for kind in dataset.stage("C2").pair_kinds)
        or dataset.stage("C3").pair_kinds.count("boundary") != c2_pairs
        or dataset.stage("C3").pair_kinds.count("within_pass") != c3_pairs - c2_pairs
    ):
        raise FullModelTrainingError(f"plan066_{role}_coverage_invalid")
    return dataset


def _validation_dataset(
    value: Any, *, input_identity: Mapping[str, Any], rubric: str
) -> ValidationDataset:
    if not isinstance(value, Mapping) or set(value) != {"packets", "supervision", "pairs"}:
        raise FullModelTrainingError("plan066_validation_rows_invalid")
    packets = _rows_by_id(value.get("packets"), "candidate_id", "plan066_validation_packets_invalid")
    supervision = _rows_by_id(value.get("supervision"), "candidate_id", "plan066_validation_supervision_invalid")
    pairs = _rows_by_id(value.get("pairs"), "pair_id", "plan066_validation_pairs_invalid")
    if (
        set(packets) != set(supervision)
        or len(supervision) != 55
        or len(pairs) != 26
        or any(row.get("proposed_split") != "validation" for row in supervision.values())
        or sum(row.get("kind") == "boundary" for row in pairs.values()) != 19
        or sum(row.get("kind") == "within_pass" for row in pairs.values()) != 7
    ):
        raise FullModelTrainingError("plan066_validation_coverage_invalid")
    for pair in pairs.values():
        if (
            str(pair.get("preferred_candidate_id")) not in supervision
            or str(pair.get("dispreferred_candidate_id")) not in supervision
        ):
            raise FullModelTrainingError("plan066_validation_pair_endpoint_invalid")
    return ValidationDataset(
        input_identity=MappingProxyType(dict(input_identity)),
        rubric=rubric,
        packets=MappingProxyType(packets),
        supervision=MappingProxyType(supervision),
        pairs=MappingProxyType(pairs),
    )


def _rows_by_id(value: Any, field: str, code: str) -> dict[str, Mapping[str, Any]]:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes, bytearray))
        or any(not isinstance(row, Mapping) for row in value)
    ):
        raise FullModelTrainingError(code)
    result: dict[str, Mapping[str, Any]] = {}
    for row in value:
        identifier = row.get(field)
        if not isinstance(identifier, str) or not identifier or identifier in result:
            raise FullModelTrainingError(code)
        result[identifier] = row
    return result


def _read_jsonl(path: Path) -> list[Mapping[str, Any]]:
    rows: list[Mapping[str, Any]] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            value = json.loads(line)
            if not isinstance(value, Mapping):
                raise ValueError("row is not an object")
            rows.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise FullModelTrainingError("plan066_v8_jsonl_invalid", path.name) from exc
    return rows


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
