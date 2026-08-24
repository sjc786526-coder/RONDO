"""Immutable v7 lineage checks for additive Publication Critic releases."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..identity import canonical_json_bytes, sha256_bytes
from .consumer import validate_memberships
from .contract import SPLITS, TrainingDataError


def validate_v7_lineage(
    *,
    v7_scenario_rows: Sequence[Mapping[str, Any]],
    v7_packet_rows: Sequence[Mapping[str, Any]],
    v7_supervision_rows: Sequence[Mapping[str, Any]],
    v7_pair_rows: Sequence[Mapping[str, Any]],
    v7_membership: Mapping[str, Any],
    combined_scenario_rows: Sequence[Mapping[str, Any]],
    combined_packet_rows: Sequence[Mapping[str, Any]],
    combined_supervision_rows: Sequence[Mapping[str, Any]],
    combined_pair_rows: Sequence[Mapping[str, Any]],
    retired_candidate_ids: Sequence[str] = (),
    retired_pair_ids: Sequence[str] = (),
) -> dict[str, Any]:
    """Verify the exact unchanged v7 projection inherited by a combined release.

    Rows are compared by their stable entity ID after canonical JSON encoding.
    This deliberately does not compare release-local group-component IDs: those
    may change when an additive row connects to an existing v7 component.
    """

    if v7_membership.get("dataset_revision") != "v7":
        raise TrainingDataError("v7 membership dataset_revision must equal v7")

    physical_v7 = {
        "scenarios": _index(v7_scenario_rows, "scenario_id", "v7 scenarios"),
        "packets": _index(v7_packet_rows, "candidate_id", "v7 packets"),
        "supervision": _index(
            v7_supervision_rows,
            "candidate_id",
            "v7 supervision",
        ),
        "pairs": _index(v7_pair_rows, "pair_id", "v7 pairs"),
    }
    combined = {
        "scenarios": _index(
            combined_scenario_rows,
            "scenario_id",
            "combined scenarios",
        ),
        "packets": _index(
            combined_packet_rows,
            "candidate_id",
            "combined packets",
        ),
        "supervision": _index(
            combined_supervision_rows,
            "candidate_id",
            "combined supervision",
        ),
        "pairs": _index(combined_pair_rows, "pair_id", "combined pairs"),
    }

    _validate_v7_relations(physical_v7)
    validate_memberships(v7_membership, v7_supervision_rows, v7_pair_rows)
    projection = project_v7_release_rows(
        v7_scenario_rows=v7_scenario_rows,
        v7_packet_rows=v7_packet_rows,
        v7_supervision_rows=v7_supervision_rows,
        v7_pair_rows=v7_pair_rows,
        retired_candidate_ids=retired_candidate_ids,
        retired_pair_ids=retired_pair_ids,
    )
    v7 = {
        "scenarios": _index(projection["scenarios"], "scenario_id", "inherited v7 scenarios"),
        "packets": _index(projection["packets"], "candidate_id", "inherited v7 packets"),
        "supervision": _index(
            projection["supervision"],
            "candidate_id",
            "inherited v7 supervision",
        ),
        "pairs": _index(projection["pairs"], "pair_id", "inherited v7 pairs"),
    }

    pinned_candidate_splits = {
        candidate_id: _split(row, candidate_id)
        for candidate_id, row in sorted(v7["supervision"].items())
    }
    for candidate_id, expected_split in pinned_candidate_splits.items():
        combined_row = combined["supervision"].get(candidate_id)
        if combined_row is None:
            raise TrainingDataError(
                f"combined supervision is missing v7 candidate: {candidate_id}"
            )
        if combined_row.get("proposed_split") != expected_split:
            raise TrainingDataError(
                f"v7 candidate split drifted: {candidate_id}"
            )

    for kind in ("scenarios", "packets", "supervision", "pairs"):
        _require_unchanged_rows(v7[kind], combined[kind], kind)

    retired_candidates = set(retired_candidate_ids)
    retired_pairs = set(retired_pair_ids)
    if retired_candidates & set(combined["packets"]):
        raise TrainingDataError("combined packets reintroduce a retired v7 candidate")
    if retired_candidates & set(combined["supervision"]):
        raise TrainingDataError("combined supervision reintroduces a retired v7 candidate")
    if retired_pairs & set(combined["pairs"]):
        raise TrainingDataError("combined pairs reintroduce a retired v7 pair")

    physical_counts = {
        kind: len(physical_v7[kind]) for kind in sorted(physical_v7)
    }
    v7_counts = {kind: len(v7[kind]) for kind in sorted(v7)}
    combined_counts = {kind: len(combined[kind]) for kind in sorted(combined)}
    return {
        "schema_version": 1,
        "base_dataset_revision": "v7",
        "physical_row_counts": physical_counts,
        "verified_row_counts": v7_counts,
        "retired_candidate_ids": sorted(retired_candidates),
        "retired_pair_ids": sorted(retired_pairs),
        "combined_row_counts": combined_counts,
        "added_row_counts": {
            kind: combined_counts[kind] - v7_counts[kind]
            for kind in sorted(v7_counts)
        },
        "v7_canonical_content_sha256": {
            kind: _rows_digest(physical_v7[kind])
            for kind in sorted(physical_v7)
        },
        "inherited_v7_canonical_content_sha256": {
            kind: _rows_digest(v7[kind]) for kind in sorted(v7)
        },
        "pinned_candidate_splits": pinned_candidate_splits,
    }


def project_v7_release_rows(
    *,
    v7_scenario_rows: Sequence[Mapping[str, Any]],
    v7_packet_rows: Sequence[Mapping[str, Any]],
    v7_supervision_rows: Sequence[Mapping[str, Any]],
    v7_pair_rows: Sequence[Mapping[str, Any]],
    retired_candidate_ids: Sequence[str],
    retired_pair_ids: Sequence[str],
) -> dict[str, list[Mapping[str, Any]]]:
    """Select the exact Plan 064 v7 membership projection.

    The physical release remains independently manifest-verified.  This helper
    only removes explicitly named candidates and relations for v8 membership;
    it neither rewrites retained rows nor introduces a runtime filter.
    """

    rows = {
        "scenarios": _index(v7_scenario_rows, "scenario_id", "v7 scenarios"),
        "packets": _index(v7_packet_rows, "candidate_id", "v7 packets"),
        "supervision": _index(
            v7_supervision_rows,
            "candidate_id",
            "v7 supervision",
        ),
        "pairs": _index(v7_pair_rows, "pair_id", "v7 pairs"),
    }
    _validate_v7_relations(rows)
    retired_candidates = _projection_ids(
        retired_candidate_ids,
        where="retired v7 candidate IDs",
    )
    retired_pairs = _projection_ids(
        retired_pair_ids,
        where="retired v7 pair IDs",
    )
    unknown_candidates = retired_candidates - set(rows["supervision"])
    unknown_pairs = retired_pairs - set(rows["pairs"])
    if unknown_candidates:
        raise TrainingDataError(
            f"v7 projection retires unknown candidates: {sorted(unknown_candidates)}"
        )
    if unknown_pairs:
        raise TrainingDataError(
            f"v7 projection retires unknown pairs: {sorted(unknown_pairs)}"
        )

    inherited_candidate_ids = set(rows["supervision"]) - retired_candidates
    inherited_pair_ids = set(rows["pairs"]) - retired_pairs
    for pair_id in sorted(inherited_pair_ids):
        pair = rows["pairs"][pair_id]
        endpoints = {
            str(pair["preferred_candidate_id"]),
            str(pair["dispreferred_candidate_id"]),
        }
        retired_endpoints = endpoints & retired_candidates
        if retired_endpoints:
            raise TrainingDataError(
                f"v7 projection keeps pair {pair_id} with retired endpoints: "
                f"{sorted(retired_endpoints)}"
            )
    for pair_id in sorted(retired_pairs):
        pair = rows["pairs"][pair_id]
        endpoints = {
            str(pair["preferred_candidate_id"]),
            str(pair["dispreferred_candidate_id"]),
        }
        if not endpoints & retired_candidates:
            raise TrainingDataError(
                f"v7 projection retires unrelated pair: {pair_id}"
            )

    referenced_scenarios = {
        str(rows["supervision"][candidate_id]["scenario_id"])
        for candidate_id in inherited_candidate_ids
    }
    if referenced_scenarios != set(rows["scenarios"]):
        raise TrainingDataError(
            "v7 projection would orphan or remove Scenario membership"
        )

    return {
        "scenarios": list(v7_scenario_rows),
        "packets": [
            row
            for row in v7_packet_rows
            if str(row["candidate_id"]) in inherited_candidate_ids
        ],
        "supervision": [
            row
            for row in v7_supervision_rows
            if str(row["candidate_id"]) in inherited_candidate_ids
        ],
        "pairs": [
            row
            for row in v7_pair_rows
            if str(row["pair_id"]) in inherited_pair_ids
        ],
    }


def _validate_v7_relations(
    rows: Mapping[str, Mapping[str, Mapping[str, Any]]],
) -> None:
    packet_ids = set(rows["packets"])
    supervision_ids = set(rows["supervision"])
    if packet_ids != supervision_ids:
        raise TrainingDataError("v7 packet and supervision candidate IDs differ")

    scenario_ids = set(rows["scenarios"])
    referenced_scenarios = {
        row.get("scenario_id") for row in rows["supervision"].values()
    }
    if referenced_scenarios != scenario_ids:
        raise TrainingDataError("v7 Scenario IDs differ from supervision references")

    for pair_id, row in rows["pairs"].items():
        for key in ("preferred_candidate_id", "dispreferred_candidate_id"):
            candidate_id = row.get(key)
            if candidate_id not in supervision_ids:
                raise TrainingDataError(
                    f"v7 pair {pair_id} references a missing candidate"
                )


def _require_unchanged_rows(
    frozen: Mapping[str, Mapping[str, Any]],
    combined: Mapping[str, Mapping[str, Any]],
    kind: str,
) -> None:
    for row_id, expected in sorted(frozen.items()):
        actual = combined.get(row_id)
        if actual is None:
            raise TrainingDataError(f"combined {kind} is missing v7 row: {row_id}")
        if canonical_json_bytes(actual) != canonical_json_bytes(expected):
            raise TrainingDataError(f"combined {kind} rewrites v7 row: {row_id}")


def _index(
    rows: Sequence[Mapping[str, Any]],
    key: str,
    where: str,
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise TrainingDataError(f"{where}[{index}] must be an object")
        row_id = row.get(key)
        if not isinstance(row_id, str) or not row_id or row_id.strip() != row_id:
            raise TrainingDataError(f"{where}[{index}].{key} must be a stable ID")
        if any(character.isspace() for character in row_id):
            raise TrainingDataError(f"{where}[{index}].{key} must be a stable ID")
        if row_id in result:
            raise TrainingDataError(f"duplicate {key} in {where}: {row_id}")
        result[row_id] = row
    return result


def _projection_ids(values: Sequence[str], *, where: str) -> set[str]:
    identifiers: set[str] = set()
    for index, value in enumerate(values):
        if (
            not isinstance(value, str)
            or not value
            or value.strip() != value
            or any(character.isspace() for character in value)
        ):
            raise TrainingDataError(f"{where}[{index}] must be a stable ID")
        if value in identifiers:
            raise TrainingDataError(f"{where} must not contain duplicates")
        identifiers.add(value)
    return identifiers


def _split(row: Mapping[str, Any], candidate_id: str) -> str:
    split = row.get("proposed_split")
    if split not in SPLITS:
        raise TrainingDataError(f"v7 candidate has invalid split: {candidate_id}")
    return str(split)


def _rows_digest(rows: Mapping[str, Mapping[str, Any]]) -> str:
    ordered_rows = [rows[row_id] for row_id in sorted(rows)]
    return sha256_bytes(canonical_json_bytes(ordered_rows))
