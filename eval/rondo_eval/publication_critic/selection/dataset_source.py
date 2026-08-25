"""Split-scoped reader for the frozen v8 evaluation splits.

``DatasetConsumer.from_frozen_directory(allow_evaluation=True)`` is the right
tool for whole-dataset work, but it materialises every split before any
filtering.  For M3-C2 that is the wrong shape: the process that prepares a
validation release must not be able to hold unseen-test bodies at all, and the
unseen split must only become readable once a valid selection lock exists.

This reader keeps the same integrity guarantees by reusing the frozen manifest
verifier and the per-row contract validators, but it decides membership from
the supervision index first and discards every non-member row as it streams,
so no unseen packet, label or pair is ever retained or returned.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from ..contract import REPO_ROOT
from ..identity import sha256_file
from ..training_data.contract import (
    validate_packet_row,
    validate_pair_row,
    validate_supervision_row,
)
from ..training_data.freeze import verify_freeze_manifest
from ..training_data.input_identity import load_plan054_training_input
from .contract import SPLITS, SelectionError
from .lock import lock_sha256, validate_lock


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


@dataclass(frozen=True)
class SplitSource:
    """Exactly one frozen split, plus the identity it was read under."""

    split: str
    dataset_revision: str
    manifest_sha256: str
    authorization: Mapping[str, Any]
    packets: Mapping[str, Mapping[str, Any]]
    supervision: Mapping[str, Mapping[str, Any]]
    pairs: tuple[Mapping[str, Any], ...]
    dropped_oldest_publications: Mapping[str, int]

    @property
    def candidate_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self.supervision))


def load_split(
    root: Path,
    split: str,
    *,
    repo_root: Path = REPO_ROOT,
    selection_lock: Mapping[str, Any] | None = None,
) -> SplitSource:
    """Read one split of the frozen dataset; unseen-test needs a valid lock."""

    if split not in SPLITS:
        raise SelectionError("Plan 073 release split is invalid")
    if split == UNSEEN_SPLIT:
        if selection_lock is None:
            raise SelectionError(
                "unseen-test release requires a valid Plan 073 selection lock"
            )
        authorization = {
            "kind": "selection_lock",
            "selection_lock_sha256": lock_sha256(validate_lock(selection_lock)),
        }
    else:
        if selection_lock is not None:
            raise SelectionError("validation release does not consume a selection lock")
        authorization = {"kind": "frozen_protocol_split", "selection_lock_sha256": None}

    safe_root = _safe_root(root)
    manifest_path = safe_root / MANIFEST_RELATIVE
    _require_regular_file(manifest_path)
    manifest = _load_json_object(manifest_path)
    verify_freeze_manifest(
        safe_root,
        manifest,
        expected_input_identity=load_plan054_training_input(repo_root).input_identity,
    )
    if not set(_REQUIRED_FILES) <= set(manifest["files"]):
        raise SelectionError("Plan 073 freeze manifest does not bind every split input")

    # Membership first: only the requested split's supervision rows are kept.
    members: set[str] = set()
    supervision: dict[str, Mapping[str, Any]] = {}
    for row in _stream_jsonl(safe_root / SUPERVISION_RELATIVE):
        validate_supervision_row(row, final=True)
        candidate_id = str(row["candidate_id"])
        if row["proposed_split"] != split:
            continue
        if candidate_id in supervision:
            raise SelectionError("Plan 073 split supervision identity is duplicated")
        members.add(candidate_id)
        supervision[candidate_id] = row
    if not members:
        raise SelectionError("Plan 073 release split is empty")

    packets: dict[str, Mapping[str, Any]] = {}
    for row in _stream_jsonl(safe_root / PACKETS_RELATIVE):
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id not in members:
            continue
        validate_packet_row(row, repo_root=repo_root)
        if candidate_id in packets:
            raise SelectionError("Plan 073 split packet identity is duplicated")
        packets[candidate_id] = row
    if set(packets) != members:
        raise SelectionError("Plan 073 split packets do not cover the split")

    omissions: dict[str, int] = {}
    for row in _stream_jsonl(safe_root / CENSUS_RELATIVE):
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, str) or candidate_id not in members:
            continue
        value = row.get("dropped_oldest_publications")
        if type(value) is not int or value < 0 or candidate_id in omissions:
            raise SelectionError("Plan 073 split census omission count is invalid")
        omissions[candidate_id] = value
    if set(omissions) != members:
        raise SelectionError("Plan 073 split census does not cover the split")

    pairs: list[Mapping[str, Any]] = []
    for row in _stream_jsonl(safe_root / PAIRS_RELATIVE):
        preferred = row.get("preferred_candidate_id")
        dispreferred = row.get("dispreferred_candidate_id")
        if preferred not in members and dispreferred not in members:
            continue
        validate_pair_row(row, final=True)
        if preferred not in members or dispreferred not in members:
            raise SelectionError("Plan 073 frozen pair crosses the split boundary")
        pairs.append(row)

    return SplitSource(
        split=split,
        dataset_revision=str(manifest["dataset_revision"]),
        manifest_sha256=sha256_file(manifest_path),
        authorization=authorization,
        packets=packets,
        supervision=supervision,
        pairs=tuple(sorted(pairs, key=lambda row: str(row["pair_id"]))),
        dropped_oldest_publications=omissions,
    )


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
    """Yield rows one at a time so non-members are never accumulated."""

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
