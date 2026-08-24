"""Plan 064 risk-stratified release-audit sampling contract.

The audit is additional semantic evidence, not an admission mechanism.  This
module only derives the declared release strata and verifies that a supplied
sample touches every represented stratum; it deliberately does not implement
a general annotation or audit platform.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import hashlib
from typing import Any

from .contract import TrainingDataError


AUDIT_DIMENSIONS = (
    "split",
    "publication_class",
    "hard_focus",
    "difficulty",
    "style",
    "length_bucket",
    "continuity_state",
    "unicode",
    "generator_batch",
)


@dataclass(frozen=True)
class Plan064QualityAuditStrata:
    """Candidate and pair stratum memberships for one complete release."""

    candidate_members: Mapping[str, frozenset[str]]
    pair_members: Mapping[str, frozenset[str]]
    required_candidate_ids: frozenset[str]
    required_pair_ids: frozenset[str]

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted((*self.candidate_members, *self.pair_members)))


def plan064_quality_audit_seed(design_lock: Mapping[str, Any]) -> int:
    """Derive the frozen non-negative 63-bit sampling seed."""

    sampling = _audit_sampling_contract(design_lock)
    seed_text = sampling.get("seed")
    if not isinstance(seed_text, str) or not seed_text:
        raise TrainingDataError("Plan 064 quality audit seed is invalid")
    prefix = hashlib.sha256(seed_text.encode("utf-8")).digest()[:8]
    return int.from_bytes(prefix, "big") & (2**63 - 1)


def build_plan064_quality_audit_strata(
    *,
    combined: Mapping[str, Sequence[Mapping[str, Any]]],
    assignments: Mapping[str, str],
    base_candidate_ids: set[str],
    base_pair_ids: set[str],
    near_duplicate_edges: Sequence[Any],
    design_lock: Mapping[str, Any],
) -> Plan064QualityAuditStrata:
    """Derive every represented inherited/new candidate and pair stratum."""

    sampling = _audit_sampling_contract(design_lock)
    dimensions = sampling.get("strata")
    if not isinstance(dimensions, list) or tuple(dimensions) != AUDIT_DIMENSIONS:
        raise TrainingDataError("Plan 064 quality audit dimensions drifted")

    packets = _index(combined.get("packets"), "candidate_id", "audit packets")
    supervision = _index(
        combined.get("supervision"),
        "candidate_id",
        "audit supervision",
    )
    pairs = _index(combined.get("pairs"), "pair_id", "audit pairs")
    if set(packets) != set(supervision) or set(supervision) != set(assignments):
        raise TrainingDataError("Plan 064 quality audit candidate universes differ")
    if not base_candidate_ids <= set(supervision) or not base_pair_ids <= set(pairs):
        raise TrainingDataError("Plan 064 quality audit base lineage is outside the release")

    pair_kinds_by_candidate: dict[str, set[str]] = defaultdict(set)
    for pair in pairs.values():
        for key in ("preferred_candidate_id", "dispreferred_candidate_id"):
            candidate_id = pair.get(key)
            if not isinstance(candidate_id, str) or candidate_id not in supervision:
                raise TrainingDataError("Plan 064 quality audit pair endpoint is invalid")
            pair_kinds_by_candidate[candidate_id].add(str(pair.get("kind")))

    near_candidates: set[str] = set()
    for edge in near_duplicate_edges:
        try:
            endpoints = (str(edge.left_candidate_id), str(edge.right_candidate_id))
        except AttributeError as exc:
            raise TrainingDataError("Plan 064 quality audit near-duplicate edge is invalid") from exc
        if not set(endpoints) <= set(supervision):
            raise TrainingDataError("Plan 064 quality audit near-duplicate endpoint is invalid")
        near_candidates.update(endpoints)

    candidate_members: dict[str, set[str]] = defaultdict(set)
    for candidate_id, row in supervision.items():
        packet = packets[candidate_id].get("packet")
        if not isinstance(packet, Mapping):
            raise TrainingDataError("Plan 064 quality audit packet is invalid")
        lineage = (
            "inherited_v7" if candidate_id in base_candidate_ids else "plan064_new"
        )
        kinds = pair_kinds_by_candidate[candidate_id]
        if "boundary" in kinds:
            difficulty = "paired_boundary"
        elif "within_pass" in kinds:
            difficulty = "paired_within_pass"
        else:
            defects = row.get("defects")
            slices = row.get("slices")
            if not isinstance(defects, list) or not isinstance(slices, list):
                raise TrainingDataError("Plan 064 quality audit defects are invalid")
            if len(defects) > 1:
                difficulty = "unpaired_multi_defect"
            else:
                difficulty = "unpaired_singleton"
        continuity = packet.get("continuity")
        if not isinstance(continuity, Mapping):
            raise TrainingDataError("Plan 064 quality audit continuity is invalid")
        generator_batch = _generator_batch(row, inherited=lineage == "inherited_v7")
        values = {
            "split": assignments[candidate_id],
            "publication_class": row.get("publication_class"),
            "hard_focus": row.get("hard_focus") or "none",
            "difficulty": difficulty,
            "style": row.get("style"),
            "length_bucket": row.get("length_bucket"),
            "continuity_state": continuity.get("state"),
            "unicode": "true" if row.get("unicode") is True else "false",
            "generator_batch": generator_batch,
        }
        for dimension in AUDIT_DIMENSIONS:
            value = values[dimension]
            if not isinstance(value, str) or not value:
                raise TrainingDataError(
                    f"Plan 064 quality audit stratum value is invalid: {dimension}"
                )
            candidate_members[
                f"candidate:{lineage}:{dimension}={value}"
            ].add(candidate_id)
        if "natural_mixed" in row.get("slices", []):
            candidate_members[
                f"candidate:{lineage}:difficulty=natural_mixed"
            ].add(candidate_id)
        if candidate_id in near_candidates:
            candidate_members[
                f"candidate:{lineage}:difficulty=near_duplicate_endpoint"
            ].add(candidate_id)

    pair_members: dict[str, set[str]] = defaultdict(set)
    for pair_id, row in pairs.items():
        lineage = "inherited_v7" if pair_id in base_pair_ids else "plan064_new"
        preferred = str(row["preferred_candidate_id"])
        pair_split = assignments[preferred]
        kind = row.get("kind")
        if kind not in {"boundary", "within_pass"}:
            raise TrainingDataError("Plan 064 quality audit pair kind is invalid")
        target = row.get("target_dimension") or "within_pass"
        if not isinstance(target, str) or not target:
            raise TrainingDataError("Plan 064 quality audit pair target is invalid")
        pair_members[
            f"pair:{lineage}:kind={kind}:split={pair_split}"
        ].add(pair_id)
        pair_members[f"pair:{lineage}:target={target}"].add(pair_id)

    frozen_candidates = {
            name: frozenset(members)
            for name, members in sorted(candidate_members.items())
        }
    frozen_pairs = {
            name: frozenset(members)
            for name, members in sorted(pair_members.items())
        }
    seed_text = str(sampling["seed"])
    return Plan064QualityAuditStrata(
        candidate_members=frozen_candidates,
        pair_members=frozen_pairs,
        required_candidate_ids=frozenset(
            _choose_seeded(seed_text, name, members)
            for name, members in frozen_candidates.items()
        ),
        required_pair_ids=frozenset(
            _choose_seeded(seed_text, name, members)
            for name, members in frozen_pairs.items()
        ),
    )


def validate_plan064_quality_audit_sample(
    *,
    declared_strata: Sequence[str],
    sampled_candidate_ids: set[str],
    sampled_pair_ids: set[str],
    strata: Plan064QualityAuditStrata,
) -> None:
    """Require the audit to name and touch every represented release stratum."""

    if tuple(declared_strata) != strata.names:
        raise TrainingDataError(
            "Plan 064 quality audit strata do not match the complete release"
        )
    missing_candidates = [
        name
        for name, members in strata.candidate_members.items()
        if members.isdisjoint(sampled_candidate_ids)
    ]
    missing_pairs = [
        name
        for name, members in strata.pair_members.items()
        if members.isdisjoint(sampled_pair_ids)
    ]
    if missing_candidates or missing_pairs:
        raise TrainingDataError(
            "Plan 064 quality audit sample misses represented strata: "
            f"{sorted((*missing_candidates, *missing_pairs))}"
        )
    missing_seeded_candidates = strata.required_candidate_ids - sampled_candidate_ids
    missing_seeded_pairs = strata.required_pair_ids - sampled_pair_ids
    if missing_seeded_candidates or missing_seeded_pairs:
        raise TrainingDataError(
            "Plan 064 quality audit sample misses deterministic seeded members: "
            f"{sorted((*missing_seeded_candidates, *missing_seeded_pairs))}"
        )


def _audit_sampling_contract(design_lock: Mapping[str, Any]) -> Mapping[str, Any]:
    review = design_lock.get("review_contract")
    sampling = review.get("audit_sampling") if isinstance(review, Mapping) else None
    if not isinstance(sampling, Mapping):
        raise TrainingDataError("Plan 064 quality audit contract is missing")
    return sampling


def _generator_batch(row: Mapping[str, Any], *, inherited: bool) -> str:
    if inherited:
        source_group = row.get("source_group")
        if not isinstance(source_group, str) or not source_group:
            raise TrainingDataError("Plan 064 inherited generator batch is invalid")
        return source_group.split("-", 1)[0] + ":v7"
    identity = row.get("generator_identity")
    session = identity.get("session_identity") if isinstance(identity, Mapping) else None
    if not isinstance(session, str) or not session:
        raise TrainingDataError("Plan 064 generator batch identity is invalid")
    return session


def _choose_seeded(seed: str, stratum: str, members: frozenset[str]) -> str:
    if not members:
        raise TrainingDataError("Plan 064 quality audit stratum is empty")
    return min(
        members,
        key=lambda identifier: hashlib.sha256(
            f"{seed}\0{stratum}\0{identifier}".encode("utf-8")
        ).hexdigest(),
    )


def _index(value: Any, key: str, where: str) -> dict[str, Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise TrainingDataError(f"Plan 064 {where} must be a row sequence")
    result: dict[str, Mapping[str, Any]] = {}
    for row in value:
        if not isinstance(row, Mapping):
            raise TrainingDataError(f"Plan 064 {where} contains a non-object row")
        identifier = row.get(key)
        if not isinstance(identifier, str) or not identifier or identifier in result:
            raise TrainingDataError(f"Plan 064 {where} contains an invalid {key}")
        result[identifier] = row
    return result
