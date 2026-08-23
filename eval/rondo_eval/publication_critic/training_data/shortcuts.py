"""Lightweight model-visible candidate-text shortcut screening."""

import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .contract import SPLITS, TrainingDataError


def model_visible_text_shortcut_findings(
    packet_rows: Sequence[Mapping[str, Any]],
    supervision_rows: Sequence[Mapping[str, Any]],
    *,
    minimum_candidate_support: int = 4,
    minimum_split_support: int = 2,
) -> tuple[dict[str, Any], ...]:
    """Find repeated candidate-only char 4-grams that perfectly predict a label.

    Each fragment contributes at most once per candidate, even when repeated in
    both the summary and handoff. Fixed rubric and public context are excluded.
    """

    if (
        not isinstance(minimum_candidate_support, int)
        or isinstance(minimum_candidate_support, bool)
        or minimum_candidate_support < 1
        or not isinstance(minimum_split_support, int)
        or isinstance(minimum_split_support, bool)
        or minimum_split_support < 1
    ):
        raise TrainingDataError("text shortcut support thresholds must be positive")
    packets = _index(packet_rows, "packet rows")
    supervision = _index(supervision_rows, "supervision rows")
    if set(packets) != set(supervision):
        raise TrainingDataError("text shortcut packet and supervision candidate IDs differ")
    for row in supervision.values():
        if row.get("binary_label") not in {"PASS", "REWRITE"}:
            raise TrainingDataError("text shortcut supervision contains an invalid Binary label")
        if row.get("proposed_split") not in SPLITS:
            raise TrainingDataError("text shortcut supervision contains an invalid or null split")

    candidates_by_fragment: dict[str, set[str]] = defaultdict(set)
    for candidate_id, row in packets.items():
        candidate = row["packet"]["candidate"]
        fragments = _char_four_grams(candidate["summary"])
        handoff = candidate.get("handoff")
        if handoff:
            fragments.update(_char_four_grams(handoff))
        for fragment in fragments:
            candidates_by_fragment[fragment].add(candidate_id)

    findings: list[dict[str, Any]] = []
    for fragment, candidate_ids in candidates_by_fragment.items():
        if len(candidate_ids) < minimum_candidate_support:
            continue
        labels = {str(supervision[candidate_id]["binary_label"]) for candidate_id in candidate_ids}
        splits = {str(supervision[candidate_id]["proposed_split"]) for candidate_id in candidate_ids}
        if len(labels) != 1 or len(splits) < minimum_split_support:
            continue
        findings.append(
            {
                "fragment": fragment,
                "support": len(candidate_ids),
                "label": next(iter(labels)),
                "splits": sorted(splits),
                "candidate_ids": sorted(candidate_ids),
            }
        )
    return tuple(sorted(findings, key=lambda finding: finding["fragment"]))


def reject_model_visible_text_shortcuts(
    findings: Sequence[Mapping[str, Any]],
) -> None:
    if findings:
        fragments = sorted(str(finding["fragment"]) for finding in findings)
        raise TrainingDataError(f"model-visible candidate-text shortcuts detected: {fragments}")


def model_visible_candidate_length_shortcut_findings(
    census_rows: Sequence[Mapping[str, Any]],
    supervision_rows: Sequence[Mapping[str, Any]],
    *,
    minimum_candidate_support: int = 6,
    minimum_split_support: int = 2,
) -> tuple[dict[str, Any], ...]:
    """Find exact-token candidate-length thresholds that perfectly predict a label."""

    if (
        not isinstance(minimum_candidate_support, int)
        or isinstance(minimum_candidate_support, bool)
        or minimum_candidate_support < 1
        or not isinstance(minimum_split_support, int)
        or isinstance(minimum_split_support, bool)
        or minimum_split_support < 1
    ):
        raise TrainingDataError("candidate-length shortcut support thresholds must be positive")
    census = _index(census_rows, "token census rows")
    supervision = _index(supervision_rows, "supervision rows")
    if set(census) != set(supervision):
        raise TrainingDataError("candidate-length census and supervision candidate IDs differ")
    candidate_tokens: dict[str, int] = {}
    for candidate_id, row in census.items():
        buckets = row.get("buckets")
        value = buckets.get("candidate") if isinstance(buckets, Mapping) else None
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise TrainingDataError("candidate-length census contains an invalid candidate bucket")
        candidate_tokens[candidate_id] = value
    for row in supervision.values():
        if row.get("binary_label") not in {"PASS", "REWRITE"}:
            raise TrainingDataError("candidate-length supervision contains an invalid Binary label")
        if row.get("proposed_split") not in SPLITS:
            raise TrainingDataError("candidate-length supervision contains an invalid or null split")

    findings: list[dict[str, Any]] = []
    seen_memberships: set[tuple[str, tuple[str, ...]]] = set()
    for threshold in sorted(set(candidate_tokens.values())):
        for direction in ("at_most", "at_least"):
            if direction == "at_most":
                candidate_ids = tuple(
                    sorted(candidate_id for candidate_id, value in candidate_tokens.items() if value <= threshold)
                )
            else:
                candidate_ids = tuple(
                    sorted(candidate_id for candidate_id, value in candidate_tokens.items() if value >= threshold)
                )
            membership = (direction, candidate_ids)
            if membership in seen_memberships:
                continue
            seen_memberships.add(membership)
            if len(candidate_ids) < minimum_candidate_support or len(candidate_ids) == len(candidate_tokens):
                continue
            labels = {str(supervision[candidate_id]["binary_label"]) for candidate_id in candidate_ids}
            splits = {str(supervision[candidate_id]["proposed_split"]) for candidate_id in candidate_ids}
            if len(labels) != 1 or len(splits) < minimum_split_support:
                continue
            findings.append(
                {
                    "direction": direction,
                    "threshold": threshold,
                    "support": len(candidate_ids),
                    "label": next(iter(labels)),
                    "splits": sorted(splits),
                    "candidate_ids": list(candidate_ids),
                }
            )
    return tuple(
        sorted(
            findings,
            key=lambda finding: (str(finding["direction"]), int(finding["threshold"])),
        )
    )


def reject_model_visible_candidate_length_shortcuts(
    findings: Sequence[Mapping[str, Any]],
) -> None:
    if findings:
        thresholds = sorted(
            f"{finding['direction']}:{finding['threshold']}" for finding in findings
        )
        raise TrainingDataError(f"model-visible candidate-length shortcuts detected: {thresholds}")


def _index(
    rows: Sequence[Mapping[str, Any]],
    where: str,
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        candidate_id = row.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id:
            raise TrainingDataError(f"{where} contains an invalid candidate ID")
        if candidate_id in result:
            raise TrainingDataError(f"{where} contains duplicate candidate ID: {candidate_id}")
        result[candidate_id] = row
    return result


def _char_four_grams(value: Any) -> set[str]:
    if not isinstance(value, str):
        raise TrainingDataError("candidate text shortcut input must be a string")
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if len(normalized) < 4:
        return set()
    return {normalized[index : index + 4] for index in range(len(normalized) - 3)}
