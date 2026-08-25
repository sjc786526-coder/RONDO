"""Split releases for Plan 073, and the gate that keeps unseen-test sealed.

A release is the only input the scoring and judging steps ever read.  Building
a ``validation`` release needs nothing beyond the frozen dataset; building an
``unseen_test`` release needs a valid selection lock.  Running the model and the
Judge from a release therefore means those processes physically never hold the
unseen bodies before the lock exists.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..identity import canonical_json_bytes, sha256_bytes, sha256_file
from ..training_data.consumer import DatasetConsumer
from .contract import (
    SPLITS,
    SelectionError,
    require_count,
    require_exact_keys,
    require_object,
    require_sha256,
)
from .lock import lock_sha256, validate_lock


SCHEMA = "rondo-publication-critic-plan073-split-release-v1"
UNSEEN_SPLIT = "unseen_test"

# Only the supervision fields the deterministic metrics and the slice report
# actually consume.  Reviewer/generator identity stays out of the release.
_SUPERVISION_PROJECTION = (
    "binary_label",
    "publication_class",
    "completion_state",
    "actor_role",
    "hard_focus",
    "length_bucket",
    "style",
    "unicode",
    "scenario_id",
    "scenario_group",
    "slices",
)
_PAIR_PROJECTION = (
    "kind",
    "preferred_candidate_id",
    "dispreferred_candidate_id",
    "target_dimension",
)
_AUTHORIZATION_KINDS = ("frozen_protocol_split", "selection_lock")


def release_sha256(release: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(release)))


def build_split_release(
    dataset_root: Path,
    split: str,
    *,
    repo_root: Path,
    selection_lock: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Release exactly one frozen split; unseen-test requires a valid lock."""

    if split not in SPLITS:
        raise SelectionError("Plan 073 release split is invalid")
    if split == UNSEEN_SPLIT:
        if selection_lock is None:
            raise SelectionError(
                "unseen-test release requires a valid Plan 073 selection lock"
            )
        lock = validate_lock(selection_lock)
        authorization = {
            "kind": "selection_lock",
            "selection_lock_sha256": lock_sha256(lock),
        }
    else:
        if selection_lock is not None:
            raise SelectionError("validation release does not consume a selection lock")
        authorization = {"kind": "frozen_protocol_split", "selection_lock_sha256": None}

    manifest = dataset_root / "manifest.json"
    if manifest.is_symlink() or not manifest.is_file():
        raise SelectionError("Plan 073 dataset manifest is missing or unsafe")
    consumer = DatasetConsumer.from_frozen_directory(
        dataset_root,
        repo_root=repo_root,
        allow_evaluation=True,
    )
    members = sorted(
        str(row["candidate_id"])
        for row in consumer.supervision.values()
        if row["proposed_split"] == split
    )
    if not members:
        raise SelectionError("Plan 073 release split is empty")
    member_set = set(members)

    items = [
        {
            "candidate_id": candidate_id,
            "packet": consumer.packets[candidate_id]["packet"],
            "dropped_oldest_publications": consumer.dropped_oldest_publications(
                candidate_id
            ),
        }
        for candidate_id in members
    ]
    supervision = [
        {
            "candidate_id": candidate_id,
            **{
                name: consumer.supervision[candidate_id][name]
                for name in _SUPERVISION_PROJECTION
            },
        }
        for candidate_id in members
    ]
    pairs = [
        {
            "pair_id": str(row["pair_id"]),
            **{name: row[name] for name in _PAIR_PROJECTION},
        }
        for row in sorted(consumer.pairs.values(), key=lambda row: str(row["pair_id"]))
        if str(row["preferred_candidate_id"]) in member_set
        and str(row["dispreferred_candidate_id"]) in member_set
    ]
    release = {
        "schema": SCHEMA,
        "split": split,
        "dataset_revision": str(consumer.membership["dataset_revision"]),
        "dataset_manifest_sha256": sha256_file(manifest),
        "authorization": authorization,
        "items": items,
        "supervision": supervision,
        "pairs": pairs,
    }
    return validate_release(release)


def validate_release(value: Any) -> dict[str, Any]:
    release = require_object(value, "Plan 073 split release")
    require_exact_keys(
        release,
        {
            "schema",
            "split",
            "dataset_revision",
            "dataset_manifest_sha256",
            "authorization",
            "items",
            "supervision",
            "pairs",
        },
        "Plan 073 split release",
    )
    if release["schema"] != SCHEMA or release["split"] not in SPLITS:
        raise SelectionError("Plan 073 split release identity is invalid")
    if not isinstance(release["dataset_revision"], str) or not release[
        "dataset_revision"
    ].strip():
        raise SelectionError("Plan 073 split release dataset revision is invalid")
    require_sha256(release["dataset_manifest_sha256"], "Plan 073 release dataset")

    authorization = require_object(release["authorization"], "Plan 073 release authorization")
    require_exact_keys(
        authorization,
        {"kind", "selection_lock_sha256"},
        "Plan 073 release authorization",
    )
    kind = authorization["kind"]
    if kind not in _AUTHORIZATION_KINDS:
        raise SelectionError("Plan 073 release authorization kind is invalid")
    if kind == "selection_lock":
        require_sha256(
            authorization["selection_lock_sha256"], "Plan 073 release authorization"
        )
    elif authorization["selection_lock_sha256"] is not None:
        raise SelectionError("Plan 073 release authorization kind is invalid")
    if (release["split"] == UNSEEN_SPLIT) != (kind == "selection_lock"):
        raise SelectionError("Plan 073 release authorization does not match its split")

    identifiers = _validate_items(release["items"])
    _validate_supervision(release["supervision"], identifiers)
    _validate_pairs(release["pairs"], identifiers)
    return dict(release)


def _validate_items(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise SelectionError("Plan 073 release items are invalid")
    identifiers: list[str] = []
    for item_value in value:
        item = require_object(item_value, "Plan 073 release item")
        require_exact_keys(
            item,
            {"candidate_id", "packet", "dropped_oldest_publications"},
            "Plan 073 release item",
        )
        candidate_id = item["candidate_id"]
        if not isinstance(candidate_id, str) or not candidate_id:
            raise SelectionError("Plan 073 release item identity is invalid")
        require_object(item["packet"], "Plan 073 release packet")
        require_count(
            item["dropped_oldest_publications"], "Plan 073 release omission count"
        )
        identifiers.append(candidate_id)
    if sorted(identifiers) != identifiers or len(set(identifiers)) != len(identifiers):
        raise SelectionError("Plan 073 release item order or identity is invalid")
    return identifiers


def _validate_supervision(value: Any, identifiers: Sequence[str]) -> None:
    if not isinstance(value, list) or len(value) != len(identifiers):
        raise SelectionError("Plan 073 release supervision is invalid")
    seen: list[str] = []
    for row_value in value:
        row = require_object(row_value, "Plan 073 release supervision row")
        require_exact_keys(
            row,
            {"candidate_id", *_SUPERVISION_PROJECTION},
            "Plan 073 release supervision row",
        )
        if row["binary_label"] not in {"PASS", "REWRITE"}:
            raise SelectionError("Plan 073 release supervision label is invalid")
        slices = row["slices"]
        if not isinstance(slices, list) or any(
            not isinstance(item, str) or not item for item in slices
        ):
            raise SelectionError("Plan 073 release supervision slices are invalid")
        if type(row["unicode"]) is not bool:
            raise SelectionError("Plan 073 release supervision unicode flag is invalid")
        seen.append(str(row["candidate_id"]))
    if seen != list(identifiers):
        raise SelectionError("Plan 073 release supervision does not match its items")


def _validate_pairs(value: Any, identifiers: Sequence[str]) -> None:
    if not isinstance(value, list):
        raise SelectionError("Plan 073 release pairs are invalid")
    known = set(identifiers)
    pair_ids: list[str] = []
    for row_value in value:
        row = require_object(row_value, "Plan 073 release pair")
        require_exact_keys(
            row, {"pair_id", *_PAIR_PROJECTION}, "Plan 073 release pair"
        )
        if row["kind"] not in {"boundary", "within_pass"}:
            raise SelectionError("Plan 073 release pair kind is invalid")
        preferred = row["preferred_candidate_id"]
        dispreferred = row["dispreferred_candidate_id"]
        if (
            preferred not in known
            or dispreferred not in known
            or preferred == dispreferred
        ):
            raise SelectionError("Plan 073 release pair members are invalid")
        pair_ids.append(str(row["pair_id"]))
    if sorted(pair_ids) != pair_ids or len(set(pair_ids)) != len(pair_ids):
        raise SelectionError("Plan 073 release pair order or identity is invalid")
