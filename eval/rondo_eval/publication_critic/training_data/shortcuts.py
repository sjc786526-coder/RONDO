"""Lightweight model-visible candidate-text shortcut screening."""

import copy
import re
import unicodedata
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from ..render import build_messages
from .contract import SPLITS, TrainingDataError


def model_visible_text_shortcut_findings(
    packet_rows: Sequence[Mapping[str, Any]],
    supervision_rows: Sequence[Mapping[str, Any]],
    *,
    minimum_candidate_support: int = 4,
    minimum_split_support: int = 2,
    dropped_oldest_publications: Mapping[str, int] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Find repeated model-visible variable 4-grams that predict one label.

    Each fragment contributes at most once per candidate, even when repeated.
    Every packet value rendered by the model-input contract is included except
    the fixed qualification identity; supervision-only metadata is excluded.
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
    omissions = _shortcut_omission_counts(
        set(packets),
        dropped_oldest_publications,
    )
    for row in supervision.values():
        if row.get("binary_label") not in {"PASS", "REWRITE"}:
            raise TrainingDataError("text shortcut supervision contains an invalid Binary label")
        if row.get("proposed_split") not in SPLITS:
            raise TrainingDataError("text shortcut supervision contains an invalid or null split")

    candidates_by_fragment: dict[str, set[str]] = defaultdict(set)
    for candidate_id, row in packets.items():
        packet = row["packet"]
        if not isinstance(packet, Mapping):
            raise TrainingDataError("text shortcut packet must be an object")
        fragments: set[str] = set()
        for visible_value in _model_visible_variable_values(
            packet,
            dropped_oldest_publications=omissions[candidate_id],
        ):
            fragments.update(_char_four_grams(visible_value))
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


def conditioned_model_visible_text_shortcut_findings(
    packet_rows: Sequence[Mapping[str, Any]],
    supervision_rows: Sequence[Mapping[str, Any]],
    *,
    condition_field: str,
    minimum_candidate_support: int = 4,
    minimum_split_support: int = 2,
    dropped_oldest_publications: Mapping[str, int] | None = None,
) -> tuple[dict[str, Any], ...]:
    """Run the existing visible-text check inside each declared condition.

    Plan 064 uses this narrow wrapper for hard-focus slices because a repeated
    label cue can disappear in a global aggregate while remaining perfect
    within one qualification dimension.  The underlying normalization and
    shortcut rule stay unchanged.
    """

    if not isinstance(condition_field, str) or not condition_field:
        raise TrainingDataError("conditioned text shortcut field must be non-empty")
    packets = _index(packet_rows, "packet rows")
    supervision = _index(supervision_rows, "supervision rows")
    if set(packets) != set(supervision):
        raise TrainingDataError("conditioned text shortcut candidate IDs differ")
    omissions = _shortcut_omission_counts(
        set(packets),
        dropped_oldest_publications,
    )
    by_value: dict[str, list[str]] = defaultdict(list)
    for candidate_id, row in supervision.items():
        value = row.get(condition_field)
        key = "<null>" if value is None else str(value)
        by_value[key].append(candidate_id)
    findings: list[dict[str, Any]] = []
    for value, candidate_ids in sorted(by_value.items()):
        subset_packets = [packets[candidate_id] for candidate_id in candidate_ids]
        subset_supervision = [supervision[candidate_id] for candidate_id in candidate_ids]
        for finding in model_visible_text_shortcut_findings(
            subset_packets,
            subset_supervision,
            minimum_candidate_support=minimum_candidate_support,
            minimum_split_support=minimum_split_support,
            dropped_oldest_publications={
                candidate_id: omissions[candidate_id]
                for candidate_id in candidate_ids
            },
        ):
            findings.append(
                {
                    "condition_field": condition_field,
                    "condition_value": value,
                    **finding,
                }
            )
    return tuple(
        sorted(
            findings,
            key=lambda finding: (
                str(finding["condition_value"]),
                str(finding["fragment"]),
            ),
        )
    )


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
    if not normalized:
        return set()
    if len(normalized) < 4:
        return {normalized}
    return {normalized[index : index + 4] for index in range(len(normalized) - 3)}


def _model_visible_variable_values(
    packet: Mapping[str, Any],
    *,
    dropped_oldest_publications: int,
) -> tuple[str, ...]:
    """Return scalar surfaces emitted by ``render.build_messages``.

    The render contract exposes only the local title, not an arbitrary
    ``local_scope`` object.  JSON literals such as ``null`` are included
    because they are real model-visible surfaces and can themselves become a
    label shortcut.
    """

    local_scope = packet.get("local_scope")
    if not isinstance(local_scope, Mapping):
        raise TrainingDataError("text shortcut local_scope must be an object")
    continuity = packet.get("continuity")
    if not isinstance(continuity, Mapping):
        raise TrainingDataError("text shortcut continuity must be an object")
    visible_continuity: Mapping[str, Any] = continuity
    if continuity.get("state") == "available":
        publications = continuity.get("prior_publications")
        if (
            not isinstance(publications, Sequence)
            or isinstance(publications, (str, bytes, bytearray))
            or dropped_oldest_publications > len(publications)
        ):
            raise TrainingDataError("text shortcut omission count exceeds continuity")
        visible_continuity = {
            **continuity,
            "model_window_additional_oldest_omitted": dropped_oldest_publications,
            "prior_publications": publications[dropped_oldest_publications:],
        }
    elif dropped_oldest_publications:
        raise TrainingDataError("text shortcut omission count requires available continuity")
    visible = (
        packet.get("actor_role"),
        packet.get("target_kind"),
        local_scope.get("title"),
        visible_continuity,
        packet.get("evidence_v1"),
        packet.get("candidate"),
    )
    values: list[str] = []
    for value in visible:
        values.extend(_json_scalar_surfaces(value))
    fitted_packet = copy.deepcopy(dict(packet))
    fitted_packet["continuity"] = copy.deepcopy(dict(visible_continuity))
    values.extend(
        message["content"]
        for message in build_messages(
            fitted_packet,
            "",
            dropped_oldest_publications=dropped_oldest_publications,
        )
    )
    return tuple(values)


def _shortcut_omission_counts(
    candidate_ids: set[str],
    supplied: Mapping[str, int] | None,
) -> dict[str, int]:
    if supplied is None:
        return {candidate_id: 0 for candidate_id in candidate_ids}
    if set(supplied) != candidate_ids:
        raise TrainingDataError("text shortcut omission census candidate IDs differ")
    result: dict[str, int] = {}
    for candidate_id, value in supplied.items():
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise TrainingDataError("text shortcut omission census contains an invalid count")
        result[candidate_id] = value
    return result


def _json_scalar_surfaces(value: Any) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        values: list[str] = []
        for nested in value.values():
            values.extend(_json_scalar_surfaces(nested))
        return tuple(values)
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        values = []
        for nested in value:
            values.extend(_json_scalar_surfaces(nested))
        return tuple(values)
    if value is None:
        return ("null",)
    if value is True:
        return ("true",)
    if value is False:
        return ("false",)
    if isinstance(value, (str, int, float)):
        return (str(value),)
    raise TrainingDataError("text shortcut model-visible value is not JSON-compatible")
