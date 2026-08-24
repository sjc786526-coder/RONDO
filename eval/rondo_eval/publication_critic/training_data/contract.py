"""Strict Plan 059 row contracts layered over the frozen Plan 054 packet seam."""

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..contract import (
    REPO_ROOT,
    PublicationCriticContractError,
    _validate_no_supervision,
    _validate_packet,
    load_fixed_input_contract,
)


SPLITS = frozenset({"train", "validation", "unseen_test"})
PUBLICATION_CLASSES = frozenset(
    {
        "new_event_completed",
        "new_event_incomplete",
        "existing_event_completed",
        "existing_event_incomplete",
    }
)
HARD_DIMENSIONS = frozenset(
    {
        "useful_state_transfer",
        "honest_uncertainty",
        "conditional_continuity",
        "scope_and_signal",
        "internal_consistency",
    }
)
_IDENTITY_KEYS = {
    "model",
    "reasoning_effort",
    "role",
    "prompt_sha256",
    "date",
    "session_identity",
}
_PACKET_ROW_KEYS = {"schema_version", "candidate_id", "packet"}
_SCENARIO_ROW_KEYS = {
    "schema_version",
    "scenario_id",
    "source_id",
    "source_group",
    "scenario_group",
    "template_group",
    "publication_class",
    "completion_state",
    "actor_role",
    "style",
    "length_bucket",
    "unicode",
    "slices",
    "blueprint",
}
_BLUEPRINT_KEYS = {
    "local_scope_title",
    "public_state",
    "continuity_state",
    "evidence_appearance",
    "candidate_brief",
}
_SUPERVISION_ROW_KEYS = {
    "schema_version",
    "candidate_id",
    "scenario_id",
    "source_group",
    "scenario_group",
    "template_group",
    "proposed_split",
    "binary_label",
    "publication_class",
    "completion_state",
    "hard_focus",
    "defects",
    "slices",
    "actor_role",
    "style",
    "length_bucket",
    "unicode",
    "generator_identity",
    "reviewer_identity",
    "review_status",
}
_PAIR_ROW_KEYS = {
    "schema_version",
    "pair_id",
    "kind",
    "scenario_id",
    "preferred_candidate_id",
    "dispreferred_candidate_id",
    "target_dimension",
    "soft_preference",
    "review_status",
}
_CANDIDATE_REVIEW_KEYS = {
    "schema_version",
    "candidate_id",
    "decision",
    "independent_label",
    "failed_hard_dimensions",
    "rationale",
    "reviewer_identity",
}
_PAIR_REVIEW_KEYS = {
    "schema_version",
    "pair_id",
    "decision",
    "direction_confirmed",
    "context_equal",
    "omission_equal",
    "atomicity_confirmed",
    "soft_only_confirmed",
    "rationale",
    "reviewer_identity",
}
_PLAN059_SUPERVISION_KEYS = frozenset(
    (_SUPERVISION_ROW_KEYS | _PAIR_ROW_KEYS | _CANDIDATE_REVIEW_KEYS | _PAIR_REVIEW_KEYS)
    - {"schema_version", "actor_role"}
)


class TrainingDataError(ValueError):
    """Raised when Plan 059 data violates its frozen contract."""


def validate_scenario_row(
    row: Mapping[str, Any],
    *,
    allowed_source_ids: set[str] | frozenset[str] | None = None,
) -> None:
    obj = _object(row, "scenario row")
    _exact_keys(obj, _SCENARIO_ROW_KEYS, "scenario row")
    _literal(obj["schema_version"], 1, "scenario row.schema_version")
    for key in ("scenario_id", "source_id", "source_group", "scenario_group", "template_group"):
        _identifier(obj[key], f"scenario row.{key}")
    if allowed_source_ids is not None and obj["source_id"] not in allowed_source_ids:
        _fail("scenario row.source_id is outside the frozen allowlist")
    publication_class = _enum(
        obj["publication_class"],
        PUBLICATION_CLASSES,
        "scenario row.publication_class",
    )
    completion = _enum(obj["completion_state"], {"completed", "incomplete"}, "scenario row.completion_state")
    if publication_class.endswith("_completed") != (completion == "completed"):
        _fail("scenario row completion_state conflicts with publication_class")
    _enum(obj["actor_role"], {"root", "member"}, "scenario row.actor_role")
    _enum(obj["style"], {"formal", "conversational"}, "scenario row.style")
    _enum(obj["length_bucket"], {"short", "medium", "long"}, "scenario row.length_bucket")
    if not isinstance(obj["unicode"], bool):
        _fail("scenario row.unicode must be boolean")
    slices = set(_string_list(obj["slices"], "scenario row.slices", allow_empty=False))
    blueprint = _object(obj["blueprint"], "scenario row.blueprint")
    _exact_keys(blueprint, _BLUEPRINT_KEYS, "scenario row.blueprint")
    for key in ("local_scope_title", "public_state", "candidate_brief"):
        _nonempty_string(blueprint[key], f"scenario row.blueprint.{key}")
    continuity = _enum(
        blueprint["continuity_state"],
        {"not_applicable", "available", "unavailable"},
        "scenario row.blueprint.continuity_state",
    )
    _enum(
        blueprint["evidence_appearance"],
        {"none", "present", "present_omitted", "not_applicable"},
        "scenario row.blueprint.evidence_appearance",
    )
    if publication_class.startswith("new_event_") != (continuity == "not_applicable"):
        _fail("scenario row continuity_state conflicts with publication_class")
    evidence_appearance = blueprint["evidence_appearance"]
    if continuity == "available":
        if evidence_appearance == "not_applicable":
            _fail("available Scenario evidence_appearance cannot be not_applicable")
    elif evidence_appearance != "not_applicable":
        _fail("non-available Scenario evidence_appearance must be not_applicable")
    required_slices = {f"continuity_{continuity}"}
    if evidence_appearance == "present_omitted":
        required_slices.update({"evidence_present", "evidence_count_omitted"})
    else:
        required_slices.add(f"evidence_{evidence_appearance}")
    if not required_slices <= slices:
        _fail(f"scenario row lacks canonical blueprint slices: {sorted(required_slices - slices)}")


def validate_packet_row(
    row: Mapping[str, Any],
    *,
    repo_root: Path | str = REPO_ROOT,
) -> None:
    """Validate the row shell, then delegate packet semantics to Plan 054."""

    obj = _object(row, "packet row")
    _exact_keys(obj, _PACKET_ROW_KEYS, "packet row")
    _literal(obj["schema_version"], 1, "packet row.schema_version")
    _identifier(obj["candidate_id"], "packet row.candidate_id")
    packet = _object(obj["packet"], "packet row.packet")
    fixed = load_fixed_input_contract(repo_root)
    try:
        _reject_plan059_supervision(packet, "packet row.packet")
        _validate_no_supervision(packet, "packet row.packet")
        _validate_packet(packet, "packet row.packet", fixed.product_limits)
    except PublicationCriticContractError as exc:
        raise TrainingDataError(str(exc)) from exc


def validate_supervision_row(row: Mapping[str, Any], *, final: bool = False) -> None:
    obj = _object(row, "supervision row")
    _exact_keys(obj, _SUPERVISION_ROW_KEYS, "supervision row")
    _literal(obj["schema_version"], 1, "supervision row.schema_version")
    for key in ("candidate_id", "scenario_id", "source_group", "scenario_group", "template_group"):
        _identifier(obj[key], f"supervision row.{key}")
    split = obj["proposed_split"]
    if split is not None:
        _enum(split, SPLITS, "supervision row.proposed_split")
    if final and split is None:
        _fail("final supervision row must have a proposed_split")
    label = _enum(obj["binary_label"], {"PASS", "REWRITE"}, "supervision row.binary_label")
    publication_class = _enum(
        obj["publication_class"],
        PUBLICATION_CLASSES,
        "supervision row.publication_class",
    )
    completion = _enum(obj["completion_state"], {"completed", "incomplete"}, "supervision row.completion_state")
    if publication_class.endswith("_completed") != (completion == "completed"):
        _fail("supervision row completion_state conflicts with publication_class")
    hard_focus = obj["hard_focus"]
    if hard_focus is not None:
        _enum(hard_focus, HARD_DIMENSIONS, "supervision row.hard_focus")
    defects = _unique_enum_list(obj["defects"], HARD_DIMENSIONS, "supervision row.defects", allow_empty=True)
    if (label == "PASS") != (not defects):
        _fail("PASS must have no defects and REWRITE must have at least one defect")
    _string_list(obj["slices"], "supervision row.slices", allow_empty=False)
    _enum(obj["actor_role"], {"root", "member"}, "supervision row.actor_role")
    _enum(obj["style"], {"formal", "conversational"}, "supervision row.style")
    _enum(obj["length_bucket"], {"short", "medium", "long"}, "supervision row.length_bucket")
    if not isinstance(obj["unicode"], bool):
        _fail("supervision row.unicode must be boolean")
    validate_teacher_identity(obj["generator_identity"], "supervision row.generator_identity")
    reviewer = obj["reviewer_identity"]
    status = _enum(
        obj["review_status"],
        {"pending", "accept", "revise", "exclude"},
        "supervision row.review_status",
    )
    if reviewer is None:
        if status != "pending":
            _fail("only pending supervision may omit reviewer_identity")
    else:
        validate_teacher_identity(reviewer, "supervision row.reviewer_identity")
    if final and status != "accept":
        _fail("final supervision row must have review_status=accept")


def validate_pair_row(row: Mapping[str, Any], *, final: bool = False) -> None:
    obj = _object(row, "pair row")
    _exact_keys(obj, _PAIR_ROW_KEYS, "pair row")
    _literal(obj["schema_version"], 1, "pair row.schema_version")
    for key in ("pair_id", "scenario_id", "preferred_candidate_id", "dispreferred_candidate_id"):
        _identifier(obj[key], f"pair row.{key}")
    if obj["preferred_candidate_id"] == obj["dispreferred_candidate_id"]:
        _fail("pair endpoints must be distinct")
    kind = _enum(obj["kind"], {"boundary", "within_pass"}, "pair row.kind")
    target = obj["target_dimension"]
    preference = obj["soft_preference"]
    if kind == "boundary":
        _enum(target, HARD_DIMENSIONS, "pair row.target_dimension")
        if preference is not None:
            _fail("boundary pair soft_preference must be null")
    else:
        if target is not None:
            _fail("within_pass target_dimension must be null")
        _nonempty_string(preference, "pair row.soft_preference")
    status = _enum(obj["review_status"], {"pending", "accept", "downgrade", "exclude"}, "pair row.review_status")
    if final and status != "accept":
        _fail("final pair row must have review_status=accept")


def validate_candidate_review(row: Mapping[str, Any]) -> None:
    obj = _object(row, "candidate review")
    _exact_keys(obj, _CANDIDATE_REVIEW_KEYS, "candidate review")
    _literal(obj["schema_version"], 1, "candidate review.schema_version")
    _identifier(obj["candidate_id"], "candidate review.candidate_id")
    _enum(obj["decision"], {"accept", "revise", "exclude"}, "candidate review.decision")
    label = _enum(obj["independent_label"], {"PASS", "REWRITE"}, "candidate review.independent_label")
    failed = _unique_enum_list(
        obj["failed_hard_dimensions"],
        HARD_DIMENSIONS,
        "candidate review.failed_hard_dimensions",
        allow_empty=True,
    )
    if (label == "PASS") != (not failed):
        _fail("candidate review PASS must have no failed hard dimensions")
    _nonempty_string(obj["rationale"], "candidate review.rationale")
    validate_teacher_identity(obj["reviewer_identity"], "candidate review.reviewer_identity")


def validate_pair_review(row: Mapping[str, Any]) -> None:
    obj = _object(row, "pair review")
    _exact_keys(obj, _PAIR_REVIEW_KEYS, "pair review")
    _literal(obj["schema_version"], 1, "pair review.schema_version")
    _identifier(obj["pair_id"], "pair review.pair_id")
    _enum(obj["decision"], {"accept", "downgrade", "exclude"}, "pair review.decision")
    for key in (
        "direction_confirmed",
        "context_equal",
        "omission_equal",
        "atomicity_confirmed",
        "soft_only_confirmed",
    ):
        if not isinstance(obj[key], bool):
            _fail(f"pair review.{key} must be boolean")
    _nonempty_string(obj["rationale"], "pair review.rationale")
    validate_teacher_identity(obj["reviewer_identity"], "pair review.reviewer_identity")


def validate_teacher_identity(value: Any, where: str) -> None:
    obj = _object(value, where)
    _exact_keys(obj, _IDENTITY_KEYS, where)
    for key in ("model", "reasoning_effort", "role", "date", "session_identity"):
        _nonempty_string(obj[key], f"{where}.{key}")
    digest = _nonempty_string(obj["prompt_sha256"], f"{where}.prompt_sha256")
    if not _is_sha256(digest):
        _fail(f"{where}.prompt_sha256 must be lowercase SHA-256")


def validate_dataset(
    packet_rows: Sequence[Mapping[str, Any]],
    supervision_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    *,
    scenario_rows: Sequence[Mapping[str, Any]] = (),
    candidate_reviews: Sequence[Mapping[str, Any]] = (),
    pair_reviews: Sequence[Mapping[str, Any]] = (),
    dropped_oldest_publications: Mapping[str, int] | None = None,
    repo_root: Path | str = REPO_ROOT,
    final: bool = True,
    require_review_records: bool = True,
    require_omission_census: bool = True,
    allowed_source_ids: set[str] | frozenset[str] | None = None,
) -> None:
    packets = _index(packet_rows, "candidate_id", "packet rows")
    supervision = _index(supervision_rows, "candidate_id", "supervision rows")
    if set(packets) != set(supervision):
        _fail("packet and supervision candidate IDs differ")
    for row in packet_rows:
        validate_packet_row(row, repo_root=repo_root)
    for row in supervision_rows:
        validate_supervision_row(row, final=final)
        packet = packets[row["candidate_id"]]["packet"]
        if row["actor_role"] != packet["actor_role"]:
            _fail(f"candidate {row['candidate_id']} actor_role conflicts with packet")
        expected_kind = "new_event" if row["publication_class"].startswith("new_event_") else "existing_event"
        if packet["target_kind"] != expected_kind:
            _fail(f"candidate {row['candidate_id']} publication_class conflicts with packet")
        _validate_packet_slice_projection(packet, row)

    if scenario_rows:
        scenarios = _index(scenario_rows, "scenario_id", "scenario rows")
        for row in scenario_rows:
            validate_scenario_row(row, allowed_source_ids=allowed_source_ids)
        observed_scenarios = {str(row["scenario_id"]) for row in supervision_rows}
        if set(scenarios) != observed_scenarios:
            _fail("Scenario IDs must exactly match supervision Scenario references")
        for candidate_id, row in supervision.items():
            scenario = scenarios[str(row["scenario_id"])]
            for field in (
                "source_group",
                "scenario_group",
                "template_group",
                "publication_class",
                "completion_state",
                "actor_role",
                "style",
                "length_bucket",
                "unicode",
            ):
                if row[field] != scenario[field]:
                    _fail(f"candidate {candidate_id} differs from Scenario field {field}")
            packet = packets[candidate_id]["packet"]
            blueprint = scenario["blueprint"]
            if packet["local_scope"]["title"] != blueprint["local_scope_title"]:
                _fail(f"candidate {candidate_id} title differs from Scenario blueprint")
            if packet["continuity"]["state"] != blueprint["continuity_state"]:
                _fail(f"candidate {candidate_id} continuity differs from Scenario blueprint")
            if _packet_evidence_appearance(packet) != blueprint["evidence_appearance"]:
                _fail(f"candidate {candidate_id} evidence differs from Scenario blueprint")

    reviews = _index(candidate_reviews, "candidate_id", "candidate reviews")
    for row in candidate_reviews:
        validate_candidate_review(row)
    if final and require_review_records and set(reviews) != set(packets):
        _fail("final candidate review IDs must exactly match candidate IDs")
    for candidate_id, review in reviews.items():
        proposed = supervision[candidate_id]
        if final and (review["decision"] != "accept" or review["independent_label"] != proposed["binary_label"]):
            _fail(f"candidate {candidate_id} lacks an accepting review for its Binary label")
        if proposed["reviewer_identity"] != review["reviewer_identity"]:
            _fail(f"candidate {candidate_id} reviewer identity differs between supervision and review")

    pairs = _index(pair_rows, "pair_id", "pair rows")
    if final and require_omission_census and pairs and dropped_oldest_publications is None:
        _fail("final pair validation requires the exact-tokenizer omission census")
    reviews_by_pair = _index(pair_reviews, "pair_id", "pair reviews")
    for row in pair_reviews:
        validate_pair_review(row)
    if final and require_review_records and set(pairs) != set(reviews_by_pair):
        _fail("final pair review IDs must exactly match pair IDs")
    for pair in pair_rows:
        validate_pair_row(pair, final=final)
        _validate_pair_semantics(
            pair,
            packets,
            supervision,
            reviews_by_pair.get(pair["pair_id"]),
            dropped_oldest_publications,
            final=final and require_review_records,
        )


def validate_generation_batch(
    scenario_rows: Sequence[Mapping[str, Any]],
    packet_rows: Sequence[Mapping[str, Any]],
    supervision_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    *,
    allowed_source_ids: set[str] | frozenset[str] | None = None,
    repo_root: Path | str = REPO_ROOT,
) -> None:
    """Validate a raw generator batch before it is sent to the independent reviewer."""

    validate_dataset(
        packet_rows,
        supervision_rows,
        pair_rows,
        scenario_rows=scenario_rows,
        repo_root=repo_root,
        final=False,
        require_review_records=False,
        require_omission_census=False,
        allowed_source_ids=allowed_source_ids,
    )


def _validate_pair_semantics(
    pair: Mapping[str, Any],
    packets: Mapping[str, Mapping[str, Any]],
    supervision: Mapping[str, Mapping[str, Any]],
    review: Mapping[str, Any] | None,
    omissions: Mapping[str, int] | None,
    *,
    final: bool,
) -> None:
    preferred_id = pair["preferred_candidate_id"]
    dispreferred_id = pair["dispreferred_candidate_id"]
    if preferred_id not in packets or dispreferred_id not in packets:
        _fail(f"pair {pair['pair_id']} has a missing candidate endpoint")
    preferred = supervision[preferred_id]
    dispreferred = supervision[dispreferred_id]
    for field in ("scenario_id", "source_group", "scenario_group", "publication_class", "completion_state"):
        if preferred[field] != dispreferred[field]:
            _fail(f"pair {pair['pair_id']} endpoint {field} differs")
    if pair["scenario_id"] != preferred["scenario_id"]:
        _fail(f"pair {pair['pair_id']} scenario_id conflicts with endpoints")
    if preferred["proposed_split"] != dispreferred["proposed_split"]:
        _fail(f"pair {pair['pair_id']} endpoints have different splits")
    left_context = {key: value for key, value in packets[preferred_id]["packet"].items() if key != "candidate"}
    right_context = {key: value for key, value in packets[dispreferred_id]["packet"].items() if key != "candidate"}
    if left_context != right_context:
        _fail(f"pair {pair['pair_id']} changes non-candidate model-visible context")
    if omissions is not None:
        if preferred_id not in omissions or dispreferred_id not in omissions:
            _fail(f"pair {pair['pair_id']} lacks final omission census")
        if omissions[preferred_id] != omissions[dispreferred_id]:
            _fail(f"pair {pair['pair_id']} endpoints have different final omissions")
    if pair["kind"] == "boundary":
        if (preferred["binary_label"], dispreferred["binary_label"]) != ("PASS", "REWRITE"):
            _fail(f"boundary pair {pair['pair_id']} must be PASS > REWRITE")
        if dispreferred["hard_focus"] != pair["target_dimension"]:
            _fail(f"boundary pair {pair['pair_id']} target_dimension conflicts with Q-")
    elif (preferred["binary_label"], dispreferred["binary_label"]) != ("PASS", "PASS"):
        _fail(f"within_pass pair {pair['pair_id']} must be PASS > PASS")
    if final:
        if review is None or review["decision"] != "accept":
            _fail(f"pair {pair['pair_id']} lacks an accepting review")
        required_true = ("direction_confirmed", "context_equal", "omission_equal")
        if not all(review[key] for key in required_true):
            _fail(f"pair {pair['pair_id']} review does not confirm direction/context/omission")
        if pair["kind"] == "boundary" and not review["atomicity_confirmed"]:
            _fail(f"boundary pair {pair['pair_id']} review does not confirm atomicity")
        if pair["kind"] == "within_pass" and not review["soft_only_confirmed"]:
            _fail(f"within_pass pair {pair['pair_id']} review does not confirm soft-only semantics")


def _index(rows: Sequence[Mapping[str, Any]], key: str, where: str) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for index, row in enumerate(rows):
        obj = _object(row, f"{where}[{index}]")
        value = _identifier(obj.get(key), f"{where}[{index}].{key}")
        if value in result:
            _fail(f"duplicate {key} in {where}: {value}")
        result[value] = obj
    return result


def _validate_packet_slice_projection(packet: Mapping[str, Any], supervision: Mapping[str, Any]) -> None:
    slices = set(supervision["slices"])
    continuity = packet["continuity"]
    state = continuity["state"]
    continuity_slices = {
        name for name in slices if name in {
            "continuity_available",
            "continuity_unavailable",
            "continuity_not_applicable",
        }
    }
    expected_continuity = f"continuity_{state}"
    if continuity_slices != {expected_continuity}:
        _fail(
            f"candidate {supervision['candidate_id']} continuity slices do not match packet"
        )
    evidence_appearance = _packet_evidence_appearance(packet)
    if evidence_appearance == "present_omitted":
        expected_evidence = {"evidence_present", "evidence_count_omitted"}
    else:
        expected_evidence = {f"evidence_{evidence_appearance}"}
    observed_evidence = {
        name for name in slices if name in {
            "evidence_none",
            "evidence_present",
            "evidence_count_omitted",
            "evidence_not_applicable",
        }
    }
    if observed_evidence != expected_evidence:
        _fail(f"candidate {supervision['candidate_id']} evidence slices do not match packet")
    freshness = continuity.get("freshness")
    if (freshness == "known_stale") != ("freshness_known_stale" in slices):
        _fail(f"candidate {supervision['candidate_id']} freshness slice does not match packet")


def _packet_evidence_appearance(packet: Mapping[str, Any]) -> str:
    continuity = packet["continuity"]
    if continuity["state"] != "available":
        return "not_applicable"
    references = [
        prior["evidence"]["fact_references"]
        for prior in continuity["prior_publications"]
    ]
    if any(reference.get("count_omitted") for reference in references):
        return "present_omitted"
    if any(reference["state"] == "present" for reference in references):
        return "present"
    return "none"


def _object(value: Any, where: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        _fail(f"{where} must be an object")
    return value


def _exact_keys(value: Mapping[str, Any], expected: set[str], where: str) -> None:
    if set(value) != expected:
        _fail(f"{where} keys differ: missing={sorted(expected - set(value))}, extra={sorted(set(value) - expected)}")


def _literal(value: Any, expected: Any, where: str) -> None:
    if value != expected or type(value) is not type(expected):
        _fail(f"{where} must equal {expected!r}")


def _nonempty_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{where} must be a non-empty string")
    return value


def _identifier(value: Any, where: str) -> str:
    text = _nonempty_string(value, where)
    if len(text) > 160 or any(character.isspace() for character in text):
        _fail(f"{where} must be a bounded whitespace-free identifier")
    return text


def _enum(value: Any, allowed: set[str] | frozenset[str], where: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        _fail(f"{where} must be one of {sorted(allowed)}")
    return value


def _string_list(value: Any, where: str, *, allow_empty: bool) -> tuple[str, ...]:
    if not isinstance(value, list) or (not allow_empty and not value):
        _fail(f"{where} must be {'a' if allow_empty else 'a non-empty'} list")
    items = tuple(_nonempty_string(item, f"{where}[{index}]") for index, item in enumerate(value))
    if len(items) != len(set(items)):
        _fail(f"{where} must contain unique values")
    return items


def _unique_enum_list(
    value: Any,
    allowed: set[str] | frozenset[str],
    where: str,
    *,
    allow_empty: bool,
) -> tuple[str, ...]:
    items = _string_list(value, where, allow_empty=allow_empty)
    for index, item in enumerate(items):
        _enum(item, allowed, f"{where}[{index}]")
    return items


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _reject_plan059_supervision(value: Any, where: str) -> None:
    if isinstance(value, Mapping):
        forbidden = sorted(set(value) & _PLAN059_SUPERVISION_KEYS)
        if forbidden:
            _fail(f"{where} contains Plan 059 supervision keys: {forbidden}")
        for key, nested in value.items():
            _reject_plan059_supervision(nested, f"{where}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _reject_plan059_supervision(nested, f"{where}[{index}]")


def _fail(message: str) -> None:
    raise TrainingDataError(message)
