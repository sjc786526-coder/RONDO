"""Minimal Plan 064 review-disposition checks over the Plan 059 row contract.

Plan 064 directly reviews every new candidate and pair.  Canonically unchanged
v7 members retain their frozen review through the separately verified lineage
set.  This module intentionally does not add sampled admission or alter the v1
row contracts.
"""

from collections.abc import Mapping, Sequence, Set
from typing import Any, NoReturn

from .contract import (
    TrainingDataError,
    validate_candidate_review,
    validate_pair_review,
)


_DISPOSITION_METHODS = frozenset({"inherited_v7", "direct_accept"})
_CANDIDATE_DISPOSITION_KEYS = {
    "schema_version",
    "candidate_id",
    "method",
}
_PAIR_DISPOSITION_KEYS = {
    "schema_version",
    "pair_id",
    "method",
}


def validate_plan064_review_dispositions(
    supervision_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    candidate_review_rows: Sequence[Mapping[str, Any]],
    pair_review_rows: Sequence[Mapping[str, Any]],
    candidate_disposition_rows: Sequence[Mapping[str, Any]],
    pair_disposition_rows: Sequence[Mapping[str, Any]],
    *,
    inherited_v7_candidate_ids: Set[str],
    inherited_v7_pair_ids: Set[str],
) -> None:
    """Validate the Plan 064 direct-review and immutable-lineage closure.

    The lineage sets are verified output from the independent v7 lineage
    validator.  Every final candidate and pair has exactly one disposition:
    lineage members must say ``inherited_v7`` and every other member must say
    ``direct_accept`` with a terminal independent review.
    """

    supervision = _index(supervision_rows, "candidate_id", "supervision rows")
    pairs = _index(pair_rows, "pair_id", "pair rows")
    candidate_reviews = _index(
        candidate_review_rows,
        "candidate_id",
        "candidate review rows",
    )
    pair_reviews = _index(pair_review_rows, "pair_id", "pair review rows")
    candidate_dispositions = _index_dispositions(
        candidate_disposition_rows,
        id_key="candidate_id",
        expected_keys=_CANDIDATE_DISPOSITION_KEYS,
        where="candidate disposition rows",
    )
    pair_dispositions = _index_dispositions(
        pair_disposition_rows,
        id_key="pair_id",
        expected_keys=_PAIR_DISPOSITION_KEYS,
        where="pair disposition rows",
    )

    candidate_ids = set(supervision)
    pair_ids = set(pairs)
    inherited_candidates = _identifier_set(
        inherited_v7_candidate_ids,
        "inherited v7 candidate IDs",
    )
    inherited_pairs = _identifier_set(inherited_v7_pair_ids, "inherited v7 pair IDs")
    if not inherited_candidates <= candidate_ids:
        _fail(
            "v7 candidate lineage contains members missing from the release: "
            f"{sorted(inherited_candidates - candidate_ids)}"
        )
    if not inherited_pairs <= pair_ids:
        _fail(
            "v7 pair lineage contains members missing from the release: "
            f"{sorted(inherited_pairs - pair_ids)}"
        )
    _require_exact_ids(candidate_dispositions, candidate_ids, "candidate dispositions")
    _require_exact_ids(pair_dispositions, pair_ids, "pair dispositions")

    if not set(candidate_reviews) <= candidate_ids:
        _fail(
            "candidate reviews contain IDs outside the release: "
            f"{sorted(set(candidate_reviews) - candidate_ids)}"
        )
    if not set(pair_reviews) <= pair_ids:
        _fail(
            "pair reviews contain IDs outside the release: "
            f"{sorted(set(pair_reviews) - pair_ids)}"
        )
    for review in candidate_review_rows:
        validate_candidate_review(review)
    for review in pair_review_rows:
        validate_pair_review(review)

    for candidate_id, supervision_row in supervision.items():
        expected = "inherited_v7" if candidate_id in inherited_candidates else "direct_accept"
        observed = candidate_dispositions[candidate_id]["method"]
        if observed != expected:
            _fail(
                f"candidate {candidate_id} must use {expected}, not {observed}"
            )
        if expected == "direct_accept":
            _validate_direct_candidate_review(
                candidate_id,
                supervision_row,
                candidate_reviews.get(candidate_id),
            )

    for pair_id, pair_row in pairs.items():
        expected = "inherited_v7" if pair_id in inherited_pairs else "direct_accept"
        observed = pair_dispositions[pair_id]["method"]
        if observed != expected:
            _fail(f"pair {pair_id} must use {expected}, not {observed}")
        if expected == "direct_accept":
            for endpoint_key in ("preferred_candidate_id", "dispreferred_candidate_id"):
                endpoint_id = _identifier(
                    pair_row.get(endpoint_key),
                    f"new pair {pair_id}.{endpoint_key}",
                )
                disposition = candidate_dispositions.get(endpoint_id)
                if disposition is None or disposition["method"] != "direct_accept":
                    _fail(
                        f"new pair {pair_id} endpoint {endpoint_id} is not directly reviewed"
                    )
            _validate_direct_pair_review(
                pair_id,
                pair_row,
                pair_reviews.get(pair_id),
                supervision,
            )


def _validate_direct_candidate_review(
    candidate_id: str,
    supervision: Mapping[str, Any],
    review: Mapping[str, Any] | None,
) -> None:
    if review is None:
        _fail(f"new candidate {candidate_id} lacks a direct review")
    if supervision.get("review_status") != "accept" or review["decision"] != "accept":
        _fail(f"new candidate {candidate_id} lacks a terminal accepting review")
    if review["independent_label"] != supervision.get("binary_label"):
        _fail(f"new candidate {candidate_id} direct review label differs")
    if set(review["failed_hard_dimensions"]) != set(
        supervision.get("defects", [])
    ):
        _fail(f"new candidate {candidate_id} direct review defects differ")
    if review["reviewer_identity"] != supervision.get("reviewer_identity"):
        _fail(f"new candidate {candidate_id} reviewer identity differs")
    generator = supervision.get("generator_identity")
    reviewer = review["reviewer_identity"]
    if not isinstance(generator, Mapping):
        _fail(f"new candidate {candidate_id} lacks generator identity")
    if generator.get("session_identity") == reviewer.get("session_identity"):
        _fail(f"new candidate {candidate_id} review is not independent from generation")


def _validate_direct_pair_review(
    pair_id: str,
    pair: Mapping[str, Any],
    review: Mapping[str, Any] | None,
    supervision: Mapping[str, Mapping[str, Any]],
) -> None:
    if review is None:
        _fail(f"new pair {pair_id} lacks a direct review")
    if pair.get("review_status") != "accept" or review["decision"] != "accept":
        _fail(f"new pair {pair_id} lacks a terminal accepting review")
    for key in ("direction_confirmed", "context_equal", "omission_equal"):
        if review[key] is not True:
            _fail(f"new pair {pair_id} direct review does not confirm {key}")
    kind = pair.get("kind")
    if kind == "boundary":
        if review["atomicity_confirmed"] is not True:
            _fail(f"new Boundary pair {pair_id} direct review does not confirm atomicity")
    elif kind == "within_pass":
        if review["soft_only_confirmed"] is not True:
            _fail(f"new Within-PASS pair {pair_id} direct review does not confirm soft-only semantics")
    else:
        _fail(f"new pair {pair_id} has an unknown kind")

    reviewer_session = review["reviewer_identity"].get("session_identity")
    for endpoint_key in ("preferred_candidate_id", "dispreferred_candidate_id"):
        endpoint_id = _identifier(
            pair.get(endpoint_key),
            f"new pair {pair_id}.{endpoint_key}",
        )
        endpoint = supervision.get(endpoint_id)
        if endpoint is None:
            _fail(f"new pair {pair_id} has a missing endpoint: {endpoint_id}")
        generator = endpoint.get("generator_identity")
        if not isinstance(generator, Mapping):
            _fail(f"new pair {pair_id} endpoint {endpoint_id} lacks generator identity")
        if generator.get("session_identity") == reviewer_session:
            _fail(f"new pair {pair_id} review is not independent from generation")


def _index(
    rows: Sequence[Mapping[str, Any]],
    id_key: str,
    where: str,
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            _fail(f"{where}[{index}] must be an object")
        identifier = _identifier(row.get(id_key), f"{where}[{index}].{id_key}")
        if identifier in result:
            _fail(f"duplicate {id_key} in {where}: {identifier}")
        result[identifier] = row
    return result


def _index_dispositions(
    rows: Sequence[Mapping[str, Any]],
    *,
    id_key: str,
    expected_keys: set[str],
    where: str,
) -> dict[str, Mapping[str, Any]]:
    result = _index(rows, id_key, where)
    for identifier, row in result.items():
        if set(row) != expected_keys:
            _fail(f"{where} {identifier} keys differ")
        if row["schema_version"] != 1 or isinstance(row["schema_version"], bool):
            _fail(f"{where} {identifier} schema_version must equal 1")
        if not isinstance(row["method"], str) or row["method"] not in _DISPOSITION_METHODS:
            _fail(f"{where} {identifier} has an unknown method")
    return result


def _identifier_set(values: Set[str], where: str) -> set[str]:
    if isinstance(values, (str, bytes)) or not isinstance(values, Set):
        _fail(f"{where} must be a set")
    return {_identifier(value, where) for value in values}


def _require_exact_ids(
    rows: Mapping[str, Mapping[str, Any]],
    expected: set[str],
    where: str,
) -> None:
    observed = set(rows)
    if observed != expected:
        _fail(
            f"{where} IDs differ: missing={sorted(expected - observed)}, "
            f"extra={sorted(observed - expected)}"
        )


def _identifier(value: Any, where: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 160
        or any(character.isspace() for character in value)
    ):
        _fail(f"{where} must be a bounded whitespace-free identifier")
    return value


def _fail(message: str) -> NoReturn:
    raise TrainingDataError(message)
