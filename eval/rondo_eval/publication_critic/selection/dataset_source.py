"""Where each Plan 073 split is read from, and what may open it.

Validation is read from the Plan 066 ``train+validation`` bundle, which is a
frozen asset that physically contains no unseen-test row or body.  The mixed v8
JSONL files are never opened on the validation path: not by the manifest
verifier, not by a streaming filter, not at all.  Only an unseen-test release,
which requires a valid selection lock, opens the mixed frozen dataset.

Integrity does not drop as a result.  The bundle is bound to the same frozen v8
manifest the selection freeze names, and its train+validation rows are handed to
the existing ``DatasetConsumer``, so the full cross-row packet/supervision
projection, pair semantics and omission-applicability checks still run.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from ..contract import REPO_ROOT
from ..full_model_training.contract import FullModelTrainingError
from ..full_model_training.plan066_bundle import verify_plan066_bundle
from ..full_model_training.plan066_data import (
    PLAN066_DATA_RELATIVE,
    PLAN066_DATA_SCHEMA,
    V8_MANIFEST_SHA256,
    load_plan066_datasets,
)
from ..identity import sha256_file
from ..training_data.consumer import DatasetConsumer, build_memberships
from ..training_data.contract import validate_pair_row, validate_supervision_row
from ..training_data.freeze import verify_freeze_manifest
from ..training_data.input_identity import load_plan054_training_input
from .contract import SPLITS, SelectionError
from .lock import lock_sha256, validate_lock


VALIDATION_SPLIT = "validation"
UNSEEN_SPLIT = "unseen_test"

MANIFEST_RELATIVE = "manifest.json"
PACKETS_RELATIVE = "packets.jsonl"
SUPERVISION_RELATIVE = "supervision.jsonl"
PAIRS_RELATIVE = "pairs.jsonl"
CENSUS_RELATIVE = "token-census.jsonl"
_REQUIRED_FILES = (
    PACKETS_RELATIVE,
    SUPERVISION_RELATIVE,
    PAIRS_RELATIVE,
    CENSUS_RELATIVE,
)

# This is the immutable train+validation projection used by Plan 066 and the
# Plan 073 formal run.  The canonical bundle verifier binds the complete bundle
# and its v8 source identity; this digest additionally pins the body projection
# itself so a self-consistent, re-hashed substitute cannot stand in for it.
PLAN066_DATA_SHA256 = "5b887f60ec803c29b7711b98614863876df4e60087e942b84f6bdc202af851cf"


@dataclass(frozen=True)
class SplitSource:
    """Exactly one frozen split, plus the identity it was read under."""

    split: str
    dataset_revision: str
    manifest_sha256: str
    authorization: Mapping[str, Any]
    origin: str
    packets: Mapping[str, Mapping[str, Any]]
    supervision: Mapping[str, Mapping[str, Any]]
    pairs: tuple[Mapping[str, Any], ...]
    dropped_oldest_publications: Mapping[str, int]

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.supervision))


def load_split(
    dataset_root: Path,
    split: str,
    *,
    repo_root: Path = REPO_ROOT,
    bundle_root: Path | None = None,
    selection_lock: Mapping[str, Any] | None = None,
) -> SplitSource:
    """Read one split from the source that split is allowed to come from."""

    if split not in SPLITS:
        raise SelectionError("Plan 073 release split is invalid")
    if split == VALIDATION_SPLIT:
        if selection_lock is not None:
            raise SelectionError("validation release does not consume a selection lock")
        if bundle_root is None:
            raise SelectionError(
                "validation must be read from the unseen-free frozen bundle"
            )
        return _load_validation_from_bundle(bundle_root, repo_root=repo_root)
    if selection_lock is None:
        raise SelectionError(
            "unseen-test release requires a valid Plan 073 selection lock"
        )
    return _load_unseen_from_frozen_dataset(
        dataset_root,
        repo_root=repo_root,
        selection_lock=selection_lock,
    )


# --------------------------------------------------------- validation ----


def _load_validation_from_bundle(bundle_root: Path, *, repo_root: Path) -> SplitSource:
    root = _safe_root(bundle_root)
    try:
        verify_plan066_bundle(root)
        datasets = load_plan066_datasets(root)
    except FullModelTrainingError as exc:
        raise SelectionError("Plan 066 bundle identity is invalid") from exc
    if datasets.export_sha256 != PLAN066_DATA_SHA256:
        raise SelectionError("Plan 066 validation projection identity drifted")

    data_path = root / PLAN066_DATA_RELATIVE
    _require_regular_file(data_path)
    data = _load_json_object(data_path)
    if data.get("schema") != PLAN066_DATA_SCHEMA:
        raise SelectionError("Plan 066 bundle data schema is invalid")
    holdout = data.get("holdout")
    if (
        not isinstance(holdout, Mapping)
        or holdout.get("unseen_test_rows_exported") != 0
        or holdout.get("unseen_test_body_files") != 0
    ):
        raise SelectionError("Plan 066 bundle does not declare unseen-test excluded")

    train = _bundle_section(data, "train")
    validation = _bundle_section(data, VALIDATION_SPLIT)
    packet_rows = [*train["packets"], *validation["packets"]]
    supervision_rows = [*train["supervision"], *validation["supervision"]]
    pair_rows = [*train["pairs"], *validation["pairs"]]
    if any(
        row.get("proposed_split") == UNSEEN_SPLIT for row in supervision_rows
    ):
        raise SelectionError("Plan 066 bundle unexpectedly carries an unseen-test row")

    census = _bundle_census(data)
    dataset_revision = str(data.get("dataset_revision") or "")
    if not dataset_revision:
        raise SelectionError("Plan 066 bundle dataset revision is invalid")

    # The existing consumer keeps the whole cross-row contract: packet and
    # supervision projection, pair semantics and omission applicability.
    consumer = DatasetConsumer.from_rows(
        packet_rows,
        supervision_rows,
        pair_rows,
        build_memberships(
            supervision_rows, pair_rows, dataset_revision=dataset_revision
        ),
        repo_root=repo_root,
        allow_evaluation=True,
        dropped_oldest_publications=census,
    )
    members = {
        candidate_id
        for candidate_id, row in consumer.supervision.items()
        if row["proposed_split"] == VALIDATION_SPLIT
    }
    if not members:
        raise SelectionError("Plan 073 release split is empty")
    return SplitSource(
        split=VALIDATION_SPLIT,
        dataset_revision=dataset_revision,
        manifest_sha256=V8_MANIFEST_SHA256,
        authorization={"kind": "frozen_protocol_split", "selection_lock_sha256": None},
        origin="plan066-train-validation-bundle-v1",
        packets={
            candidate_id: consumer.packets[candidate_id] for candidate_id in members
        },
        supervision={
            candidate_id: consumer.supervision[candidate_id] for candidate_id in members
        },
        pairs=tuple(
            sorted(
                (
                    row
                    for row in consumer.pairs.values()
                    if str(row["preferred_candidate_id"]) in members
                    and str(row["dispreferred_candidate_id"]) in members
                ),
                key=lambda row: str(row["pair_id"]),
            )
        ),
        dropped_oldest_publications={
            candidate_id: consumer.dropped_oldest_publications(candidate_id)
            for candidate_id in members
        },
    )

def _bundle_section(data: Mapping[str, Any], name: str) -> dict[str, list[Any]]:
    section = data.get(name)
    if not isinstance(section, Mapping):
        raise SelectionError(f"Plan 066 bundle section is invalid: {name}")
    result: dict[str, list[Any]] = {}
    for key in ("packets", "supervision", "pairs"):
        rows = section.get(key)
        if not isinstance(rows, list):
            raise SelectionError(f"Plan 066 bundle rows are invalid: {name}.{key}")
        result[key] = rows
    return result


def _bundle_census(data: Mapping[str, Any]) -> dict[str, int]:
    census = data.get("token_census")
    if not isinstance(census, Mapping) or not census:
        raise SelectionError("Plan 066 bundle token census is invalid")
    result: dict[str, int] = {}
    for candidate_id, row in census.items():
        value = row.get("dropped_oldest_publications") if isinstance(row, Mapping) else None
        if not isinstance(candidate_id, str) or type(value) is not int or value < 0:
            raise SelectionError("Plan 066 bundle census omission count is invalid")
        result[str(candidate_id)] = value
    return result


# ------------------------------------------------------------- unseen ----


def _load_unseen_from_frozen_dataset(
    dataset_root: Path,
    *,
    repo_root: Path,
    selection_lock: Mapping[str, Any],
) -> SplitSource:
    """Only reachable once a valid selection lock exists."""

    authorization = {
        "kind": "selection_lock",
        "selection_lock_sha256": lock_sha256(validate_lock(selection_lock)),
    }
    root = _safe_root(dataset_root)
    manifest_path = root / MANIFEST_RELATIVE
    _require_regular_file(manifest_path)
    manifest = _load_json_object(manifest_path)
    verify_freeze_manifest(
        root,
        manifest,
        expected_input_identity=load_plan054_training_input(repo_root).input_identity,
    )
    if not set(_REQUIRED_FILES) <= set(manifest["files"]):
        raise SelectionError("Plan 073 freeze manifest does not bind every split input")

    members: set[str] = set()
    supervision: dict[str, Mapping[str, Any]] = {}
    for row in _stream_jsonl(root / SUPERVISION_RELATIVE):
        validate_supervision_row(row, final=True)
        candidate_id = str(row["candidate_id"])
        if row["proposed_split"] != UNSEEN_SPLIT:
            continue
        if candidate_id in supervision:
            raise SelectionError("Plan 073 split supervision identity is duplicated")
        members.add(candidate_id)
        supervision[candidate_id] = row
    if not members:
        raise SelectionError("Plan 073 release split is empty")

    packet_rows = [
        row
        for row in _stream_jsonl(root / PACKETS_RELATIVE)
        if str(row.get("candidate_id")) in members
    ]
    pair_rows = [
        row
        for row in _stream_jsonl(root / PAIRS_RELATIVE)
        if str(row.get("preferred_candidate_id")) in members
        or str(row.get("dispreferred_candidate_id")) in members
    ]
    for row in pair_rows:
        validate_pair_row(row, final=True)
        if (
            str(row["preferred_candidate_id"]) not in members
            or str(row["dispreferred_candidate_id"]) not in members
        ):
            raise SelectionError("Plan 073 frozen pair crosses the split boundary")
    omissions: dict[str, int] = {}
    for row in _stream_jsonl(root / CENSUS_RELATIVE):
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id not in members:
            continue
        value = row.get("dropped_oldest_publications")
        if type(value) is not int or value < 0 or candidate_id in omissions:
            raise SelectionError("Plan 073 split census omission count is invalid")
        omissions[candidate_id] = value
    if set(omissions) != members:
        raise SelectionError("Plan 073 split census does not cover the split")

    consumer = DatasetConsumer.from_rows(
        packet_rows,
        list(supervision.values()),
        pair_rows,
        build_memberships(
            list(supervision.values()),
            pair_rows,
            dataset_revision=str(manifest["dataset_revision"]),
        ),
        repo_root=repo_root,
        allow_evaluation=True,
        dropped_oldest_publications=omissions,
    )
    return SplitSource(
        split=UNSEEN_SPLIT,
        dataset_revision=str(manifest["dataset_revision"]),
        manifest_sha256=sha256_file(manifest_path),
        authorization=authorization,
        origin="frozen-v8-under-selection-lock-v1",
        packets=dict(consumer.packets),
        supervision=dict(consumer.supervision),
        pairs=tuple(
            sorted(consumer.pairs.values(), key=lambda row: str(row["pair_id"]))
        ),
        dropped_oldest_publications=omissions,
    )


# -------------------------------------------------------------- utils ----


def _safe_root(root: Path) -> Path:
    if root.is_symlink() or not root.is_dir():
        raise SelectionError("Plan 073 dataset root is missing or unsafe")
    return root


def _require_regular_file(path: Path) -> None:
    if path.is_symlink() or not path.is_file():
        raise SelectionError(f"Plan 073 dataset input is missing or unsafe: {path.name}")


def _load_json_object(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SelectionError(f"Plan 073 dataset input is invalid: {path.name}") from exc
    if not isinstance(value, Mapping):
        raise SelectionError(f"Plan 073 dataset input must be an object: {path.name}")
    return value


def _stream_jsonl(path: Path) -> Iterator[Mapping[str, Any]]:
    _require_regular_file(path)
    try:
        with path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    raise SelectionError(
                        f"Plan 073 dataset input has a blank line: {path.name}:{number}"
                    )
                value = json.loads(line)
                if not isinstance(value, Mapping):
                    raise SelectionError(
                        f"Plan 073 dataset row must be an object: {path.name}:{number}"
                    )
                yield value
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SelectionError(f"Plan 073 dataset input is invalid: {path.name}") from exc
