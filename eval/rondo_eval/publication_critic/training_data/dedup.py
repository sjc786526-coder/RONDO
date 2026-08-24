"""Lightweight, reproducible exact and near-duplicate screening."""

from dataclasses import dataclass
import hashlib
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any

from ..identity import canonical_json_bytes
from .contract import TrainingDataError


@dataclass(frozen=True)
class NearDuplicateEdge:
    left_candidate_id: str
    right_candidate_id: str
    similarity: float


def exact_packet_digest(packet: Mapping[str, Any]) -> str:
    """Hash the complete canonical model-visible packet, excluding supervision."""

    return hashlib.sha256(canonical_json_bytes(packet)).hexdigest()


def reject_exact_duplicates(packet_rows: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    by_digest: dict[str, str] = {}
    result: dict[str, str] = {}
    for row in packet_rows:
        candidate_id = str(row["candidate_id"])
        digest = exact_packet_digest(row["packet"])
        if digest in by_digest:
            raise TrainingDataError(
                f"exact duplicate packets: {by_digest[digest]} and {candidate_id}"
            )
        by_digest[digest] = candidate_id
        result[candidate_id] = digest
    return result


def variable_text_similarity(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    """Return max(char-5gram Jaccard, containment) over variable packet text."""

    left_grams = _char_ngrams(_variable_text(left))
    right_grams = _char_ngrams(_variable_text(right))
    if not left_grams and not right_grams:
        return 1.0
    if not left_grams or not right_grams:
        return 0.0
    overlap = len(left_grams & right_grams)
    jaccard = overlap / len(left_grams | right_grams)
    containment = overlap / min(len(left_grams), len(right_grams))
    return max(jaccard, containment)


def find_near_duplicate_edges(
    packet_rows: Sequence[Mapping[str, Any]],
    *,
    threshold: float,
) -> tuple[NearDuplicateEdge, ...]:
    if not isinstance(threshold, (int, float)) or isinstance(threshold, bool) or not 0 < threshold <= 1:
        raise TrainingDataError("near-duplicate threshold must be in (0, 1]")
    edges: list[NearDuplicateEdge] = []
    for left_index, left in enumerate(packet_rows):
        for right in packet_rows[left_index + 1 :]:
            score = variable_text_similarity(left["packet"], right["packet"])
            if score >= threshold:
                edges.append(
                    NearDuplicateEdge(
                        left_candidate_id=str(left["candidate_id"]),
                        right_candidate_id=str(right["candidate_id"]),
                        similarity=score,
                    )
                )
    return tuple(edges)


def find_reference_matches(
    packet_rows: Sequence[Mapping[str, Any]],
    reference_packets: Mapping[str, Mapping[str, Any]],
    *,
    threshold: float,
) -> tuple[dict[str, Any], ...]:
    matches: list[dict[str, Any]] = []
    for row in packet_rows:
        for reference_id, reference in reference_packets.items():
            score = variable_text_similarity(row["packet"], reference)
            if score >= threshold:
                matches.append(
                    {
                        "candidate_id": row["candidate_id"],
                        "reference_id": reference_id,
                        "similarity": score,
                    }
                )
    return tuple(matches)


def _variable_text(packet: Mapping[str, Any]) -> str:
    values: list[str] = [
        str(packet["local_scope"]["title"]),
        str(packet["candidate"]["summary"]),
        str(packet["candidate"].get("handoff") or ""),
    ]
    continuity = packet["continuity"]
    if continuity["state"] == "available":
        for prior in continuity["prior_publications"]:
            values.extend((str(prior["summary"]), str(prior.get("handoff") or "")))
    return "\n".join(values)


def _char_ngrams(value: str) -> frozenset[str]:
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"\s+", " ", normalized).strip()
    if not normalized:
        return frozenset()
    if len(normalized) < 5:
        return frozenset({normalized})
    return frozenset(normalized[index : index + 5] for index in range(len(normalized) - 4))
