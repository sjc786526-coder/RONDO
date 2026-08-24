"""Plan 064 full-release materialization with an explicit prefreeze gate.

This is a thin orchestration layer over the Plan 059 row contracts.  It keeps
the immutable v7 rows, terminalizes only directly reviewed Plan 064 delta rows,
and runs the same complete mechanical chain for prefreeze and freeze.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from typing import Any, Literal

from ..identity import canonical_json_bytes, sha256_bytes, sha256_file
from ..render import build_messages
from .consumer import (
    DatasetConsumer,
    build_memberships,
    build_train_only_smoke_bundle,
    validate_train_only_smoke_bundle,
)
from .contract import (
    TrainingDataError,
    validate_candidate_review,
    validate_dataset,
    validate_generation_batch,
    validate_pair_review,
)
from .dedup import (
    find_near_duplicate_edges,
    find_reference_matches,
    reject_exact_duplicates,
)
from .freeze import build_freeze_manifest, verify_freeze_manifest
from .grouping import (
    build_group_components,
    coverage_failures,
    deterministic_grouped_stratified_split,
    reject_perfect_shortcuts,
    shortcut_contingencies,
    validate_group_closure,
    validate_new_to_base_component_closure,
)
from .input_identity import load_plan054_training_input
from .lineage import validate_v7_lineage
from .plan064_batch import (
    AGGREGATE_REVIEW_BINDINGS_FILE,
    validate_plan064_aggregate_review_bindings,
)
from .quality_audit import (
    Plan064QualityAuditStrata,
    build_plan064_quality_audit_strata,
    plan064_quality_audit_seed,
    validate_plan064_quality_audit_sample,
)
from .review_policy import validate_plan064_review_dispositions
from .shortcuts import (
    conditioned_model_visible_text_shortcut_findings,
    model_visible_candidate_length_shortcut_findings,
    model_visible_text_shortcut_findings,
    reject_model_visible_candidate_length_shortcuts,
    reject_model_visible_text_shortcuts,
)
from .token_census import census_packets


Phase = Literal["prefreeze", "freeze"]
_ROW_FILES = {
    "scenarios": "scenarios.jsonl",
    "packets": "packets.jsonl",
    "supervision": "supervision.jsonl",
    "pairs": "pairs.jsonl",
}
_DELTA_REVIEW_FILES = {
    "candidate_reviews": "candidate-reviews.jsonl",
    "pair_reviews": "pair-reviews.jsonl",
}
_GENERATOR_PROMPT_CONTRACT = (
    "eval/templates/publication-critic/training-data-generator-prompt-v8.md"
)
_REVIEWER_PROMPT_CONTRACT = (
    "eval/templates/publication-critic/training-data-reviewer-prompt-v2.md"
)
_QUALITY_AUDIT_FILE = "quality-audit.json"
_QUALITY_AUDIT_KEYS = {
    "schema",
    "universe",
    "sampling_seed",
    "strata",
    "sampled_candidate_ids",
    "sampled_pair_ids",
    "summary_counts",
    "findings",
    "unresolved_systemic_findings",
}
_QUALITY_AUDIT_UNIVERSE_KEYS = {
    "candidate_ids_sha256",
    "final_split_sha256",
    "pair_ids_sha256",
    "reviewed_content_sha256",
}
_QUALITY_AUDIT_SUMMARY_KEYS = {
    "complete_candidate_count",
    "complete_pair_count",
    "sampled_candidate_count",
    "sampled_pair_count",
    "stratum_count",
    "finding_count",
}
_QUALITY_AUDIT_FINDING_KEYS = {
    "status",
    "affected_candidate_ids",
    "affected_pair_ids",
}
_TERMINAL_QUALITY_FINDING_STATUSES = frozenset(
    {"resolved", "false_positive"}
)


def materialize_plan064_release(
    *,
    phase: Phase,
    base_dir: Path,
    delta_dir: Path,
    output_dir: Path,
    design_lock_path: Path,
    reference_packets_path: Path,
    tokenizer: Any,
    generation_commit: str,
    contracts: Mapping[str, str],
    repo_root: Path,
    ignored_namespace: Path,
    formal_release_dir: Path,
    approved_prefreeze_identity: str | None = None,
) -> dict[str, Any]:
    """Materialize and validate the complete v7 plus Plan 064 logical release.

    Prefreeze writes only an ignored checkpoint.  Freeze requires the exact
    approved prefreeze universe identity and is the only phase that writes a
    formal manifest or data card.
    """

    _validate_phase_and_paths(
        phase,
        output_dir=output_dir,
        ignored_namespace=ignored_namespace,
        formal_release_dir=formal_release_dir,
        approved_prefreeze_identity=approved_prefreeze_identity,
    )
    _validate_secure_ignored_directory(delta_dir, ignored_namespace)
    _full_git_sha(generation_commit)
    design_lock = _load_json(design_lock_path)
    _validate_design_lock(design_lock)
    dataset_revision = str(design_lock["dataset_revision"])
    verified_input = load_plan054_training_input(repo_root)
    _validate_plan054_design_identity(design_lock, verified_input.input_identity)

    base_manifest = _load_json(base_dir / "manifest.json")
    _validate_base_release(
        base_dir,
        base_manifest,
        design_lock,
        expected_input_identity=verified_input.input_identity,
    )
    base = {
        key: _load_jsonl(base_dir / relative)
        for key, relative in _ROW_FILES.items()
    }
    base_membership = _load_json(base_dir / "membership.json")
    base_reports = _load_json(base_dir / "reports.json")
    delta = {
        key: _load_jsonl(delta_dir / relative, secure=True)
        for key, relative in _ROW_FILES.items()
    }
    reviews = {
        key: _load_jsonl(delta_dir / relative, secure=True)
        for key, relative in _DELTA_REVIEW_FILES.items()
    }
    quality_audit = _load_json(delta_dir / _QUALITY_AUDIT_FILE, secure=True)
    aggregate_review_bindings = _load_json(
        delta_dir / AGGREGATE_REVIEW_BINDINGS_FILE,
        secure=True,
    )
    aggregate_review_bindings_sha256 = sha256_bytes(
        canonical_json_bytes(aggregate_review_bindings)
    )
    _validate_delta_teacher_prompt_hashes(
        delta["supervision"],
        reviews["candidate_reviews"],
        reviews["pair_reviews"],
        contracts=contracts,
    )

    delta_sources = _source_ids(design_lock, membership="primary")
    validate_generation_batch(
        delta["scenarios"],
        delta["packets"],
        delta["supervision"],
        delta["pairs"],
        allowed_source_ids=delta_sources,
        repo_root=repo_root,
    )
    terminal_supervision, terminal_pairs = _terminalize_delta(
        delta["supervision"],
        delta["pairs"],
        reviews["candidate_reviews"],
        reviews["pair_reviews"],
    )
    validate_plan064_aggregate_review_bindings(
        aggregate_review_bindings,
        scenarios=delta["scenarios"],
        packets=delta["packets"],
        supervision=delta["supervision"],
        pairs=delta["pairs"],
        candidate_reviews=reviews["candidate_reviews"],
        pair_reviews=reviews["pair_reviews"],
    )
    combined = {
        "scenarios": [*base["scenarios"], *delta["scenarios"]],
        "packets": [*base["packets"], *delta["packets"]],
        "supervision": [*base["supervision"], *terminal_supervision],
        "pairs": [*base["pairs"], *terminal_pairs],
    }
    scale = design_lock["bounded_scale"]
    candidate_count = len(combined["supervision"])
    if not int(scale["logical_release_floor"]) <= candidate_count <= int(
        scale["hard_cap"]
    ):
        raise TrainingDataError(
            "Plan 064 logical release candidate count is outside the frozen bounded scale"
        )
    base_candidate_ids = {str(row["candidate_id"]) for row in base["supervision"]}
    base_pair_ids = {str(row["pair_id"]) for row in base["pairs"]}
    candidate_dispositions = [
        {
            "schema_version": 1,
            "candidate_id": row["candidate_id"],
            "method": (
                "inherited_v7"
                if row["candidate_id"] in base_candidate_ids
                else "direct_accept"
            ),
        }
        for row in combined["supervision"]
    ]
    pair_dispositions = [
        {
            "schema_version": 1,
            "pair_id": row["pair_id"],
            "method": (
                "inherited_v7"
                if row["pair_id"] in base_pair_ids
                else "direct_accept"
            ),
        }
        for row in combined["pairs"]
    ]
    packet_hashes = reject_exact_duplicates(combined["packets"])
    dedup_contract = design_lock["dedup_contract"]
    near_edges = find_near_duplicate_edges(
        combined["packets"],
        threshold=float(dedup_contract["near_duplicate_threshold"]),
    )
    reference_rows = _load_jsonl(reference_packets_path)
    reference_packets = {
        str(row["sample_id"]): row["packet"] for row in reference_rows
    }
    reference_matches = find_reference_matches(
        combined["packets"],
        reference_packets,
        threshold=float(dedup_contract["plan054_reference_threshold"]),
    )
    if reference_matches:
        raise TrainingDataError(
            "Plan 064 release contains candidates too close to the Plan 054 cohort"
        )

    authored_assignments = _authored_assignments(combined["supervision"])
    components = build_group_components(
        combined["supervision"],
        combined["pairs"],
        near_duplicate_edges=near_edges,
    )
    base_components = base_reports.get("group_components")
    if not isinstance(base_components, Mapping):
        raise TrainingDataError("Plan 064 v7 group component evidence is missing")
    validate_new_to_base_component_closure(components, base_components)
    fixed_v7_assignments = {
        str(row["candidate_id"]): str(row["proposed_split"])
        for row in base["supervision"]
    }
    assignments = deterministic_grouped_stratified_split(
        components,
        combined["supervision"],
        combined["pairs"],
        design_lock,
        fixed_assignments=fixed_v7_assignments,
    )
    final_supervision = [copy.deepcopy(dict(row)) for row in combined["supervision"]]
    for row in final_supervision:
        row["proposed_split"] = assignments[str(row["candidate_id"])]
    combined = {**combined, "supervision": final_supervision}
    validate_group_closure(components, assignments)
    lineage = validate_v7_lineage(
        v7_scenario_rows=base["scenarios"],
        v7_packet_rows=base["packets"],
        v7_supervision_rows=base["supervision"],
        v7_pair_rows=base["pairs"],
        v7_membership=base_membership,
        combined_scenario_rows=combined["scenarios"],
        combined_packet_rows=combined["packets"],
        combined_supervision_rows=combined["supervision"],
        combined_pair_rows=combined["pairs"],
    )
    audit_strata = build_plan064_quality_audit_strata(
        combined=combined,
        assignments=assignments,
        base_candidate_ids=base_candidate_ids,
        base_pair_ids=base_pair_ids,
        near_duplicate_edges=near_edges,
        design_lock=design_lock,
    )
    quality_audit_report = _validate_quality_audit(
        quality_audit,
        combined=combined,
        candidate_ids={
            str(row["candidate_id"]) for row in combined["supervision"]
        },
        pair_ids={str(row["pair_id"]) for row in combined["pairs"]},
        assignments=assignments,
        pairs=combined["pairs"],
        audit_strata=audit_strata,
        expected_sampling_seed=plan064_quality_audit_seed(design_lock),
    )
    quality_audit_sha256 = sha256_bytes(canonical_json_bytes(quality_audit))
    validate_plan064_review_dispositions(
        combined["supervision"],
        combined["pairs"],
        reviews["candidate_reviews"],
        reviews["pair_reviews"],
        candidate_dispositions,
        pair_dispositions,
        inherited_v7_candidate_ids=base_candidate_ids,
        inherited_v7_pair_ids=base_pair_ids,
    )
    failures = coverage_failures(
        assignments,
        combined["supervision"],
        combined["pairs"],
        design_lock,
    )
    if failures:
        raise TrainingDataError(f"Plan 064 coverage minimums failed: {failures}")
    new_candidate_ids = set(assignments) - base_candidate_ids
    split_assignment_summary = {
        "authored_new_changed_count": sum(
            authored_assignments[candidate_id] != assignments[candidate_id]
            for candidate_id in new_candidate_ids
        ),
        "final_split_counts": dict(
            sorted(Counter(assignments.values()).items())
        ),
    }

    census_rows_tuple, token_summary = census_packets(
        combined["packets"],
        tokenizer,
        verified_input.rubric,
        repo_root=repo_root,
    )
    census_rows = list(census_rows_tuple)
    omissions = {
        str(row["candidate_id"]): int(row["dropped_oldest_publications"])
        for row in census_rows
    }

    shortcut_contract = design_lock["shortcut_checks"]
    visible_support = max(
        int(shortcut_contract["visible_text_minimum_candidate_support_floor"]),
        math.ceil(
            len(combined["supervision"])
            * float(shortcut_contract["visible_text_minimum_candidate_support_fraction"])
        ),
    )
    contingencies = shortcut_contingencies(
        combined["supervision"],
        shortcut_contract["dimensions"],
    )
    reject_perfect_shortcuts(
        contingencies,
        minimum_support=int(shortcut_contract["metadata_minimum_support"]),
    )
    visible_findings = model_visible_text_shortcut_findings(
        combined["packets"],
        combined["supervision"],
        minimum_candidate_support=visible_support,
        minimum_split_support=int(
            shortcut_contract["visible_text_minimum_split_support"]
        ),
        dropped_oldest_publications=omissions,
    )
    reject_model_visible_text_shortcuts(visible_findings)
    conditioned_visible: list[dict[str, Any]] = []
    for dimension in shortcut_contract.get("conditioned_text_dimensions", []):
        population_counts = Counter(
            "<null>" if row.get(dimension) is None else str(row.get(dimension))
            for row in combined["supervision"]
        )
        conditioned_support = max(
            int(
                shortcut_contract[
                    "conditioned_text_minimum_candidate_support_floor"
                ]
            ),
            math.ceil(
                max(population_counts.values(), default=0)
                * float(
                    shortcut_contract[
                        "conditioned_text_minimum_candidate_support_fraction"
                    ]
                )
            ),
        )
        conditioned_visible.extend(
            conditioned_model_visible_text_shortcut_findings(
                combined["packets"],
                combined["supervision"],
                condition_field=str(dimension),
                minimum_candidate_support=conditioned_support,
                minimum_split_support=int(
                    shortcut_contract["visible_text_minimum_split_support"]
                ),
                dropped_oldest_publications=omissions,
            )
        )
    if conditioned_visible:
        raise TrainingDataError(
            "hard-focus-conditioned model-visible text shortcuts detected"
        )

    length_bucket_check = _validate_exact_length_buckets(
        combined["supervision"],
        census_rows,
        design_lock["length_bucket_contract"],
    )
    length_findings = model_visible_candidate_length_shortcut_findings(
        census_rows,
        combined["supervision"],
        minimum_candidate_support=int(
            shortcut_contract["candidate_length_minimum_support"]
        ),
        minimum_split_support=int(
            shortcut_contract["candidate_length_minimum_split_support"]
        ),
    )
    reject_model_visible_candidate_length_shortcuts(length_findings)

    all_sources = _source_ids(design_lock, membership=None)
    validate_dataset(
        combined["packets"],
        combined["supervision"],
        combined["pairs"],
        scenario_rows=combined["scenarios"],
        candidate_reviews=reviews["candidate_reviews"],
        pair_reviews=reviews["pair_reviews"],
        dropped_oldest_publications=omissions,
        repo_root=repo_root,
        final=True,
        require_review_records=False,
        allowed_source_ids=all_sources,
    )

    membership = build_memberships(
        combined["supervision"],
        combined["pairs"],
        dataset_revision=dataset_revision,
    )
    consumer_report = _consumer_smoke(
        combined["packets"],
        combined["supervision"],
        combined["pairs"],
        membership,
        verified_input.rubric,
        repo_root,
        omissions,
        tokenizer,
    )
    split_index = _split_index(combined["supervision"], dataset_revision)
    statistics = _statistics(
        combined["supervision"], combined["pairs"], token_summary
    )
    smoke_source_bytes = {
        "packets.jsonl": _jsonl_bytes(combined["packets"]),
        "supervision.jsonl": _jsonl_bytes(combined["supervision"]),
        "pairs.jsonl": _jsonl_bytes(combined["pairs"]),
        "membership.json": _json_bytes(membership),
    }
    source_hashes = {
        name: sha256_bytes(content)
        for name, content in smoke_source_bytes.items()
    }
    bundle = build_train_only_smoke_bundle(
        combined["packets"],
        combined["supervision"],
        combined["pairs"],
        dataset_revision=dataset_revision,
        source_hashes=source_hashes,
    )
    if bundle.get("source_hashes") != source_hashes:
        raise TrainingDataError("train-only smoke bundle source hashes drifted")
    validate_train_only_smoke_bundle(bundle, repo_root=repo_root)
    reports = {
        "schema": "rondo-publication-critic-plan064-release-report-v1",
        "phase": phase,
        "coverage_failures": [],
        "exact_packet_sha256": dict(sorted(packet_hashes.items())),
        "near_duplicate_edges": [
            {
                "left_candidate_id": edge.left_candidate_id,
                "right_candidate_id": edge.right_candidate_id,
                "similarity": edge.similarity,
            }
            for edge in near_edges
        ],
        "plan054_reference_matches": list(reference_matches),
        "group_components": dict(sorted(components.items())),
        "split_assignments": dict(sorted(assignments.items())),
        "split_assignment_summary": split_assignment_summary,
        "shortcut_contingencies": contingencies,
        "model_visible_text_shortcuts": list(visible_findings),
        "hard_focus_conditioned_text_shortcuts": conditioned_visible,
        "model_visible_candidate_length_shortcuts": list(length_findings),
        "token_summary": token_summary,
        "length_bucket_check": length_bucket_check,
        "review": {
            "new_candidate_decisions": dict(
                sorted(Counter(row["decision"] for row in reviews["candidate_reviews"]).items())
            ),
            "new_pair_decisions": dict(
                sorted(Counter(row["decision"] for row in reviews["pair_reviews"]).items())
            ),
        },
        "quality_audit": quality_audit_report,
        "consumer": consumer_report,
    }
    identity = _prefreeze_identity(
        design_lock_path=design_lock_path,
        plan054_input_identity=verified_input.input_identity,
        base_manifest_content_sha256=str(base_manifest["content_sha256"]),
        combined=combined,
        candidate_reviews=reviews["candidate_reviews"],
        pair_reviews=reviews["pair_reviews"],
        candidate_dispositions=candidate_dispositions,
        pair_dispositions=pair_dispositions,
        lineage=lineage,
        quality_audit_sha256=quality_audit_sha256,
        aggregate_review_bindings_sha256=aggregate_review_bindings_sha256,
        mechanical_artifacts_sha256=sha256_bytes(
            canonical_json_bytes(
                {
                    "reports": {
                        key: value
                        for key, value in reports.items()
                        if key != "phase"
                    },
                    "token_census": _rows_semantic_sha256(
                        census_rows,
                        "candidate_id",
                    ),
                    "membership": membership,
                    "split_index": split_index,
                    "train_only_smoke_bundle": bundle,
                }
            )
        ),
    )
    if phase == "freeze" and identity["universe_sha256"] != approved_prefreeze_identity:
        raise TrainingDataError(
            "freeze approval does not match the recomputed prefreeze universe identity"
        )

    output, ignored = _prepare_output(
        output_dir,
        ignored=(phase == "prefreeze"),
    )
    file_bytes = {
        "scenarios.jsonl": _jsonl_bytes(combined["scenarios"]),
        "packets.jsonl": _jsonl_bytes(combined["packets"]),
        "supervision.jsonl": _jsonl_bytes(combined["supervision"]),
        "pairs.jsonl": _jsonl_bytes(combined["pairs"]),
        "candidate-reviews.jsonl": _jsonl_bytes(reviews["candidate_reviews"]),
        "pair-reviews.jsonl": _jsonl_bytes(reviews["pair_reviews"]),
        "candidate-dispositions.jsonl": _jsonl_bytes(candidate_dispositions),
        "pair-dispositions.jsonl": _jsonl_bytes(pair_dispositions),
        "lineage.json": _json_bytes(lineage),
        _QUALITY_AUDIT_FILE: _json_bytes(quality_audit),
        AGGREGATE_REVIEW_BINDINGS_FILE: _json_bytes(aggregate_review_bindings),
        "split-index.json": _json_bytes(split_index),
        "token-census.jsonl": _jsonl_bytes(census_rows),
        "membership.json": _json_bytes(membership),
        "reports.json": _json_bytes(reports),
        "prefreeze-identity.json": _json_bytes(identity),
    }
    file_bytes["train-only-smoke-bundle.json"] = _json_bytes(bundle)
    for name, content in file_bytes.items():
        _write_new(output / name, content, ignored=ignored)

    result: dict[str, Any] = {
        "schema": "rondo-publication-critic-plan064-release-result-v1",
        "phase": phase,
        "status": (
            "PREFREEZE_WAITING_APPROVAL" if phase == "prefreeze" else "FROZEN"
        ),
        "output_dir": str(output),
        "prefreeze_universe_sha256": identity["universe_sha256"],
        "statistics": statistics,
        "consumer": consumer_report,
    }
    if phase == "freeze":
        _write_new(
            output / "DATA_CARD.md",
            _data_card(dataset_revision, statistics, identity).encode("utf-8"),
            ignored=False,
        )
        manifest_paths = sorted(path.name for path in output.iterdir())
        manifest = build_freeze_manifest(
            output,
            manifest_paths,
            dataset_revision=dataset_revision,
            input_identity=verified_input.input_identity,
            design_lock_sha256=sha256_file(design_lock_path),
            generation_commit=generation_commit,
            contracts=contracts,
            statistics=statistics,
        )
        _write_new(output / "manifest.json", _json_bytes(manifest), ignored=False)
        verify_freeze_manifest(
            output,
            manifest,
            expected_input_identity=verified_input.input_identity,
        )
        DatasetConsumer.from_frozen_directory(
            output,
            repo_root=repo_root,
        ).model_inputs("C3")
        result["manifest_content_sha256"] = manifest["content_sha256"]
    return result


def _terminalize_delta(
    supervision_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    candidate_reviews: Sequence[Mapping[str, Any]],
    pair_reviews: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    for review in candidate_reviews:
        validate_candidate_review(review)
    for review in pair_reviews:
        validate_pair_review(review)
    candidate_by_id = _index(candidate_reviews, "candidate_id", "candidate reviews")
    pair_by_id = _index(pair_reviews, "pair_id", "pair reviews")
    if set(candidate_by_id) != {str(row["candidate_id"]) for row in supervision_rows}:
        raise TrainingDataError("Plan 064 candidate review IDs must exactly match delta candidates")
    if set(pair_by_id) != {str(row["pair_id"]) for row in pair_rows}:
        raise TrainingDataError("Plan 064 pair review IDs must exactly match delta pairs")
    terminal_supervision: list[dict[str, Any]] = []
    for raw in supervision_rows:
        row = copy.deepcopy(dict(raw))
        review = candidate_by_id[str(row["candidate_id"])]
        if review.get("decision") != "accept" or review.get("independent_label") != row.get("binary_label"):
            raise TrainingDataError(f"delta candidate lacks direct accepting review: {row['candidate_id']}")
        row["reviewer_identity"] = review["reviewer_identity"]
        row["review_status"] = "accept"
        terminal_supervision.append(row)
    terminal_pairs: list[dict[str, Any]] = []
    for raw in pair_rows:
        row = copy.deepcopy(dict(raw))
        review = pair_by_id[str(row["pair_id"])]
        if review.get("decision") != "accept":
            raise TrainingDataError(f"delta pair lacks direct accepting review: {row['pair_id']}")
        row["review_status"] = "accept"
        terminal_pairs.append(row)
    return terminal_supervision, terminal_pairs


def _validate_delta_teacher_prompt_hashes(
    supervision_rows: Sequence[Mapping[str, Any]],
    candidate_reviews: Sequence[Mapping[str, Any]],
    pair_reviews: Sequence[Mapping[str, Any]],
    *,
    contracts: Mapping[str, str],
) -> None:
    expected_generator = _sha256(
        contracts.get(_GENERATOR_PROMPT_CONTRACT),
        "Plan 064 generator prompt contract hash",
    )
    expected_reviewer = _sha256(
        contracts.get(_REVIEWER_PROMPT_CONTRACT),
        "Plan 064 reviewer prompt contract hash",
    )
    for row in supervision_rows:
        candidate_id = row.get("candidate_id")
        identity = row.get("generator_identity")
        if (
            not isinstance(identity, Mapping)
            or identity.get("prompt_sha256") != expected_generator
        ):
            raise TrainingDataError(
                f"delta candidate generator prompt identity drifted: {candidate_id}"
            )
    for where, rows in (
        ("candidate", candidate_reviews),
        ("pair", pair_reviews),
    ):
        for row in rows:
            identity = row.get("reviewer_identity")
            if (
                not isinstance(identity, Mapping)
                or identity.get("prompt_sha256") != expected_reviewer
            ):
                raise TrainingDataError(
                    f"delta {where} reviewer prompt identity drifted: "
                    f"{row.get(f'{where}_id')}"
                )


def _consumer_smoke(
    packet_rows: Sequence[Mapping[str, Any]],
    supervision_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    membership: Mapping[str, Any],
    rubric: str,
    repo_root: Path,
    dropped_oldest_publications: Mapping[str, int],
    tokenizer: Any,
) -> dict[str, Any]:
    consumer = DatasetConsumer.from_rows(
        packet_rows,
        supervision_rows,
        pair_rows,
        membership,
        repo_root=repo_root,
        dropped_oldest_publications=dropped_oldest_publications,
    )
    c1 = consumer.stage("C1")
    c2 = consumer.stage("C2")
    c3 = consumer.stage("C3")
    model_inputs = consumer.model_inputs("C3")
    if c1["pairs"] or any(row["kind"] != "boundary" for row in c2["pairs"]):
        raise TrainingDataError("C1/C2 cumulative membership is invalid")
    try:
        consumer.evaluation_split("unseen_test")
    except TrainingDataError:
        pass
    else:
        raise TrainingDataError("default consumer unexpectedly exposes holdout")
    evaluation = DatasetConsumer.from_rows(
        packet_rows,
        supervision_rows,
        pair_rows,
        membership,
        repo_root=repo_root,
        allow_evaluation=True,
        dropped_oldest_publications=dropped_oldest_publications,
    )
    unseen_count = sum(row["proposed_split"] == "unseen_test" for row in supervision_rows)
    if len(evaluation.evaluation_split("unseen_test")) != unseen_count:
        raise TrainingDataError("evaluation consumer cannot reproduce unseen_test")
    packet_index = {str(row["candidate_id"]): row for row in packet_rows}
    model_inputs_by_candidate = {
        str(row["candidate_id"]): row["messages"] for row in model_inputs
    }
    for candidate_id, messages in model_inputs_by_candidate.items():
        fitted = tokenizer.fit_packet(packet_index[candidate_id]["packet"], rubric)
        if tuple(messages) != tuple(fitted.plan.messages):
            raise TrainingDataError(
                f"consumer model input differs from exact fitted input: {candidate_id}"
            )
        if [message["role"] for message in messages] != ["user", "assistant"]:
            raise TrainingDataError(f"invalid model messages: {candidate_id}")
    return {
        "c1_binary": len(c1["binary"]),
        "c1_pairs": len(c1["pairs"]),
        "c2_pairs": len(c2["pairs"]),
        "c3_pairs": len(c3["pairs"]),
        "default_holdout_access": "denied",
        "default_retained_packets": len(consumer.packets),
        "evaluation_retained_packets": len(evaluation.packets),
        "model_message_roles": ["user", "assistant"],
    }


def _prefreeze_identity(
    *,
    design_lock_path: Path,
    plan054_input_identity: Mapping[str, Any],
    base_manifest_content_sha256: str,
    combined: Mapping[str, Sequence[Mapping[str, Any]]],
    candidate_reviews: Sequence[Mapping[str, Any]],
    pair_reviews: Sequence[Mapping[str, Any]],
    candidate_dispositions: Sequence[Mapping[str, Any]],
    pair_dispositions: Sequence[Mapping[str, Any]],
    lineage: Mapping[str, Any],
    quality_audit_sha256: str,
    aggregate_review_bindings_sha256: str,
    mechanical_artifacts_sha256: str,
) -> dict[str, Any]:
    semantic = {
        "schema": "rondo-publication-critic-plan064-prefreeze-identity-v1",
        "dataset_revision": "v8",
        "design_lock_sha256": sha256_file(design_lock_path),
        "plan054_input_identity": dict(plan054_input_identity),
        "base_manifest_content_sha256": base_manifest_content_sha256,
        "semantic_content_sha256": {
            "scenarios": _rows_semantic_sha256(combined["scenarios"], "scenario_id"),
            "packets": _rows_semantic_sha256(combined["packets"], "candidate_id"),
            "supervision": _rows_semantic_sha256(
                combined["supervision"], "candidate_id"
            ),
            "pairs": _rows_semantic_sha256(combined["pairs"], "pair_id"),
            "candidate_reviews": _rows_semantic_sha256(
                candidate_reviews, "candidate_id"
            ),
            "pair_reviews": _rows_semantic_sha256(pair_reviews, "pair_id"),
            "candidate_dispositions": _rows_semantic_sha256(
                candidate_dispositions, "candidate_id"
            ),
            "pair_dispositions": _rows_semantic_sha256(
                pair_dispositions, "pair_id"
            ),
            "lineage": sha256_bytes(canonical_json_bytes(lineage)),
            "quality_audit": _sha256(
                quality_audit_sha256,
                "quality audit canonical identity",
            ),
            "aggregate_review_bindings": _sha256(
                aggregate_review_bindings_sha256,
                "aggregate review bindings canonical identity",
            ),
            "mechanical_artifacts": _sha256(
                mechanical_artifacts_sha256,
                "phase-independent mechanical artifacts identity",
            ),
        },
    }
    return {
        **semantic,
        "universe_sha256": sha256_bytes(canonical_json_bytes(semantic)),
    }


def _validate_base_release(
    base_dir: Path,
    manifest: Mapping[str, Any],
    design_lock: Mapping[str, Any],
    *,
    expected_input_identity: Mapping[str, Any],
) -> None:
    base_contract = design_lock["base_release"]
    if _git_tree_oid(base_dir) != base_contract.get("git_tree_oid"):
        raise TrainingDataError("Plan 064 v7 directory bytes or tracked modes drifted")
    if manifest.get("dataset_revision") != "v7":
        raise TrainingDataError("Plan 064 base release must be v7")
    if manifest.get("content_sha256") != base_contract["manifest_content_sha256"]:
        raise TrainingDataError("Plan 064 v7 manifest identity drifted")
    verify_freeze_manifest(
        base_dir, manifest, expected_input_identity=expected_input_identity
    )


def _git_tree_oid(directory: Path) -> str:
    """Compute the Git tree identity for one flat, regular-file release."""

    if directory.is_symlink() or not directory.is_dir():
        raise TrainingDataError("Plan 064 v7 base directory is missing or unsafe")
    entries: list[bytes] = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name.encode("utf-8")):
        if path.is_symlink() or not path.is_file():
            raise TrainingDataError("Plan 064 v7 base must contain only regular files")
        content = path.read_bytes()
        blob = hashlib.sha1(  # noqa: S324 - this reproduces a Git object identity
            b"blob " + str(len(content)).encode("ascii") + b"\0" + content,
            usedforsecurity=False,
        ).digest()
        mode = b"100755" if path.stat().st_mode & 0o111 else b"100644"
        entries.append(mode + b" " + path.name.encode("utf-8") + b"\0" + blob)
    body = b"".join(entries)
    return hashlib.sha1(  # noqa: S324 - this reproduces a Git object identity
        b"tree " + str(len(body)).encode("ascii") + b"\0" + body,
        usedforsecurity=False,
    ).hexdigest()


def _validate_design_lock(design_lock: Mapping[str, Any]) -> None:
    if (
        design_lock.get("schema")
        != "rondo-publication-critic-training-data-design-lock-v8"
        or design_lock.get("dataset_revision") != "v8"
    ):
        raise TrainingDataError("Plan 064 design lock identity drifted")
    if design_lock.get("review_contract", {}).get("admission_strategy") != "direct_review_all_new":
        raise TrainingDataError("Plan 064 requires direct review of every new row")
    if design_lock.get("release_layout", {}).get("strategy") != "full_materialization":
        raise TrainingDataError("Plan 064 release layout must use full materialization")


def _validate_quality_audit(
    audit: Mapping[str, Any],
    *,
    combined: Mapping[str, Sequence[Mapping[str, Any]]],
    candidate_ids: set[str],
    pair_ids: set[str],
    assignments: Mapping[str, str],
    pairs: Sequence[Mapping[str, Any]],
    audit_strata: Plan064QualityAuditStrata,
    expected_sampling_seed: int,
) -> dict[str, Any]:
    """Validate the one Plan 064 release-quality audit evidence object."""

    if set(audit) != _QUALITY_AUDIT_KEYS:
        raise TrainingDataError("Plan 064 quality audit keys differ")
    if audit.get("schema") != "rondo-publication-critic-plan064-quality-audit-v1":
        raise TrainingDataError("Plan 064 quality audit schema drifted")

    universe = audit.get("universe")
    if not isinstance(universe, Mapping) or set(universe) != _QUALITY_AUDIT_UNIVERSE_KEYS:
        raise TrainingDataError("Plan 064 quality audit universe keys differ")
    expected_universe = {
        "candidate_ids_sha256": _id_universe_sha256(candidate_ids),
        "final_split_sha256": _split_assignments_sha256(assignments),
        "pair_ids_sha256": _id_universe_sha256(pair_ids),
        "reviewed_content_sha256": quality_audit_content_sha256(combined),
    }
    for key, expected in expected_universe.items():
        observed = _sha256(universe.get(key), f"quality audit universe.{key}")
        if observed != expected:
            raise TrainingDataError(
                f"Plan 064 quality audit {key} does not bind the complete release universe"
            )

    sampling_seed = audit.get("sampling_seed")
    if (
        not isinstance(sampling_seed, int)
        or isinstance(sampling_seed, bool)
        or not 0 <= sampling_seed <= 2**63 - 1
    ):
        raise TrainingDataError(
            "Plan 064 quality audit sampling_seed must be a non-negative 63-bit integer"
        )
    if sampling_seed != expected_sampling_seed:
        raise TrainingDataError(
            "Plan 064 quality audit sampling_seed differs from the design lock"
        )
    strata = _audit_identifier_list(audit.get("strata"), "quality audit strata")
    if not strata:
        raise TrainingDataError("Plan 064 quality audit strata must not be empty")
    sampled_candidates = _audit_identifier_list(
        audit.get("sampled_candidate_ids"),
        "quality audit sampled candidate IDs",
    )
    sampled_pairs = _audit_identifier_list(
        audit.get("sampled_pair_ids"),
        "quality audit sampled pair IDs",
    )
    if not set(sampled_candidates) <= candidate_ids:
        raise TrainingDataError(
            "Plan 064 quality audit samples candidate IDs outside the complete release"
        )
    if not set(sampled_pairs) <= pair_ids:
        raise TrainingDataError(
            "Plan 064 quality audit samples pair IDs outside the complete release"
        )
    if candidate_ids and not sampled_candidates:
        raise TrainingDataError(
            "Plan 064 quality audit must sample at least one candidate"
        )
    if pair_ids and not sampled_pairs:
        raise TrainingDataError(
            "Plan 064 quality audit must sample at least one pair"
        )
    validate_plan064_quality_audit_sample(
        declared_strata=strata,
        sampled_candidate_ids=set(sampled_candidates),
        sampled_pair_ids=set(sampled_pairs),
        strata=audit_strata,
    )
    pair_index = _index(pairs, "pair_id", "quality audit pairs")
    for pair_id in sampled_pairs:
        pair = pair_index[pair_id]
        missing_endpoints = {
            str(pair["preferred_candidate_id"]),
            str(pair["dispreferred_candidate_id"]),
        } - set(sampled_candidates)
        if missing_endpoints:
            raise TrainingDataError(
                "Plan 064 quality audit sampled pair endpoints are missing from "
                f"the candidate sample: {pair_id}"
            )

    findings = audit.get("findings")
    if not isinstance(findings, list):
        raise TrainingDataError("Plan 064 quality audit findings must be a list")
    finding_status_counts: Counter[str] = Counter()
    observed_findings: set[bytes] = set()
    for index, finding in enumerate(findings):
        if not isinstance(finding, Mapping) or set(finding) != _QUALITY_AUDIT_FINDING_KEYS:
            raise TrainingDataError(
                f"Plan 064 quality audit finding {index} keys differ"
            )
        status_value = finding.get("status")
        if (
            not isinstance(status_value, str)
            or status_value not in _TERMINAL_QUALITY_FINDING_STATUSES
        ):
            raise TrainingDataError(
                f"Plan 064 quality audit finding {index} is unresolved or has an unknown status"
            )
        affected_candidates = _audit_identifier_list(
            finding.get("affected_candidate_ids"),
            f"quality audit finding {index} affected candidate IDs",
        )
        affected_pairs = _audit_identifier_list(
            finding.get("affected_pair_ids"),
            f"quality audit finding {index} affected pair IDs",
        )
        if not affected_candidates and not affected_pairs:
            raise TrainingDataError(
                f"Plan 064 quality audit finding {index} has no affected IDs"
            )
        if not set(affected_candidates) <= candidate_ids:
            raise TrainingDataError(
                f"Plan 064 quality audit finding {index} names a candidate outside the release"
            )
        if not set(affected_pairs) <= pair_ids:
            raise TrainingDataError(
                f"Plan 064 quality audit finding {index} names a pair outside the release"
            )
        canonical_finding = canonical_json_bytes(finding)
        if canonical_finding in observed_findings:
            raise TrainingDataError("Plan 064 quality audit has duplicate findings")
        observed_findings.add(canonical_finding)
        finding_status_counts[status_value] += 1

    unresolved = audit.get("unresolved_systemic_findings")
    if unresolved != 0 or isinstance(unresolved, bool):
        raise TrainingDataError(
            "Plan 064 quality audit unresolved_systemic_findings must equal zero"
        )

    summary = audit.get("summary_counts")
    if not isinstance(summary, Mapping) or set(summary) != _QUALITY_AUDIT_SUMMARY_KEYS:
        raise TrainingDataError("Plan 064 quality audit summary_counts keys differ")
    expected_counts = {
        "complete_candidate_count": len(candidate_ids),
        "complete_pair_count": len(pair_ids),
        "sampled_candidate_count": len(sampled_candidates),
        "sampled_pair_count": len(sampled_pairs),
        "stratum_count": len(strata),
        "finding_count": len(findings),
    }
    for key, expected in expected_counts.items():
        observed = summary.get(key)
        if (
            not isinstance(observed, int)
            or isinstance(observed, bool)
            or observed < 0
            or observed != expected
        ):
            raise TrainingDataError(
                f"Plan 064 quality audit summary count does not reconcile: {key}"
            )

    return {
        "schema": audit["schema"],
        "canonical_sha256": sha256_bytes(canonical_json_bytes(audit)),
        "sampling_seed": sampling_seed,
        "strata": list(strata),
        "summary_counts": dict(summary),
        "finding_status_counts": dict(sorted(finding_status_counts.items())),
        "unresolved_systemic_findings": 0,
    }


def _audit_identifier_list(value: Any, where: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise TrainingDataError(f"{where} must be a list")
    result: list[str] = []
    for index, item in enumerate(value):
        if (
            not isinstance(item, str)
            or not item
            or len(item) > 160
            or any(character.isspace() for character in item)
        ):
            raise TrainingDataError(f"{where}[{index}] must be a stable ID")
        result.append(item)
    if len(result) != len(set(result)):
        raise TrainingDataError(f"{where} must not contain duplicates")
    return tuple(result)


def _id_universe_sha256(ids: set[str]) -> str:
    return sha256_bytes(canonical_json_bytes(sorted(ids)))


def _split_assignments_sha256(assignments: Mapping[str, str]) -> str:
    return sha256_bytes(
        canonical_json_bytes(
            {candidate_id: assignments[candidate_id] for candidate_id in sorted(assignments)}
        )
    )


def quality_audit_content_sha256(
    combined: Mapping[str, Sequence[Mapping[str, Any]]],
) -> str:
    """Bind audit evidence to reviewed content without lifecycle bookkeeping.

    Final split assignments, review records, and dispositions are separately
    bound by the prefreeze identity.  The audit concerns the candidate and pair
    semantics themselves, so this projection excludes only split and terminal
    review lifecycle fields.
    """

    projected_supervision = [
        {
            key: value
            for key, value in row.items()
            if key not in {"proposed_split", "reviewer_identity", "review_status"}
        }
        for row in combined["supervision"]
    ]
    projected_pairs = [
        {key: value for key, value in row.items() if key != "review_status"}
        for row in combined["pairs"]
    ]
    semantic = {
        "scenarios": _rows_semantic_sha256(combined["scenarios"], "scenario_id"),
        "packets": _rows_semantic_sha256(combined["packets"], "candidate_id"),
        "supervision": _rows_semantic_sha256(
            projected_supervision,
            "candidate_id",
        ),
        "pairs": _rows_semantic_sha256(projected_pairs, "pair_id"),
    }
    return sha256_bytes(canonical_json_bytes(semantic))


def _validate_plan054_design_identity(
    design_lock: Mapping[str, Any], input_identity: Mapping[str, Any]
) -> None:
    expected = design_lock["plan054_input_contract"]
    actual = {
        "plan054_freeze_sha256": input_identity["plan054_freeze_sha256"],
        "packet": (
            f"{input_identity['packet_schema']['name']}@"
            f"{input_identity['packet_schema']['revision']}"
        ),
        "qualification_rubric": (
            f"{input_identity['qualification_rubric']['name']}@"
            f"{input_identity['qualification_rubric']['revision']}"
        ),
        "render_contract": input_identity["render_contract"],
        "input_template_revision": input_identity["input_template_revision"],
        "tokenizer_name": input_identity["tokenizer_name"],
        "tokenizer_revision": input_identity["tokenizer_revision"],
        "candidate_truncation": input_identity["candidate_truncation"],
        "token_window": input_identity["adopted_window_tokens"],
        "overflow_policy": input_identity["continuity_overflow"],
        "messages": [
            "current_task_and_prior_publications",
            "candidate_to_judge",
        ],
        "scalar_direction": "higher_is_better",
        "source_allowlist": [
            "request.context",
            "request.developer_instructions",
            "request.user_instructions",
            "prior_publications",
            "public_candidate",
        ],
        "forbidden_sources": [
            "private_reasoning",
            "hidden_transcript",
            "raw_tool_output",
            "private_fact_body",
            "credentials",
        ],
    }
    if set(expected) != set(actual):
        raise TrainingDataError("Plan 064 Plan 054 identity keys drifted")
    for key, value in actual.items():
        if expected.get(key) != value:
            raise TrainingDataError(f"Plan 064 Plan 054 identity drifted: {key}")


def _validate_phase_and_paths(
    phase: str,
    *,
    output_dir: Path,
    ignored_namespace: Path,
    formal_release_dir: Path,
    approved_prefreeze_identity: str | None,
) -> None:
    if phase not in {"prefreeze", "freeze"}:
        raise TrainingDataError("Plan 064 phase must be prefreeze or freeze")
    if (
        ignored_namespace.is_symlink()
        or not ignored_namespace.is_dir()
        or stat.S_IMODE(ignored_namespace.stat().st_mode) != 0o700
    ):
        raise TrainingDataError("Plan 064 ignored namespace must be a mode-0700 directory")
    resolved_output = output_dir.resolve()
    ignored_root = ignored_namespace.resolve()
    formal_root = formal_release_dir.resolve()
    if phase == "prefreeze":
        if ignored_root not in resolved_output.parents:
            raise TrainingDataError("prefreeze output must be a child of the Plan 064 ignored namespace")
        if approved_prefreeze_identity is not None:
            raise TrainingDataError("prefreeze must not accept a freeze approval")
    else:
        if resolved_output != formal_root:
            raise TrainingDataError("freeze output must be the formal Plan 064 release directory")
        _sha256(approved_prefreeze_identity, "approved prefreeze identity")


def _prepare_output(path: Path, *, ignored: bool) -> tuple[Path, bool]:
    if path.parent.is_symlink() or not path.parent.is_dir():
        raise TrainingDataError("Plan 064 output parent must be an existing safe directory")
    try:
        resolved_parent = path.parent.resolve(strict=True)
    except OSError as exc:
        raise TrainingDataError("Plan 064 output parent cannot be resolved") from exc
    if path.parent.absolute() != resolved_parent:
        raise TrainingDataError("Plan 064 output parent must not traverse symlinks")
    if path.exists() or path.is_symlink():
        raise TrainingDataError("Plan 064 output directory must be a new path")
    path.mkdir(mode=0o700 if ignored else 0o755)
    path.chmod(0o700 if ignored else 0o755)
    return path.resolve(), ignored


def _validate_secure_ignored_directory(path: Path, namespace: Path) -> None:
    if path.is_symlink() or not path.is_dir():
        raise TrainingDataError("Plan 064 delta directory is missing or unsafe")
    if path.absolute() != path.resolve(strict=True):
        raise TrainingDataError("Plan 064 delta path must not traverse symlinks")
    if namespace.resolve() not in path.resolve().parents:
        raise TrainingDataError("Plan 064 delta must be inside its ignored namespace")
    if stat.S_IMODE(path.stat().st_mode) != 0o700:
        raise TrainingDataError("Plan 064 delta directory must be mode 0700")


def _write_new(path: Path, content: bytes, *, ignored: bool) -> None:
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600 if ignored else 0o644,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
    path.chmod(0o600 if ignored else 0o644)


def _load_json(path: Path, *, secure: bool = False) -> dict[str, Any]:
    _validate_input(path, secure=secure)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrainingDataError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise TrainingDataError(f"JSON root must be an object: {path}")
    return value


def _load_jsonl(path: Path, *, secure: bool = False) -> list[dict[str, Any]]:
    _validate_input(path, secure=secure)
    rows: list[dict[str, Any]] = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line:
                raise TrainingDataError(f"blank JSONL line: {path}:{line_number}")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TrainingDataError(f"JSONL row must be an object: {path}:{line_number}")
            rows.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrainingDataError(f"cannot read JSONL: {path}") from exc
    return rows


def _validate_input(path: Path, *, secure: bool) -> None:
    if path.is_symlink() or not path.is_file():
        raise TrainingDataError(f"input file is missing or unsafe: {path}")
    if secure and stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise TrainingDataError(f"ignored Plan 064 input must be mode 0600: {path}")


def _index(
    rows: Sequence[Mapping[str, Any]], key: str, where: str
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if not isinstance(value, str) or not value or value in result:
            raise TrainingDataError(f"invalid or duplicate {key} in {where}: {value!r}")
        result[value] = row
    return result


def _source_ids(
    design_lock: Mapping[str, Any], *, membership: str | None
) -> frozenset[str]:
    values = []
    for row in design_lock["source_allowlist"]:
        state = row["membership"]
        if (membership is None and state != "forbidden") or state == membership:
            values.append(str(row["source_id"]))
    return frozenset(values)


def _authored_assignments(
    supervision_rows: Sequence[Mapping[str, Any]],
) -> dict[str, str]:
    result: dict[str, str] = {}
    for row in supervision_rows:
        split = row.get("proposed_split")
        if split not in {"train", "validation", "unseen_test"}:
            raise TrainingDataError(
                f"Plan 064 requires an authored fixed split: {row.get('candidate_id')}"
            )
        result[str(row["candidate_id"])] = str(split)
    return result


def _split_index(
    supervision_rows: Sequence[Mapping[str, Any]], dataset_revision: str
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "dataset_revision": dataset_revision,
        "splits": {
            split: sorted(
                str(row["candidate_id"])
                for row in supervision_rows
                if row["proposed_split"] == split
            )
            for split in ("train", "validation", "unseen_test")
        },
    }


def _statistics(
    supervision_rows: Sequence[Mapping[str, Any]],
    pair_rows: Sequence[Mapping[str, Any]],
    token_summary: Mapping[str, Any],
) -> dict[str, Any]:
    split_by_candidate = {
        str(row["candidate_id"]): str(row["proposed_split"])
        for row in supervision_rows
    }
    return {
        "candidate_count": len(supervision_rows),
        "scenario_count": len({row["scenario_id"] for row in supervision_rows}),
        "split_counts": dict(
            sorted(Counter(row["proposed_split"] for row in supervision_rows).items())
        ),
        "binary_counts": dict(
            sorted(Counter(row["binary_label"] for row in supervision_rows).items())
        ),
        "pair_counts": dict(sorted(Counter(row["kind"] for row in pair_rows).items())),
        "pairs_by_split": {
            split: dict(
                sorted(
                    Counter(
                        row["kind"]
                        for row in pair_rows
                        if split_by_candidate[str(row["preferred_candidate_id"])] == split
                    ).items()
                )
            )
            for split in ("train", "validation", "unseen_test")
        },
        "token_census": dict(token_summary),
    }


def _validate_exact_length_buckets(
    supervision_rows: Sequence[Mapping[str, Any]],
    census_rows: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    census = _index(census_rows, "candidate_id", "token census")
    supervision = _index(supervision_rows, "candidate_id", "supervision rows")
    if set(census) != set(supervision):
        raise TrainingDataError(
            "length-bucket census and supervision candidate IDs differ"
        )
    long_minimum = contract.get("long_exact_input_min_tokens")
    non_long_maximum = contract.get("non_long_exact_input_max_tokens")
    if (
        not isinstance(long_minimum, int)
        or isinstance(long_minimum, bool)
        or not isinstance(non_long_maximum, int)
        or isinstance(non_long_maximum, bool)
        or long_minimum <= 0
        or non_long_maximum < 0
        or non_long_maximum >= long_minimum
    ):
        raise TrainingDataError("Plan 064 length-bucket thresholds are invalid")

    observed: dict[str, list[int]] = {
        "short": [],
        "medium": [],
        "long": [],
    }
    for candidate_id, row in supervision.items():
        bucket = row.get("length_bucket")
        if bucket not in observed:
            raise TrainingDataError(
                f"candidate {candidate_id} has an invalid length bucket"
            )
        token_count = census[candidate_id].get("token_count")
        if (
            not isinstance(token_count, int)
            or isinstance(token_count, bool)
            or token_count < 0
        ):
            raise TrainingDataError(
                f"candidate {candidate_id} lacks exact total token_count"
            )
        if bucket == "long" and token_count < long_minimum:
            raise TrainingDataError(
                f"long candidate {candidate_id} has only {token_count} exact input tokens"
            )
        if bucket != "long" and token_count > non_long_maximum:
            raise TrainingDataError(
                f"non-long candidate {candidate_id} has {token_count} exact input tokens"
            )
        observed[str(bucket)].append(token_count)

    return {
        "status": "pass",
        "long_exact_input_min_tokens": long_minimum,
        "non_long_exact_input_max_tokens": non_long_maximum,
        "candidate_counts": {
            bucket: len(values) for bucket, values in observed.items()
        },
        "observed_token_ranges": {
            bucket: {
                "min": min(values) if values else None,
                "max": max(values) if values else None,
            }
            for bucket, values in observed.items()
        },
    }
def _data_card(
    dataset_revision: str,
    statistics: Mapping[str, Any],
    identity: Mapping[str, Any],
) -> str:
    return f"""# Publication Critic training data {dataset_revision}

This is the full-materialized Plan 064 release over the immutable v7 base and
directly reviewed Plan 064 additions.

- Candidates: {statistics['candidate_count']}
- Splits: {json.dumps(statistics['split_counts'], ensure_ascii=False, sort_keys=True)}
- Pairs: {json.dumps(statistics['pair_counts'], ensure_ascii=False, sort_keys=True)}
- Exact-token total: {statistics['token_census']['token_total']}
- Approved prefreeze universe: `{identity['universe_sha256']}`

The default consumer physically exposes train rows only. Validation and unseen
test access requires explicit evaluation mode. Labels are synthetic teacher
references, not human-labelled ground truth. This data release does not itself
establish model quality or authorize training.
"""


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2
    ).encode("utf-8") + b"\n"


def _jsonl_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(row) for row in rows)


def _rows_semantic_sha256(
    rows: Sequence[Mapping[str, Any]], id_key: str
) -> str:
    ordered = sorted(rows, key=lambda row: str(row.get(id_key)))
    if len({row.get(id_key) for row in ordered}) != len(ordered):
        raise TrainingDataError(f"semantic identity contains duplicate {id_key}")
    return sha256_bytes(canonical_json_bytes(ordered))


def _sha256(value: Any, where: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TrainingDataError(f"{where} must be lowercase SHA-256")
    return value


def _full_git_sha(value: Any) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise TrainingDataError("generation commit must be a full lowercase Git SHA")
    return value
