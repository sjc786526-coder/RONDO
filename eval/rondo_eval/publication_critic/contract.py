"""Strict loaders for the frozen Publication Critic inputs.

This module owns only the tracked input shape and supervision boundary. Product
limits, canonicalization, freshness interpretation, rendering, and scoring stay
with their respective owners.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, NoReturn, Sequence


REPO_ROOT = Path(__file__).resolve().parents[3]
_FIXTURE_DIR = Path("eval/fixtures/publication-critic-v1")
_TEMPLATE_DIR = Path("eval/templates/publication-critic")

_PUBLICATION_CLASSES = frozenset(
    {
        "new_event_completed",
        "new_event_incomplete",
        "existing_event_completed",
        "existing_event_incomplete",
    }
)
_DATA_ROLES = frozenset({"m3a2_calibration", "m3a2_measurement"})
_VERDICTS = frozenset({"pass", "rewrite"})
_SUPERVISION_KEYS = frozenset(
    {
        "data_role",
        "publication_class",
        "completion_state",
        "expected_verdict",
        "pair_id",
        "pair_direction",
        "slices",
        "rationale_anchor",
        "source_identity",
        "reviewer_identity",
    }
)


class PublicationCriticContractError(ValueError):
    """Raised when a tracked Publication Critic input violates its contract."""


@dataclass(frozen=True)
class PublicationCriticFixedInput:
    input_contract: str
    rubric: str
    render_contract: Mapping[str, Any]
    product_limits: Mapping[str, Any]


@dataclass(frozen=True)
class PublicationCriticSample:
    sample_id: str
    packet: Mapping[str, Any]
    annotation: Mapping[str, Any]


@dataclass(frozen=True)
class PublicationCriticCorpus:
    samples: tuple[PublicationCriticSample, ...]

    @property
    def by_id(self) -> Mapping[str, PublicationCriticSample]:
        return MappingProxyType({sample.sample_id: sample for sample in self.samples})


def load_fixed_input_contract(
    repo_root: Path | str = REPO_ROOT,
) -> PublicationCriticFixedInput:
    root = Path(repo_root)
    input_contract = _read_text(root / _TEMPLATE_DIR / "input-contract-v1.md")
    if not input_contract.strip():
        _fail("model input contract must not be empty")
    rubric = _read_text(root / _TEMPLATE_DIR / "qualification-rubric-v1.md")
    if not rubric.strip():
        _fail("qualification rubric must not be empty")
    render = _load_json(root / _TEMPLATE_DIR / "render-contract-v2.json")
    _validate_render_contract(render)
    limits = _load_json(root / _TEMPLATE_DIR / "product-packet-limits-v1.json")
    _validate_product_limits(limits)
    return PublicationCriticFixedInput(
        input_contract=input_contract,
        rubric=rubric,
        render_contract=_freeze(render),
        product_limits=_freeze(limits),
    )


def _validate_product_limits(value: Any) -> None:
    limits = _require_object(value, "product packet limits")
    _require_exact_keys(
        limits,
        {
            "schema_version",
            "name",
            "revision",
            "title",
            "summary",
            "handoff",
            "max_prior_publications",
            "max_visible_fact_references",
        },
        "product packet limits",
    )
    _require_literal(limits["schema_version"], 1, "product packet limits.schema_version")
    _require_literal(limits["name"], "rondo-publication-packet-limits", "product packet limits.name")
    _require_literal(limits["revision"], "v1", "product packet limits.revision")
    for field in ("title", "summary", "handoff"):
        text_limit = _require_object(limits[field], f"product packet limits.{field}")
        _require_exact_keys(text_limit, {"max_scalars", "max_bytes"}, f"product packet limits.{field}")
        _require_nonnegative_int(text_limit["max_scalars"], f"product packet limits.{field}.max_scalars")
        _require_nonnegative_int(text_limit["max_bytes"], f"product packet limits.{field}.max_bytes")
    _require_nonnegative_int(limits["max_prior_publications"], "product packet limits.max_prior_publications")
    _require_nonnegative_int(limits["max_visible_fact_references"], "product packet limits.max_visible_fact_references")


def load_sample_corpus(repo_root: Path | str = REPO_ROOT) -> PublicationCriticCorpus:
    root = Path(repo_root)
    packet_rows = _load_jsonl(root / _FIXTURE_DIR / "packets.jsonl")
    annotation_rows = _load_jsonl(root / _FIXTURE_DIR / "annotations.jsonl")

    packets: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(packet_rows, start=1):
        where = f"packets.jsonl:{index}"
        _require_exact_keys(row, {"schema_version", "sample_id", "packet"}, where)
        _require_literal(row["schema_version"], 1, f"{where}.schema_version")
        sample_id = _require_nonempty_string(row["sample_id"], f"{where}.sample_id")
        if sample_id in packets:
            _fail(f"duplicate packet sample_id: {sample_id}")
        packet = _require_object(row["packet"], f"{where}.packet")
        _validate_no_supervision(packet, f"{where}.packet")
        _validate_packet(packet, f"{where}.packet")
        packets[sample_id] = packet

    annotations: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(annotation_rows, start=1):
        where = f"annotations.jsonl:{index}"
        _validate_annotation(row, where)
        sample_id = row["sample_id"]
        if sample_id in annotations:
            _fail(f"duplicate annotation sample_id: {sample_id}")
        annotations[sample_id] = row

    packet_ids = set(packets)
    annotation_ids = set(annotations)
    if packet_ids != annotation_ids:
        missing_annotations = sorted(packet_ids - annotation_ids)
        missing_packets = sorted(annotation_ids - packet_ids)
        _fail(
            "packet/annotation sample_id mismatch: "
            f"missing_annotations={missing_annotations}, missing_packets={missing_packets}"
        )

    ordered_samples = tuple(
        PublicationCriticSample(
            sample_id=sample_id,
            packet=_freeze(packet),
            annotation=_freeze(annotations[sample_id]),
        )
        for sample_id, packet in packets.items()
    )
    _validate_corpus_shape(ordered_samples)
    return PublicationCriticCorpus(samples=ordered_samples)


def _validate_render_contract(value: Any) -> None:
    contract = _require_object(value, "render contract")
    _require_exact_keys(
        contract,
        {
            "schema_version",
            "name",
            "revision",
            "messages",
            "token_accounting",
            "render_compatibility",
            "chat_template",
            "context",
            "padding",
        },
        "render contract",
    )
    _require_literal(contract["schema_version"], 1, "render contract.schema_version")
    _require_literal(contract["name"], "rondo-publication-critic-render", "render contract.name")
    _require_literal(contract["revision"], "v2", "render contract.revision")

    messages = _require_object(contract["messages"], "render contract.messages")
    _require_exact_keys(messages, {"system", "count", "user", "assistant"}, "render contract.messages")
    _require_literal(messages["system"], "absent", "render contract.messages.system")
    _require_literal(messages["count"], 2, "render contract.messages.count")

    user = _require_object(messages["user"], "render contract.messages.user")
    _require_exact_keys(user, {"order", "components", "excluded_fields"}, "render contract.messages.user")
    _require_sequence_literal(user["order"], ["qualification_rubric", "public_context"], "render contract.messages.user.order")
    _require_sequence_literal(user["excluded_fields"], ["candidate", "supervision"], "render contract.messages.user.excluded_fields")

    components = _require_object(user["components"], "render contract.messages.user.components")
    _require_exact_keys(components, {"packet", "continuity", "evidence_v1"}, "render contract.messages.user.components")
    packet_component = _require_object(components["packet"], "render contract.messages.user.components.packet")
    _require_exact_keys(packet_component, {"fields"}, "render contract.messages.user.components.packet")
    _require_sequence_literal(
        packet_component["fields"],
        ["qualification", "actor_role", "target_kind", "local_scope.title"],
        "render contract.messages.user.components.packet.fields",
    )
    continuity_component = _require_object(
        components["continuity"],
        "render contract.messages.user.components.continuity",
    )
    _require_exact_keys(continuity_component, {"fields"}, "render contract.messages.user.components.continuity")
    _require_sequence_literal(
        continuity_component["fields"],
        ["continuity"],
        "render contract.messages.user.components.continuity.fields",
    )
    evidence_component = _require_object(
        components["evidence_v1"],
        "render contract.messages.user.components.evidence_v1",
    )
    _require_exact_keys(evidence_component, {"fields"}, "render contract.messages.user.components.evidence_v1")
    _require_sequence_literal(
        evidence_component["fields"],
        ["evidence_v1"],
        "render contract.messages.user.components.evidence_v1.fields",
    )

    assistant = _require_object(messages["assistant"], "render contract.messages.assistant")
    _require_exact_keys(assistant, {"component", "fields"}, "render contract.messages.assistant")
    _require_literal(assistant["component"], "candidate", "render contract.messages.assistant.component")
    _require_sequence_literal(
        assistant["fields"],
        ["candidate.summary", "candidate.handoff"],
        "render contract.messages.assistant.fields",
    )

    token_accounting = _require_object(contract["token_accounting"], "render contract.token_accounting")
    _require_exact_keys(
        token_accounting,
        {"candidate_semantic_fields", "canonical_title"},
        "render contract.token_accounting",
    )
    _require_sequence_literal(
        token_accounting["candidate_semantic_fields"],
        ["local_scope.title", "candidate.summary", "candidate.handoff"],
        "render contract.token_accounting.candidate_semantic_fields",
    )
    canonical_title = _require_object(
        token_accounting["canonical_title"],
        "render contract.token_accounting.canonical_title",
    )
    _require_exact_keys(
        canonical_title,
        {"source", "message_role", "render_component", "token_bucket"},
        "render contract.token_accounting.canonical_title",
    )
    _require_literal(
        canonical_title["source"],
        "local_scope.title",
        "render contract.token_accounting.canonical_title.source",
    )
    _require_literal(
        canonical_title["message_role"],
        "user",
        "render contract.token_accounting.canonical_title.message_role",
    )
    _require_literal(
        canonical_title["render_component"],
        "packet",
        "render contract.token_accounting.canonical_title.render_component",
    )
    _require_literal(
        canonical_title["token_bucket"],
        "candidate",
        "render contract.token_accounting.canonical_title.token_bucket",
    )

    compatibility = _require_object(
        contract["render_compatibility"],
        "render contract.render_compatibility",
    )
    _require_exact_keys(
        compatibility,
        {"model_visible_bytes", "message_roles"},
        "render contract.render_compatibility",
    )
    _require_literal(
        compatibility["model_visible_bytes"],
        "identical_to_rondo-publication-critic-render@v1",
        "render contract.render_compatibility.model_visible_bytes",
    )
    _require_sequence_literal(
        compatibility["message_roles"],
        ["user", "assistant"],
        "render contract.render_compatibility.message_roles",
    )

    chat_template = _require_object(contract["chat_template"], "render contract.chat_template")
    _require_exact_keys(chat_template, {"source", "add_generation_prompt"}, "render contract.chat_template")
    _require_literal(chat_template["source"], "frozen_tokenizer", "render contract.chat_template.source")
    _require_literal(chat_template["add_generation_prompt"], False, "render contract.chat_template.add_generation_prompt")

    context = _require_object(contract["context"], "render contract.context")
    _require_exact_keys(context, {"adopted_window_tokens", "mandatory", "candidate_truncation", "overflow"}, "render contract.context")
    _require_literal(context["adopted_window_tokens"], 16_384, "render contract.context.adopted_window_tokens")
    _require_sequence_literal(
        context["mandatory"],
        ["qualification_rubric", "local_scope.title", "candidate.summary", "candidate.handoff"],
        "render contract.context.mandatory",
    )
    _require_literal(context["candidate_truncation"], "forbidden", "render contract.context.candidate_truncation")

    overflow = _require_object(context["overflow"], "render contract.context.overflow")
    _require_exact_keys(
        overflow,
        {
            "strategy",
            "unit",
            "rerender_and_retokenize_after_each_drop",
            "render_only_omission_field",
            "render_only_omission_is_additional_to_packet_coverage",
            "mandatory_content_overflow",
        },
        "render contract.context.overflow",
    )
    _require_literal(overflow["strategy"], "drop_oldest_continuity_item", "render contract.context.overflow.strategy")
    _require_literal(overflow["unit"], "whole_prior_publication", "render contract.context.overflow.unit")
    _require_literal(overflow["rerender_and_retokenize_after_each_drop"], True, "render contract.context.overflow.rerender_and_retokenize_after_each_drop")
    _require_literal(overflow["render_only_omission_field"], "model_window_additional_oldest_omitted", "render contract.context.overflow.render_only_omission_field")
    _require_literal(overflow["render_only_omission_is_additional_to_packet_coverage"], True, "render contract.context.overflow.render_only_omission_is_additional_to_packet_coverage")
    _require_literal(overflow["mandatory_content_overflow"], "typed_input_failure", "render contract.context.overflow.mandatory_content_overflow")

    padding = _require_object(contract["padding"], "render contract.padding")
    _require_exact_keys(padding, {"binding", "semantic_parity_required"}, "render contract.padding")
    _require_literal(padding["binding"], "scoring_identity", "render contract.padding.binding")
    _require_literal(padding["semantic_parity_required"], True, "render contract.padding.semantic_parity_required")


def _validate_packet(packet: Mapping[str, Any], where: str) -> None:
    _require_exact_keys(
        packet,
        {"qualification", "actor_role", "target_kind", "local_scope", "candidate", "continuity", "evidence_v1"},
        where,
    )
    qualification = _require_object(packet["qualification"], f"{where}.qualification")
    _require_exact_keys(qualification, {"packet_schema", "rubric"}, f"{where}.qualification")
    _validate_named_revision(qualification["packet_schema"], "rondo-publication-packet", f"{where}.qualification.packet_schema")
    _validate_named_revision(qualification["rubric"], "rondo-publication-qualification", f"{where}.qualification.rubric")

    _require_enum(packet["actor_role"], {"root", "member"}, f"{where}.actor_role")
    target_kind = _require_enum(packet["target_kind"], {"new_event", "existing_event"}, f"{where}.target_kind")

    local_scope = _require_object(packet["local_scope"], f"{where}.local_scope")
    _require_exact_keys(local_scope, {"title"}, f"{where}.local_scope")
    _require_string(local_scope["title"], f"{where}.local_scope.title")

    candidate = _require_object(packet["candidate"], f"{where}.candidate")
    _require_exact_keys(candidate, {"summary", "handoff"}, f"{where}.candidate")
    _require_string(candidate["summary"], f"{where}.candidate.summary")
    _require_optional_string(candidate["handoff"], f"{where}.candidate.handoff")

    continuity = _require_object(packet["continuity"], f"{where}.continuity")
    state = continuity.get("state")
    if state == "not_applicable":
        _require_exact_keys(continuity, {"state"}, f"{where}.continuity")
    elif state == "available":
        _validate_available_continuity(continuity, f"{where}.continuity")
    elif state == "unavailable":
        _require_exact_keys(continuity, {"state", "last_known_revision", "freshness"}, f"{where}.continuity")
        _require_optional_nonnegative_int(continuity["last_known_revision"], f"{where}.continuity.last_known_revision")
        _require_enum(continuity["freshness"], {"known_stale", "unknown"}, f"{where}.continuity.freshness")
    else:
        _fail(f"{where}.continuity.state must be not_applicable, available, or unavailable")

    if target_kind == "new_event" and state != "not_applicable":
        _fail(f"{where}.continuity must be not_applicable for new_event")
    if target_kind == "existing_event" and state not in {"available", "unavailable"}:
        _fail(f"{where}.continuity must be available or unavailable for existing_event")

    evidence = _require_object(packet["evidence_v1"], f"{where}.evidence_v1")
    _require_exact_keys(evidence, {"semantic_entailment", "candidate_window"}, f"{where}.evidence_v1")
    _require_literal(evidence["semantic_entailment"], "not_evaluated", f"{where}.evidence_v1.semantic_entailment")
    _require_literal(evidence["candidate_window"], "not_frozen_before_commit", f"{where}.evidence_v1.candidate_window")


def _validate_available_continuity(continuity: Mapping[str, Any], where: str) -> None:
    _require_exact_keys(
        continuity,
        {"state", "source_team_revision", "freshness", "coverage", "prior_publications"},
        where,
    )
    _require_nonnegative_int(continuity["source_team_revision"], f"{where}.source_team_revision")
    _require_enum(continuity["freshness"], {"current", "known_stale", "unknown"}, f"{where}.freshness")
    coverage = _require_object(continuity["coverage"], f"{where}.coverage")
    coverage_state = coverage.get("state")
    if coverage_state == "complete":
        _require_exact_keys(coverage, {"state"}, f"{where}.coverage")
    elif coverage_state == "partial":
        _require_exact_keys(coverage, {"state", "omitted_count"}, f"{where}.coverage")
        _require_optional_nonnegative_int(coverage["omitted_count"], f"{where}.coverage.omitted_count")
    else:
        _fail(f"{where}.coverage.state must be complete or partial")

    prior_publications = _require_list(continuity["prior_publications"], f"{where}.prior_publications")
    for index, prior in enumerate(prior_publications):
        prior_where = f"{where}.prior_publications[{index}]"
        prior_object = _require_object(prior, prior_where)
        _require_exact_keys(prior_object, {"summary", "handoff", "evidence"}, prior_where)
        _require_string(prior_object["summary"], f"{prior_where}.summary")
        _require_optional_string(prior_object["handoff"], f"{prior_where}.handoff")
        evidence = _require_object(prior_object["evidence"], f"{prior_where}.evidence")
        _require_exact_keys(evidence, {"fact_references", "observation_availability"}, f"{prior_where}.evidence")
        _require_literal(evidence["observation_availability"], "unknown", f"{prior_where}.evidence.observation_availability")
        fact_references = _require_object(evidence["fact_references"], f"{prior_where}.evidence.fact_references")
        fact_state = fact_references.get("state")
        if fact_state == "none":
            _require_exact_keys(fact_references, {"state"}, f"{prior_where}.evidence.fact_references")
        elif fact_state == "present":
            _require_exact_keys(
                fact_references,
                {"state", "visible_count", "count_omitted"},
                f"{prior_where}.evidence.fact_references",
            )
            _require_nonnegative_int(fact_references["visible_count"], f"{prior_where}.evidence.fact_references.visible_count")
            _require_bool(fact_references["count_omitted"], f"{prior_where}.evidence.fact_references.count_omitted")
        else:
            _fail(f"{prior_where}.evidence.fact_references.state must be none or present")


def _validate_annotation(annotation: Mapping[str, Any], where: str) -> None:
    annotation = _require_object(annotation, where)
    expected_keys = {"schema_version", "sample_id", *_SUPERVISION_KEYS}
    _require_exact_keys(annotation, expected_keys, where)
    _require_literal(annotation["schema_version"], 1, f"{where}.schema_version")
    _require_nonempty_string(annotation["sample_id"], f"{where}.sample_id")
    _require_enum(annotation["data_role"], _DATA_ROLES, f"{where}.data_role")
    publication_class = _require_enum(annotation["publication_class"], _PUBLICATION_CLASSES, f"{where}.publication_class")
    completion_state = _require_enum(annotation["completion_state"], {"completed", "incomplete"}, f"{where}.completion_state")
    if publication_class.endswith("_completed") and completion_state != "completed":
        _fail(f"{where}.completion_state conflicts with publication_class")
    if publication_class.endswith("_incomplete") and completion_state != "incomplete":
        _fail(f"{where}.completion_state conflicts with publication_class")
    verdict = _require_enum(annotation["expected_verdict"], _VERDICTS, f"{where}.expected_verdict")
    _require_nonempty_string(annotation["pair_id"], f"{where}.pair_id")
    pair_direction = _require_enum(annotation["pair_direction"], {"positive", "negative"}, f"{where}.pair_direction")
    if (verdict, pair_direction) not in {("pass", "positive"), ("rewrite", "negative")}:
        _fail(f"{where}.pair_direction must be positive for pass and negative for rewrite")
    slices = _require_list(annotation["slices"], f"{where}.slices")
    if not slices:
        _fail(f"{where}.slices must not be empty")
    normalized_slices = [_require_nonempty_string(item, f"{where}.slices[{index}]") for index, item in enumerate(slices)]
    if len(normalized_slices) != len(set(normalized_slices)):
        _fail(f"{where}.slices must be unique")
    _require_nonempty_string(annotation["rationale_anchor"], f"{where}.rationale_anchor")
    _require_literal(annotation["source_identity"], "plan054-synthetic-product-shaped-v1", f"{where}.source_identity")
    _require_literal(annotation["reviewer_identity"], "plan054-contract-application-v1", f"{where}.reviewer_identity")


def _validate_corpus_shape(samples: Sequence[PublicationCriticSample]) -> None:
    if len(samples) != 24:
        _fail(f"corpus must contain exactly 24 samples, got {len(samples)}")
    roles = Counter(sample.annotation["data_role"] for sample in samples)
    if roles != Counter({"m3a2_calibration": 8, "m3a2_measurement": 16}):
        _fail(f"corpus role balance is invalid: {dict(roles)}")
    classes = Counter(sample.annotation["publication_class"] for sample in samples)
    if classes != Counter({publication_class: 6 for publication_class in _PUBLICATION_CLASSES}):
        _fail(f"corpus publication-class balance is invalid: {dict(classes)}")
    verdicts = Counter(sample.annotation["expected_verdict"] for sample in samples)
    if verdicts != Counter({"pass": 12, "rewrite": 12}):
        _fail(f"corpus verdict balance is invalid: {dict(verdicts)}")

    pairs: dict[str, list[PublicationCriticSample]] = defaultdict(list)
    for sample in samples:
        pairs[sample.annotation["pair_id"]].append(sample)
    if len(pairs) != 12:
        _fail(f"corpus must contain exactly 12 atomic pairs, got {len(pairs)}")
    for pair_id, pair in pairs.items():
        if len(pair) != 2:
            _fail(f"pair {pair_id} must contain exactly two samples")
        signature = {
            (
                sample.annotation["data_role"],
                sample.annotation["publication_class"],
                sample.annotation["completion_state"],
            )
            for sample in pair
        }
        if len(signature) != 1:
            _fail(f"pair {pair_id} must keep role, class, and completion state fixed")
        outcomes = {
            (sample.annotation["expected_verdict"], sample.annotation["pair_direction"])
            for sample in pair
        }
        if outcomes != {("pass", "positive"), ("rewrite", "negative")}:
            _fail(f"pair {pair_id} must contain one pass/positive and one rewrite/negative")


def _validate_named_revision(value: Any, name: str, where: str) -> None:
    obj = _require_object(value, where)
    _require_exact_keys(obj, {"name", "revision"}, where)
    _require_literal(obj["name"], name, f"{where}.name")
    _require_literal(obj["revision"], "v1", f"{where}.revision")


def _validate_no_supervision(value: Any, where: str) -> None:
    if isinstance(value, dict):
        forbidden = sorted(set(value) & _SUPERVISION_KEYS)
        if forbidden:
            _fail(f"{where} contains supervision keys: {forbidden}")
        for key, nested in value.items():
            _validate_no_supervision(nested, f"{where}.{key}")
    elif isinstance(value, list):
        for index, nested in enumerate(value):
            _validate_no_supervision(nested, f"{where}[{index}]")


def _load_json(path: Path) -> Any:
    text = _read_text(path)
    try:
        return json.loads(text, parse_constant=_reject_nonfinite)
    except (json.JSONDecodeError, PublicationCriticContractError) as exc:
        raise PublicationCriticContractError(f"invalid JSON in {path}: {exc}") from exc


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    text = _read_text(path)
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            _fail(f"blank line in {path}:{index}")
        try:
            value = json.loads(line, parse_constant=_reject_nonfinite)
        except (json.JSONDecodeError, PublicationCriticContractError) as exc:
            raise PublicationCriticContractError(f"invalid JSON in {path}:{index}: {exc}") from exc
        rows.append(_require_object(value, f"{path}:{index}"))
    if not rows:
        _fail(f"{path} must not be empty")
    return rows


def _read_text(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        _fail(f"required input is not a regular non-symlink file: {path}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise PublicationCriticContractError(f"cannot read {path}: {exc}") from exc


def _freeze(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(nested) for key, nested in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(nested) for nested in value)
    return value


def _require_object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{where} must be an object")
    return value


def _require_list(value: Any, where: str) -> list[Any]:
    if not isinstance(value, list):
        _fail(f"{where} must be an array")
    return value


def _require_string(value: Any, where: str) -> str:
    if not isinstance(value, str):
        _fail(f"{where} must be a string")
    return value


def _require_nonempty_string(value: Any, where: str) -> str:
    value = _require_string(value, where)
    if not value:
        _fail(f"{where} must not be empty")
    return value


def _require_optional_string(value: Any, where: str) -> None:
    if value is not None:
        _require_string(value, where)


def _require_nonnegative_int(value: Any, where: str) -> int:
    if type(value) is not int or value < 0:
        _fail(f"{where} must be a non-negative integer")
    return value


def _require_optional_nonnegative_int(value: Any, where: str) -> None:
    if value is not None:
        _require_nonnegative_int(value, where)


def _require_bool(value: Any, where: str) -> bool:
    if type(value) is not bool:
        _fail(f"{where} must be a boolean")
    return value


def _require_enum(value: Any, allowed: set[str] | frozenset[str], where: str) -> str:
    value = _require_string(value, where)
    if value not in allowed:
        _fail(f"{where} must be one of {sorted(allowed)}")
    return value


def _require_literal(value: Any, expected: Any, where: str) -> None:
    if type(value) is not type(expected) or value != expected:
        _fail(f"{where} must equal {expected!r}")


def _require_sequence_literal(value: Any, expected: list[str], where: str) -> None:
    if not isinstance(value, list) or value != expected:
        _fail(f"{where} must equal {expected!r}")


def _require_exact_keys(value: Mapping[str, Any], expected: set[str], where: str) -> None:
    actual = set(value)
    if actual != expected:
        _fail(f"{where} keys differ: missing={sorted(expected - actual)}, extra={sorted(actual - expected)}")


def _reject_nonfinite(value: str) -> NoReturn:
    _fail(f"non-finite JSON number is forbidden: {value}")


def _fail(message: str) -> NoReturn:
    raise PublicationCriticContractError(message)
