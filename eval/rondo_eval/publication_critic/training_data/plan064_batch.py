"""Compile a compact Plan 064 authoring batch into the existing v1 row contracts.

The batch format removes repeated packet and supervision boilerplate from data
authoring.  This module deliberately does not define another dataset contract:
after expansion, :func:`validate_generation_batch` remains the sole semantic
gate for Scenario, PublicationPacket, supervision, and pair rows.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
from typing import Any, NoReturn

from ..contract import REPO_ROOT
from ..identity import canonical_json_bytes, sha256_bytes
from .contract import (
    TrainingDataError,
    validate_candidate_review,
    validate_generation_batch,
    validate_pair_review,
)


BATCH_SCHEMA = "rondo-publication-critic-plan064-batch-v1"
SOURCE_ID = "plan064-synthetic-product-shaped-v1"
PLAN064_NAMESPACE = Path(
    "/home/sjc/desktop/RONDO/eval-data/publication-critic/plan064"
)

_QUALIFICATION = {
    "packet_schema": {"name": "rondo-publication-packet", "revision": "v1"},
    "rubric": {"name": "rondo-publication-qualification", "revision": "v1"},
}
_EVIDENCE_V1 = {
    "semantic_entailment": "not_evaluated",
    "candidate_window": "not_frozen_before_commit",
}
_TOP_KEYS = {"schema", "batch_id", "generator_identity", "scenarios"}
_SCENARIO_KEYS = {
    "scenario_id",
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
    "proposed_split",
    "continuity",
    "candidates",
    "pairs",
}
_CANDIDATE_KEYS = {"id_suffix", "label", "summary", "handoff", "defects"}
_PAIR_KEYS = {
    "id_suffix",
    "kind",
    "preferred",
    "dispreferred",
    "target_dimension",
    "soft_preference",
}
_OUTPUT_FILES = (
    "scenarios.jsonl",
    "packets.jsonl",
    "supervision.jsonl",
    "pairs.jsonl",
)
REVIEW_BINDING_FILE = "review-binding.json"
AGGREGATE_REVIEW_BINDINGS_FILE = "review-bindings.json"
_REVIEW_BINDING_SCHEMA = "rondo-publication-critic-plan064-review-binding-v1"
_AGGREGATE_REVIEW_BINDINGS_SCHEMA = (
    "rondo-publication-critic-plan064-aggregate-review-bindings-v1"
)
_BOUND_ROW_SPECS = (
    ("scenarios", "scenario_id"),
    ("packets", "candidate_id"),
    ("supervision", "candidate_id"),
    ("pairs", "pair_id"),
    ("candidate_reviews", "candidate_id"),
    ("pair_reviews", "pair_id"),
)
_REVIEW_BINDING_KEYS = {"schema", "counts", "semantic_sha256"}
_REVIEW_BINDING_CONTENT_KEYS = {name for name, _ in _BOUND_ROW_SPECS}
_AGGREGATE_REVIEW_BINDINGS_KEYS = {"schema", "source_bindings", "aggregate"}


@dataclass(frozen=True)
class CompiledPlan064Batch:
    """The four raw v1 row collections emitted by a Plan 064 batch."""

    batch_id: str
    scenarios: tuple[dict[str, Any], ...]
    packets: tuple[dict[str, Any], ...]
    supervision: tuple[dict[str, Any], ...]
    pairs: tuple[dict[str, Any], ...]

    def rows_by_filename(self) -> dict[str, tuple[dict[str, Any], ...]]:
        return {
            "scenarios.jsonl": self.scenarios,
            "packets.jsonl": self.packets,
            "supervision.jsonl": self.supervision,
            "pairs.jsonl": self.pairs,
        }


def compile_plan064_batch(
    value: Any,
    *,
    repo_root: Path | str = REPO_ROOT,
) -> CompiledPlan064Batch:
    """Expand one strict authoring object and validate the resulting v1 rows."""

    batch = _object(value, "Plan 064 batch")
    _exact_keys(batch, _TOP_KEYS, "Plan 064 batch")
    if batch["schema"] != BATCH_SCHEMA:
        _fail(f"Plan 064 batch.schema must equal {BATCH_SCHEMA!r}")
    batch_id = _prefixed_identifier(
        batch["batch_id"],
        "p064-batch-",
        "Plan 064 batch.batch_id",
    )
    generator_identity = _object(
        batch["generator_identity"],
        "Plan 064 batch.generator_identity",
    )
    scenarios = _array(batch["scenarios"], "Plan 064 batch.scenarios", allow_empty=False)

    scenario_rows: list[dict[str, Any]] = []
    packet_rows: list[dict[str, Any]] = []
    supervision_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    for index, raw in enumerate(scenarios):
        where = f"Plan 064 batch.scenarios[{index}]"
        scenario, packets, supervision, pairs = _compile_scenario(
            raw,
            generator_identity=generator_identity,
            where=where,
        )
        scenario_rows.append(scenario)
        packet_rows.extend(packets)
        supervision_rows.extend(supervision)
        pair_rows.extend(pairs)

    # All row-level and cross-row meaning stays with the existing contract.
    validate_generation_batch(
        scenario_rows,
        packet_rows,
        supervision_rows,
        pair_rows,
        allowed_source_ids={SOURCE_ID},
        repo_root=repo_root,
    )
    return CompiledPlan064Batch(
        batch_id=batch_id,
        scenarios=tuple(scenario_rows),
        packets=tuple(packet_rows),
        supervision=tuple(supervision_rows),
        pairs=tuple(pair_rows),
    )


def load_plan064_batch(
    path: Path | str,
    *,
    namespace: Path | str = PLAN064_NAMESPACE,
) -> dict[str, Any]:
    """Load one secure raw authoring object from the Plan 064 namespace."""

    root = _resolve_namespace(namespace)
    source = _resolve_plan064_input_file(
        path,
        namespace=root,
        where="Plan 064 raw batch input",
    )
    try:
        text = source.read_text(encoding="utf-8")
        value = json.loads(text, parse_constant=_reject_nonfinite)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"cannot load Plan 064 batch input {source}: {exc}")
    return _object(value, f"Plan 064 batch input {source}")


def create_plan064_review_binding(
    batch_dir: Path | str,
    review_dir: Path | str,
    *,
    namespace: Path | str = PLAN064_NAMESPACE,
    repo_root: Path | str = REPO_ROOT,
) -> dict[str, Any]:
    """Create one non-overwritable binding for the rows actually reviewed."""

    root = _resolve_namespace(namespace)
    batch = _resolve_plan064_input_dir(
        batch_dir,
        namespace=root,
        where="Plan 064 review binding batch directory",
    )
    review = _resolve_plan064_input_dir(
        review_dir,
        namespace=root,
        where="Plan 064 review binding review directory",
    )
    batch_rows = _load_compiled_rows(batch)
    validate_generation_batch(
        batch_rows.scenarios,
        batch_rows.packets,
        batch_rows.supervision,
        batch_rows.pairs,
        allowed_source_ids={SOURCE_ID},
        repo_root=repo_root,
    )
    candidate_reviews, pair_reviews = _load_and_validate_reviews(
        review,
        batch_rows,
        where="Plan 064 review binding",
    )
    binding = _build_review_binding(
        batch_rows,
        candidate_reviews,
        pair_reviews,
    )
    _secure_create(review / REVIEW_BINDING_FILE, _json_bytes(binding))
    return binding


def write_compiled_plan064_batch(
    output_dir: Path | str,
    compiled: CompiledPlan064Batch,
    *,
    namespace: Path | str = PLAN064_NAMESPACE,
) -> None:
    """Create one new output directory and its four non-overwritable JSONL files."""

    root = _resolve_namespace(namespace)

    requested = Path(output_dir)
    if requested.is_symlink() or requested.exists():
        _fail(f"Plan 064 output must be a new path: {requested}")
    if requested.name in {"", ".", ".."}:
        _fail("Plan 064 output must name a child directory")
    try:
        parent = requested.parent.resolve(strict=True)
    except OSError as exc:
        _fail(f"Plan 064 output parent does not exist: {requested.parent}: {exc}")
    if requested.parent.absolute() != parent:
        _fail(f"Plan 064 output parent must not traverse symlinks: {requested.parent}")
    if root != parent and root not in parent.parents:
        _fail(f"Plan 064 output is outside the ignored namespace: {requested}")
    if not parent.is_dir() or parent.is_symlink():
        _fail(f"Plan 064 output parent is unsafe: {parent}")
    _require_mode(parent, 0o700, "Plan 064 output parent")

    output = parent / requested.name
    try:
        os.mkdir(output, mode=0o700)
        output.chmod(0o700)
    except OSError as exc:
        _fail(f"cannot create Plan 064 output directory {output}: {exc}")
    _require_mode(output, 0o700, "Plan 064 output directory")

    rows_by_filename = compiled.rows_by_filename()
    if tuple(rows_by_filename) != _OUTPUT_FILES:
        _fail("internal Plan 064 output registry drifted")
    for filename, rows in rows_by_filename.items():
        _secure_create(output / filename, _jsonl_bytes(rows))


def aggregate_compiled_plan064_batches(
    batch_dirs: Sequence[Path | str],
    *,
    namespace: Path | str = PLAN064_NAMESPACE,
    repo_root: Path | str = REPO_ROOT,
) -> CompiledPlan064Batch:
    """Safely load and combine explicit compiled batch directories."""

    if not batch_dirs:
        _fail("Plan 064 aggregation requires at least one batch directory")
    root = _resolve_namespace(namespace)
    resolved_dirs: list[Path] = []
    seen_dirs: set[Path] = set()
    for index, batch_dir in enumerate(batch_dirs):
        directory = _resolve_plan064_input_dir(
            batch_dir,
            namespace=root,
            where=f"Plan 064 batch directory[{index}]",
        )
        if directory in seen_dirs:
            _fail(f"duplicate Plan 064 batch directory: {directory}")
        seen_dirs.add(directory)
        resolved_dirs.append(directory)

    scenario_rows: list[dict[str, Any]] = []
    packet_rows: list[dict[str, Any]] = []
    supervision_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    for directory in resolved_dirs:
        batch_rows = _load_compiled_rows(directory)
        scenario_rows.extend(batch_rows.scenarios)
        packet_rows.extend(batch_rows.packets)
        supervision_rows.extend(batch_rows.supervision)
        pair_rows.extend(batch_rows.pairs)

    _reject_duplicate_row_ids(scenario_rows, "scenario_id", "aggregated scenarios")
    _reject_duplicate_row_ids(packet_rows, "candidate_id", "aggregated packets")
    _reject_duplicate_row_ids(
        supervision_rows,
        "candidate_id",
        "aggregated supervision",
    )
    _reject_duplicate_row_ids(pair_rows, "pair_id", "aggregated pairs")
    validate_generation_batch(
        scenario_rows,
        packet_rows,
        supervision_rows,
        pair_rows,
        allowed_source_ids={SOURCE_ID},
        repo_root=repo_root,
    )
    return CompiledPlan064Batch(
        batch_id="p064-batch-aggregate",
        scenarios=tuple(scenario_rows),
        packets=tuple(packet_rows),
        supervision=tuple(supervision_rows),
        pairs=tuple(pair_rows),
    )


def aggregate_plan064_reviews(
    batch_dirs: Sequence[Path | str],
    review_dirs: Sequence[Path | str],
    aggregate_dir: Path | str,
    *,
    namespace: Path | str = PLAN064_NAMESPACE,
    repo_root: Path | str = REPO_ROOT,
) -> tuple[int, int]:
    """Bind each review directory to its ordered batch and attach the union."""

    if not batch_dirs or len(batch_dirs) != len(review_dirs):
        _fail(
            "Plan 064 review aggregation requires one ordered review directory "
            "for every batch directory"
        )
    root = _resolve_namespace(namespace)
    resolved_batches: list[Path] = []
    resolved_reviews: list[Path] = []
    seen_batches: set[Path] = set()
    seen_reviews: set[Path] = set()
    for index, (batch_dir, review_dir) in enumerate(zip(batch_dirs, review_dirs)):
        batch = _resolve_plan064_input_dir(
            batch_dir,
            namespace=root,
            where=f"Plan 064 review binding[{index}].batch_dir",
        )
        review = _resolve_plan064_input_dir(
            review_dir,
            namespace=root,
            where=f"Plan 064 review binding[{index}].review_dir",
        )
        if batch in seen_batches:
            _fail(f"duplicate Plan 064 review batch directory: {batch}")
        if review in seen_reviews:
            _fail(f"duplicate Plan 064 review directory: {review}")
        seen_batches.add(batch)
        seen_reviews.add(review)
        resolved_batches.append(batch)
        resolved_reviews.append(review)

    scenario_rows: list[dict[str, Any]] = []
    packet_rows: list[dict[str, Any]] = []
    supervision_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    candidate_reviews: list[dict[str, Any]] = []
    pair_reviews: list[dict[str, Any]] = []
    source_bindings: list[dict[str, Any]] = []
    for index, (batch_dir, review_dir) in enumerate(
        zip(resolved_batches, resolved_reviews)
    ):
        batch_rows = _load_compiled_rows(batch_dir)
        scenario_rows.extend(batch_rows.scenarios)
        packet_rows.extend(batch_rows.packets)
        supervision_rows.extend(batch_rows.supervision)
        pair_rows.extend(batch_rows.pairs)

        reviewed_candidates, reviewed_pairs = _load_and_validate_reviews(
            review_dir,
            batch_rows,
            where=f"Plan 064 review binding[{index}]",
        )
        source_binding = _load_json_file(review_dir / REVIEW_BINDING_FILE)
        expected_binding = _build_review_binding(
            batch_rows,
            reviewed_candidates,
            reviewed_pairs,
        )
        _validate_review_binding(source_binding)
        if source_binding != expected_binding:
            _fail(
                f"Plan 064 review binding[{index}] does not match current ordered batch/review content"
            )
        source_bindings.append(source_binding)
        candidate_reviews.extend(reviewed_candidates)
        pair_reviews.extend(reviewed_pairs)

    _reject_duplicate_row_ids(scenario_rows, "scenario_id", "review-bound scenarios")
    _reject_duplicate_row_ids(packet_rows, "candidate_id", "review-bound packets")
    _reject_duplicate_row_ids(
        supervision_rows,
        "candidate_id",
        "review-bound supervision",
    )
    _reject_duplicate_row_ids(pair_rows, "pair_id", "review-bound pairs")
    _reject_duplicate_row_ids(
        candidate_reviews,
        "candidate_id",
        "aggregated candidate reviews",
    )
    _reject_duplicate_row_ids(pair_reviews, "pair_id", "aggregated pair reviews")
    validate_generation_batch(
        scenario_rows,
        packet_rows,
        supervision_rows,
        pair_rows,
        allowed_source_ids={SOURCE_ID},
        repo_root=repo_root,
    )

    target = _resolve_plan064_input_dir(
        aggregate_dir,
        namespace=root,
        where="Plan 064 aggregate candidate directory",
    )
    aggregate_rows = _load_compiled_rows(target)
    _require_exact_aggregate_rows(
        aggregate_rows,
        scenarios=scenario_rows,
        packets=packet_rows,
        supervision=supervision_rows,
        pairs=pair_rows,
    )
    candidate_target = target / "candidate-reviews.jsonl"
    pair_target = target / "pair-reviews.jsonl"
    bindings_target = target / AGGREGATE_REVIEW_BINDINGS_FILE
    existing = [
        path
        for path in (candidate_target, pair_target, bindings_target)
        if path.exists() or path.is_symlink()
    ]
    if existing:
        _fail(f"refusing to overwrite Plan 064 review outputs: {existing}")
    aggregate_binding = build_plan064_aggregate_review_bindings(
        source_bindings,
        scenarios=aggregate_rows.scenarios,
        packets=aggregate_rows.packets,
        supervision=aggregate_rows.supervision,
        pairs=aggregate_rows.pairs,
        candidate_reviews=candidate_reviews,
        pair_reviews=pair_reviews,
    )
    _secure_create(candidate_target, _jsonl_bytes(candidate_reviews))
    _secure_create(pair_target, _jsonl_bytes(pair_reviews))
    _secure_create(bindings_target, _json_bytes(aggregate_binding))
    return len(candidate_reviews), len(pair_reviews)


def build_plan064_aggregate_review_bindings(
    source_bindings: Sequence[Mapping[str, Any]],
    *,
    scenarios: Sequence[Mapping[str, Any]],
    packets: Sequence[Mapping[str, Any]],
    supervision: Sequence[Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
    candidate_reviews: Sequence[Mapping[str, Any]],
    pair_reviews: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    aggregate_rows = CompiledPlan064Batch(
        batch_id="p064-batch-aggregate-binding",
        scenarios=tuple(dict(row) for row in scenarios),
        packets=tuple(dict(row) for row in packets),
        supervision=tuple(dict(row) for row in supervision),
        pairs=tuple(dict(row) for row in pairs),
    )
    value = {
        "schema": _AGGREGATE_REVIEW_BINDINGS_SCHEMA,
        "source_bindings": [dict(binding) for binding in source_bindings],
        "aggregate": _build_review_binding(
            aggregate_rows,
            candidate_reviews,
            pair_reviews,
        ),
    }
    validate_plan064_aggregate_review_bindings(
        value,
        scenarios=scenarios,
        packets=packets,
        supervision=supervision,
        pairs=pairs,
        candidate_reviews=candidate_reviews,
        pair_reviews=pair_reviews,
    )
    return value


def validate_plan064_aggregate_review_bindings(
    value: Mapping[str, Any],
    *,
    scenarios: Sequence[Mapping[str, Any]],
    packets: Sequence[Mapping[str, Any]],
    supervision: Sequence[Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
    candidate_reviews: Sequence[Mapping[str, Any]],
    pair_reviews: Sequence[Mapping[str, Any]],
) -> None:
    """Rebind an aggregate candidate directory to its source review evidence."""

    binding = _object(value, "Plan 064 aggregate review bindings")
    _exact_keys(
        binding,
        _AGGREGATE_REVIEW_BINDINGS_KEYS,
        "Plan 064 aggregate review bindings",
    )
    if binding["schema"] != _AGGREGATE_REVIEW_BINDINGS_SCHEMA:
        _fail("Plan 064 aggregate review bindings schema drifted")
    sources = _array(
        binding["source_bindings"],
        "Plan 064 aggregate review bindings.source_bindings",
        allow_empty=False,
    )
    for source in sources:
        _validate_review_binding(
            _object(source, "Plan 064 aggregate source review binding")
        )
    aggregate = _object(
        binding["aggregate"],
        "Plan 064 aggregate review bindings.aggregate",
    )
    _validate_review_binding(aggregate)
    rows = CompiledPlan064Batch(
        batch_id="p064-batch-aggregate-validation",
        scenarios=tuple(dict(row) for row in scenarios),
        packets=tuple(dict(row) for row in packets),
        supervision=tuple(dict(row) for row in supervision),
        pairs=tuple(dict(row) for row in pairs),
    )
    expected = _build_review_binding(rows, candidate_reviews, pair_reviews)
    if aggregate != expected:
        _fail("Plan 064 aggregate review binding does not match current aggregate content")
    source_counts = {
        name: sum(int(source["counts"][name]) for source in sources)
        for name in _REVIEW_BINDING_CONTENT_KEYS
    }
    if source_counts != aggregate["counts"]:
        _fail("Plan 064 aggregate review binding counts do not reconcile to sources")


def _load_and_validate_reviews(
    review_dir: Path,
    batch_rows: CompiledPlan064Batch,
    *,
    where: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidate_reviews = _load_jsonl_file(
        review_dir / "candidate-reviews.jsonl",
        allow_empty=False,
    )
    pair_reviews = _load_jsonl_file(
        review_dir / "pair-reviews.jsonl",
        allow_empty=not batch_rows.pairs,
    )
    for row in candidate_reviews:
        validate_candidate_review(row)
    for row in pair_reviews:
        validate_pair_review(row)
    _require_exact_review_ids(
        candidate_reviews,
        review_key="candidate_id",
        expected_rows=batch_rows.packets,
        expected_key="candidate_id",
        where=f"{where} candidate reviews",
    )
    _require_exact_review_ids(
        pair_reviews,
        review_key="pair_id",
        expected_rows=batch_rows.pairs,
        expected_key="pair_id",
        where=f"{where} pair reviews",
    )
    return candidate_reviews, pair_reviews


def _build_review_binding(
    batch: CompiledPlan064Batch,
    candidate_reviews: Sequence[Mapping[str, Any]],
    pair_reviews: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    rows: dict[str, Sequence[Mapping[str, Any]]] = {
        "scenarios": batch.scenarios,
        "packets": batch.packets,
        "supervision": batch.supervision,
        "pairs": batch.pairs,
        "candidate_reviews": candidate_reviews,
        "pair_reviews": pair_reviews,
    }
    return {
        "schema": _REVIEW_BINDING_SCHEMA,
        "counts": {name: len(rows[name]) for name, _ in _BOUND_ROW_SPECS},
        "semantic_sha256": {
            name: _semantic_rows_sha256(rows[name], id_key)
            for name, id_key in _BOUND_ROW_SPECS
        },
    }


def _validate_review_binding(value: Mapping[str, Any]) -> None:
    _exact_keys(value, _REVIEW_BINDING_KEYS, "Plan 064 review binding")
    if value["schema"] != _REVIEW_BINDING_SCHEMA:
        _fail("Plan 064 review binding schema drifted")
    counts = _object(value["counts"], "Plan 064 review binding.counts")
    digests = _object(
        value["semantic_sha256"],
        "Plan 064 review binding.semantic_sha256",
    )
    _exact_keys(counts, _REVIEW_BINDING_CONTENT_KEYS, "Plan 064 review binding.counts")
    _exact_keys(
        digests,
        _REVIEW_BINDING_CONTENT_KEYS,
        "Plan 064 review binding.semantic_sha256",
    )
    for name in sorted(_REVIEW_BINDING_CONTENT_KEYS):
        count = counts[name]
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            _fail(f"Plan 064 review binding count is invalid: {name}")
        digest = digests[name]
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            _fail(f"Plan 064 review binding digest is invalid: {name}")


def _semantic_rows_sha256(
    rows: Sequence[Mapping[str, Any]], id_key: str
) -> str:
    indexed: list[tuple[str, Mapping[str, Any]]] = []
    seen: set[str] = set()
    for index, row in enumerate(rows):
        identifier = _nonempty_string(
            row.get(id_key),
            f"Plan 064 review binding rows[{index}].{id_key}",
        )
        if identifier in seen:
            _fail(f"Plan 064 review binding contains duplicate {id_key}")
        seen.add(identifier)
        indexed.append((identifier, row))
    ordered = [row for _, row in sorted(indexed, key=lambda item: item[0])]
    return sha256_bytes(canonical_json_bytes(ordered))


def _compile_scenario(
    value: Any,
    *,
    generator_identity: Mapping[str, Any],
    where: str,
) -> tuple[
    dict[str, Any],
    list[dict[str, Any]],
    list[dict[str, Any]],
    list[dict[str, Any]],
]:
    raw = _object(value, where)
    _exact_keys(raw, _SCENARIO_KEYS, where)
    scenario_id = _prefixed_identifier(
        raw["scenario_id"],
        "p064-",
        f"{where}.scenario_id",
    )
    source_group = _prefixed_identifier(
        raw["source_group"],
        "p064-",
        f"{where}.source_group",
    )
    scenario_group = _prefixed_identifier(
        raw["scenario_group"],
        "p064-",
        f"{where}.scenario_group",
    )
    template_group = _prefixed_identifier(
        raw["template_group"],
        "p064-",
        f"{where}.template_group",
    )
    proposed_split = _nonempty_string(raw["proposed_split"], f"{where}.proposed_split")
    if proposed_split not in {"train", "validation", "unseen_test"}:
        _fail(f"{where}.proposed_split must be train, validation, or unseen_test")
    candidates = _array(raw["candidates"], f"{where}.candidates", allow_empty=False)
    pair_specs = _array(raw["pairs"], f"{where}.pairs", allow_empty=True)

    parsed_pairs = [
        _parse_pair(pair, where=f"{where}.pairs[{index}]")
        for index, pair in enumerate(pair_specs)
    ]
    boundary_targets = {
        pair["target_dimension"]
        for pair in parsed_pairs
        if pair["kind"] == "boundary"
    }
    if len(boundary_targets) > 1:
        _fail(f"{where} has more than one Boundary target dimension")
    hard_focus = next(iter(boundary_targets), None)

    scenario_suffix = scenario_id.removeprefix("p064-")
    packet_rows: list[dict[str, Any]] = []
    supervision_rows: list[dict[str, Any]] = []
    suffix_to_candidate_id: dict[str, str] = {}
    for candidate_index, candidate_value in enumerate(candidates):
        candidate_where = f"{where}.candidates[{candidate_index}]"
        candidate = _object(candidate_value, candidate_where)
        _exact_keys(candidate, _CANDIDATE_KEYS, candidate_where)
        suffix = _id_suffix(candidate["id_suffix"], f"{candidate_where}.id_suffix")
        if suffix in suffix_to_candidate_id:
            _fail(f"{where} has duplicate candidate id_suffix: {suffix}")
        candidate_id = f"pc064-{scenario_suffix}-{suffix}"
        suffix_to_candidate_id[suffix] = candidate_id
        summary = _nonempty_string(candidate["summary"], f"{candidate_where}.summary")
        handoff = candidate["handoff"]
        if handoff is not None and not isinstance(handoff, str):
            _fail(f"{candidate_where}.handoff must be a string or null")
        defects = _string_array(
            candidate["defects"],
            f"{candidate_where}.defects",
            allow_empty=True,
        )
        packet_rows.append(
            {
                "schema_version": 1,
                "candidate_id": candidate_id,
                "packet": {
                    "qualification": deepcopy(_QUALIFICATION),
                    "actor_role": raw["actor_role"],
                    "target_kind": (
                        "new_event"
                        if str(raw["publication_class"]).startswith("new_event_")
                        else "existing_event"
                    ),
                    "local_scope": {
                        "title": _object(
                            raw["blueprint"],
                            f"{where}.blueprint",
                        ).get("local_scope_title")
                    },
                    "candidate": {"summary": summary, "handoff": handoff},
                    "continuity": deepcopy(_object(raw["continuity"], f"{where}.continuity")),
                    "evidence_v1": deepcopy(_EVIDENCE_V1),
                },
            }
        )
        supervision_rows.append(
            {
                "schema_version": 1,
                "candidate_id": candidate_id,
                "scenario_id": scenario_id,
                "source_group": source_group,
                "scenario_group": scenario_group,
                "template_group": template_group,
                "proposed_split": proposed_split,
                "binary_label": _nonempty_string(
                    candidate["label"],
                    f"{candidate_where}.label",
                ),
                "publication_class": raw["publication_class"],
                "completion_state": raw["completion_state"],
                "hard_focus": hard_focus,
                "defects": defects,
                "slices": deepcopy(raw["slices"]),
                "actor_role": raw["actor_role"],
                "style": raw["style"],
                "length_bucket": raw["length_bucket"],
                "unicode": raw["unicode"],
                "generator_identity": deepcopy(dict(generator_identity)),
                "reviewer_identity": None,
                "review_status": "pending",
            }
        )

    pair_rows: list[dict[str, Any]] = []
    seen_pair_suffixes: set[str] = set()
    for pair in parsed_pairs:
        suffix = pair["id_suffix"]
        if suffix in seen_pair_suffixes:
            _fail(f"{where} has duplicate pair id_suffix: {suffix}")
        seen_pair_suffixes.add(suffix)
        try:
            preferred = suffix_to_candidate_id[pair["preferred"]]
            dispreferred = suffix_to_candidate_id[pair["dispreferred"]]
        except KeyError as exc:
            _fail(f"{where} pair references unknown candidate id_suffix: {exc.args[0]}")
        pair_rows.append(
            {
                "schema_version": 1,
                "pair_id": f"pc064-pair-{scenario_suffix}-{suffix}",
                "kind": pair["kind"],
                "scenario_id": scenario_id,
                "preferred_candidate_id": preferred,
                "dispreferred_candidate_id": dispreferred,
                "target_dimension": pair["target_dimension"],
                "soft_preference": pair["soft_preference"],
                "review_status": "pending",
            }
        )

    scenario_row = {
        "schema_version": 1,
        "scenario_id": scenario_id,
        "source_id": SOURCE_ID,
        "source_group": source_group,
        "scenario_group": scenario_group,
        "template_group": template_group,
        "publication_class": raw["publication_class"],
        "completion_state": raw["completion_state"],
        "actor_role": raw["actor_role"],
        "style": raw["style"],
        "length_bucket": raw["length_bucket"],
        "unicode": raw["unicode"],
        "slices": deepcopy(raw["slices"]),
        "blueprint": deepcopy(_object(raw["blueprint"], f"{where}.blueprint")),
    }
    return scenario_row, packet_rows, supervision_rows, pair_rows


def _parse_pair(value: Any, *, where: str) -> dict[str, Any]:
    pair = _object(value, where)
    _exact_keys(pair, _PAIR_KEYS, where)
    kind = _nonempty_string(pair["kind"], f"{where}.kind")
    target_dimension = pair["target_dimension"]
    if kind == "boundary":
        target_dimension = _nonempty_string(
            target_dimension,
            f"{where}.target_dimension",
        )
    return {
        "id_suffix": _id_suffix(pair["id_suffix"], f"{where}.id_suffix"),
        "kind": kind,
        "preferred": _id_suffix(pair["preferred"], f"{where}.preferred"),
        "dispreferred": _id_suffix(pair["dispreferred"], f"{where}.dispreferred"),
        "target_dimension": target_dimension,
        "soft_preference": pair["soft_preference"],
    }


def _object(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail(f"{where} must be an object")
    return value


def _array(value: Any, where: str, *, allow_empty: bool) -> list[Any]:
    if not isinstance(value, list) or (not allow_empty and not value):
        _fail(f"{where} must be {'an' if allow_empty else 'a non-empty'} array")
    return value


def _string_array(value: Any, where: str, *, allow_empty: bool) -> list[str]:
    rows = _array(value, where, allow_empty=allow_empty)
    result = [
        _nonempty_string(item, f"{where}[{index}]")
        for index, item in enumerate(rows)
    ]
    if len(result) != len(set(result)):
        _fail(f"{where} must contain unique values")
    return result


def _exact_keys(value: Mapping[str, Any], expected: set[str], where: str) -> None:
    actual = set(value)
    if actual != expected:
        _fail(
            f"{where} keys differ: missing={sorted(expected - actual)}, "
            f"extra={sorted(actual - expected)}"
        )


def _nonempty_string(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _fail(f"{where} must be a non-empty string")
    return value


def _prefixed_identifier(value: Any, prefix: str, where: str) -> str:
    identifier = _nonempty_string(value, where)
    if (
        not identifier.startswith(prefix)
        or len(identifier) > 160
        or any(character.isspace() for character in identifier)
    ):
        _fail(f"{where} must be a bounded whitespace-free {prefix}* identifier")
    return identifier


def _id_suffix(value: Any, where: str) -> str:
    suffix = _nonempty_string(value, where)
    allowed = frozenset("abcdefghijklmnopqrstuvwxyz0123456789-")
    if len(suffix) > 64 or suffix[0] not in allowed - {"-"} or not set(suffix) <= allowed:
        _fail(f"{where} must use lowercase ASCII letters, digits, and hyphens")
    return suffix


def _resolve_namespace(namespace: Path | str) -> Path:
    root = Path(namespace)
    if root.is_symlink() or not root.is_dir():
        _fail(f"Plan 064 namespace is not a regular non-symlink directory: {root}")
    resolved = root.resolve()
    if root.absolute() != resolved:
        _fail(f"Plan 064 namespace must not traverse symlinks: {root}")
    _require_mode(resolved, 0o700, "Plan 064 namespace")
    return resolved


def _resolve_plan064_input_dir(
    path: Path | str,
    *,
    namespace: Path,
    where: str,
) -> Path:
    directory = Path(path)
    if directory.is_symlink() or not directory.is_dir():
        _fail(f"{where} is not a regular non-symlink directory: {directory}")
    resolved = directory.resolve()
    if directory.absolute() != resolved:
        _fail(f"{where} must not traverse symlinks: {directory}")
    if namespace != resolved and namespace not in resolved.parents:
        _fail(f"{where} is outside the Plan 064 namespace: {directory}")
    _require_mode(resolved, 0o700, where)
    return resolved


def _resolve_plan064_input_file(
    path: Path | str,
    *,
    namespace: Path,
    where: str,
) -> Path:
    source = Path(path)
    if source.is_symlink() or not source.is_file():
        _fail(f"{where} is not a regular non-symlink file: {source}")
    try:
        resolved = source.resolve(strict=True)
    except OSError as exc:
        _fail(f"cannot resolve {where} {source}: {exc}")
    if source.absolute() != resolved:
        _fail(f"{where} must not traverse symlinks: {source}")
    if namespace not in resolved.parents:
        _fail(f"{where} is outside the Plan 064 namespace: {source}")
    _resolve_plan064_input_dir(
        resolved.parent,
        namespace=namespace,
        where=f"{where} parent directory",
    )
    _require_mode(resolved, 0o600, where)
    return resolved


def _load_compiled_rows(directory: Path) -> CompiledPlan064Batch:
    return CompiledPlan064Batch(
        batch_id="p064-batch-loaded",
        scenarios=tuple(
            _load_jsonl_file(directory / "scenarios.jsonl", allow_empty=False)
        ),
        packets=tuple(
            _load_jsonl_file(directory / "packets.jsonl", allow_empty=False)
        ),
        supervision=tuple(
            _load_jsonl_file(directory / "supervision.jsonl", allow_empty=False)
        ),
        pairs=tuple(_load_jsonl_file(directory / "pairs.jsonl", allow_empty=True)),
    )


def _load_jsonl_file(path: Path, *, allow_empty: bool) -> list[dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        _fail(f"Plan 064 JSONL input is not a regular non-symlink file: {path}")
    _require_mode(path, 0o600, "Plan 064 JSONL input file")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        _fail(f"cannot read Plan 064 JSONL input {path}: {exc}")
    if not lines and not allow_empty:
        _fail(f"Plan 064 JSONL input must not be empty: {path}")
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            _fail(f"blank line in Plan 064 JSONL input {path}:{line_number}")
        try:
            value = json.loads(line, parse_constant=_reject_nonfinite)
        except json.JSONDecodeError as exc:
            _fail(f"invalid JSON in Plan 064 JSONL input {path}:{line_number}: {exc}")
        rows.append(_object(value, f"Plan 064 JSONL input {path}:{line_number}"))
    return rows


def _load_json_file(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        _fail(f"Plan 064 JSON input is not a regular non-symlink file: {path}")
    _require_mode(path, 0o600, "Plan 064 JSON input file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"), parse_constant=_reject_nonfinite)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        _fail(f"cannot read Plan 064 JSON input {path}: {exc}")
    return _object(value, f"Plan 064 JSON input {path}")


def _reject_duplicate_row_ids(
    rows: Sequence[Mapping[str, Any]],
    key: str,
    where: str,
) -> None:
    seen: set[str] = set()
    for index, row in enumerate(rows):
        identifier = _nonempty_string(row.get(key), f"{where}[{index}].{key}")
        if identifier in seen:
            _fail(f"duplicate {key} in {where}: {identifier}")
        seen.add(identifier)


def _require_exact_review_ids(
    review_rows: Sequence[Mapping[str, Any]],
    *,
    review_key: str,
    expected_rows: Sequence[Mapping[str, Any]],
    expected_key: str,
    where: str,
) -> None:
    review_ids = [
        _nonempty_string(row.get(review_key), f"{where}[{index}].{review_key}")
        for index, row in enumerate(review_rows)
    ]
    expected_ids = [
        _nonempty_string(
            row.get(expected_key),
            f"{where}.expected[{index}].{expected_key}",
        )
        for index, row in enumerate(expected_rows)
    ]
    if len(review_ids) != len(set(review_ids)):
        _fail(f"{where} contains duplicate {review_key}")
    if set(review_ids) != set(expected_ids):
        _fail(
            f"{where} IDs differ from its ordered batch: "
            f"missing={sorted(set(expected_ids) - set(review_ids))}, "
            f"extra={sorted(set(review_ids) - set(expected_ids))}"
        )


def _require_exact_aggregate_rows(
    aggregate: CompiledPlan064Batch,
    *,
    scenarios: Sequence[Mapping[str, Any]],
    packets: Sequence[Mapping[str, Any]],
    supervision: Sequence[Mapping[str, Any]],
    pairs: Sequence[Mapping[str, Any]],
) -> None:
    for name, actual, expected in (
        ("scenarios", aggregate.scenarios, scenarios),
        ("packets", aggregate.packets, packets),
        ("supervision", aggregate.supervision, supervision),
        ("pairs", aggregate.pairs, pairs),
    ):
        if list(actual) != list(expected):
            _fail(
                "Plan 064 aggregate candidate directory does not exactly match "
                f"the ordered review-bound batch {name}"
            )


def _jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join(
        json.dumps(
            row,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
        for row in rows
    )


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return canonical_json_bytes(value)


def _secure_create(path: Path, content: bytes) -> None:
    if path.exists() or path.is_symlink():
        _fail(f"refusing to overwrite Plan 064 output: {path}")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
        path.chmod(0o600)
    except OSError as exc:
        _fail(f"cannot create Plan 064 output {path}: {exc}")
    _require_mode(path, 0o600, "Plan 064 output file")


def _require_mode(path: Path, expected: int, where: str) -> None:
    try:
        actual = stat.S_IMODE(path.stat(follow_symlinks=False).st_mode)
    except OSError as exc:
        _fail(f"cannot inspect {where} {path}: {exc}")
    if actual != expected:
        _fail(f"{where} must have mode {expected:o}, got {actual:o}: {path}")


def _reject_nonfinite(value: str) -> NoReturn:
    _fail(f"non-finite JSON number is forbidden: {value}")


def _fail(message: str) -> NoReturn:
    raise TrainingDataError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compile one structured Plan 064 batch into pending v1 JSONL rows."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    compiled = compile_plan064_batch(load_plan064_batch(args.input))
    write_compiled_plan064_batch(args.output_dir, compiled)
    summary = {
        "batch_id": compiled.batch_id,
        "scenarios": len(compiled.scenarios),
        "candidates": len(compiled.packets),
        "pairs": len(compiled.pairs),
        "output_dir": str(Path(args.output_dir).resolve()),
    }
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0
