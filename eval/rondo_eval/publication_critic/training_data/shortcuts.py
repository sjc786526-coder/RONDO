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
