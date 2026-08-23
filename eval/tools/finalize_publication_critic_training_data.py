#!/usr/bin/env python3
"""Finalize one reviewed Plan 059 batch without loading a reward model."""

import argparse
from collections import Counter
import copy
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any


EVAL_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_ROOT.parent
sys.path.insert(0, str(EVAL_ROOT))

from rondo_eval.publication_critic.contract import load_fixed_input_contract  # noqa: E402
from rondo_eval.publication_critic.identity import canonical_json_bytes, sha256_file  # noqa: E402
from rondo_eval.publication_critic.render import build_messages  # noqa: E402
from rondo_eval.publication_critic.runner import load_exact_tokenizer  # noqa: E402
from rondo_eval.publication_critic.training_data import (  # noqa: E402
    DatasetConsumer,
    TrainingDataError,
    build_freeze_manifest,
    build_group_components,
    build_memberships,
    build_train_only_smoke_bundle,
    census_packets,
    coverage_failures,
    deterministic_grouped_stratified_split,
    find_near_duplicate_edges,
    find_reference_matches,
    model_visible_text_shortcut_findings,
    reject_exact_duplicates,
    reject_model_visible_text_shortcuts,
    reject_perfect_shortcuts,
    shortcut_contingencies,
    validate_candidate_review,
    validate_dataset,
    validate_generation_batch,
    validate_group_closure,
    validate_pair_review,
    validate_train_only_smoke_bundle,
    verify_freeze_manifest,
)


IGNORED_NAMESPACE = Path(
    "/home/sjc/desktop/RONDO/eval-data/publication-critic/plan059"
).resolve()
DESIGN_LOCK_PATH = (
    REPO_ROOT / "eval/templates/publication-critic/training-data-design-lock-v2.json"
)
BASE_DESIGN_LOCK_PATH = (
    REPO_ROOT / "eval/templates/publication-critic/training-data-design-lock-v1.json"
)
SCHEMA_PATH = REPO_ROOT / "eval/templates/publication-critic/training-data-schema-v1.json"
GENERATOR_PROMPT_PATH = (
    REPO_ROOT / "eval/templates/publication-critic/training-data-generator-prompt-v2.md"
)
REVIEWER_PROMPT_PATH = (
    REPO_ROOT / "eval/templates/publication-critic/training-data-reviewer-prompt-v1.md"
)
REFERENCE_PACKETS_PATH = REPO_ROOT / "eval/fixtures/publication-critic-v1/packets.jsonl"


def _load_json(path: Path, *, secure_ignored: bool = False) -> dict[str, Any]:
    _validate_input_file(path, secure_ignored=secure_ignored)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrainingDataError(f"cannot read JSON: {path}") from exc
    if not isinstance(value, dict):
        raise TrainingDataError(f"JSON root must be an object: {path}")
    return value


def _load_design_lock() -> dict[str, Any]:
    overlay = _load_json(DESIGN_LOCK_PATH)
    if overlay.get("schema") != "rondo-publication-critic-training-data-design-lock-v2":
        raise TrainingDataError("training-data design lock v2 identity drifted")
    base_identity = overlay.get("base_lock")
    overrides = overlay.get("overrides")
    if not isinstance(base_identity, dict) or not isinstance(overrides, dict):
        raise TrainingDataError("training-data design lock v2 overlay is invalid")
    expected_base = {
        "relative_path": BASE_DESIGN_LOCK_PATH.relative_to(REPO_ROOT).as_posix(),
        "sha256": sha256_file(BASE_DESIGN_LOCK_PATH),
    }
    if base_identity != expected_base:
        raise TrainingDataError("training-data design lock v2 base identity drifted")
    base = _load_json(BASE_DESIGN_LOCK_PATH)
    merged = copy.deepcopy(base)
    merged["schema"] = overlay["schema"]
    merged["dataset_revision"] = overlay["dataset_revision"]
    merged["purpose"] = overlay["purpose"]
    merged["split_contract"]["seed"] = overrides["split_seed"]
    merged["visible_text_shortcut_contract"] = overrides["visible_text_shortcut_contract"]
    merged["template_group_rule"] = overrides["template_group_rule"]
    if overrides["generator_prompt_relative_path"] != GENERATOR_PROMPT_PATH.relative_to(REPO_ROOT).as_posix():
        raise TrainingDataError("training-data generator prompt v2 path drifted")
    return merged


def _load_jsonl(path: Path, *, secure_ignored: bool = False) -> list[dict[str, Any]]:
    _validate_input_file(path, secure_ignored=secure_ignored)
    rows: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                raise TrainingDataError(f"blank JSONL line: {path}:{line_number}")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise TrainingDataError(f"JSONL row must be an object: {path}:{line_number}")
            rows.append(value)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise TrainingDataError(f"cannot read JSONL: {path}") from exc
    return rows


def _validate_input_file(path: Path, *, secure_ignored: bool) -> None:
    if path.is_symlink() or not path.is_file():
        raise TrainingDataError(f"input file is missing or unsafe: {path}")
    if secure_ignored and stat.S_IMODE(path.stat().st_mode) != 0o600:
        raise TrainingDataError(f"ignored input file must be mode 0600: {path}")


def _prepare_output(path: Path) -> tuple[Path, bool]:
    resolved = path.resolve()
    ignored = resolved == IGNORED_NAMESPACE or IGNORED_NAMESPACE in resolved.parents
    tracked = resolved == REPO_ROOT / "training" or (REPO_ROOT / "training") in resolved.parents
    if not ignored and not tracked:
        raise TrainingDataError("output must be inside the Plan 059 ignored namespace or repo training/")
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise TrainingDataError(f"output directory is unsafe: {path}")
        if any(path.iterdir()):
            raise TrainingDataError(f"output directory must be new or empty: {path}")
    else:
        path.mkdir(parents=True, mode=0o700 if ignored else 0o755)
    path.chmod(0o700 if ignored else 0o755)
    return path.resolve(), ignored


def _write(path: Path, content: bytes, *, ignored: bool) -> None:
    if path.exists() and path.is_symlink():
        raise TrainingDataError(f"refusing symlink output: {path}")
    descriptor = os.open(
        path,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
        0o600 if ignored else 0o644,
    )
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(content)
    path.chmod(0o600 if ignored else 0o644)


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        indent=2,
    ).encode("utf-8") + b"\n"


def _jsonl_bytes(rows: list[dict[str, Any]]) -> bytes:
    return b"".join(canonical_json_bytes(row) for row in rows)


def _index(rows: list[dict[str, Any]], key: str, where: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = row.get(key)
        if not isinstance(value, str) or not value or value in result:
            raise TrainingDataError(f"invalid or duplicate {key} in {where}: {value!r}")
        result[value] = row
    return result


def _allowed_source_ids(design_lock: dict[str, Any]) -> frozenset[str]:
    return frozenset(
        str(row["source_id"])
        for row in design_lock["source_allowlist"]
        if row["membership"] != "forbidden"
    )


def _merge_terminal_reviews(
    supervision_rows: list[dict[str, Any]],
    pair_rows: list[dict[str, Any]],
    candidate_reviews: list[dict[str, Any]],
    pair_reviews: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidate_by_id = _index(candidate_reviews, "candidate_id", "candidate reviews")
    pair_by_id = _index(pair_reviews, "pair_id", "pair reviews")
    if set(candidate_by_id) != {row["candidate_id"] for row in supervision_rows}:
        raise TrainingDataError("candidate review IDs do not exactly match supervision")
    if set(pair_by_id) != {row["pair_id"] for row in pair_rows}:
        raise TrainingDataError("pair review IDs do not exactly match pairs")
    final_supervision: list[dict[str, Any]] = []
    for raw in supervision_rows:
        row = copy.deepcopy(raw)
        review = candidate_by_id[row["candidate_id"]]
        if review["decision"] != "accept" or review["independent_label"] != row["binary_label"]:
            raise TrainingDataError(f"candidate lacks terminal accepting label review: {row['candidate_id']}")
        row["reviewer_identity"] = review["reviewer_identity"]
        row["review_status"] = "accept"
        final_supervision.append(row)
    final_pairs: list[dict[str, Any]] = []
    for raw in pair_rows:
        row = copy.deepcopy(raw)
        review = pair_by_id[row["pair_id"]]
        if review["decision"] != "accept":
            raise TrainingDataError(f"pair lacks terminal accepting review: {row['pair_id']}")
        row["review_status"] = "accept"
        final_pairs.append(row)
    return final_supervision, final_pairs


def _rehearsal_assignments(
    components: dict[str, str],
    supervision_rows: list[dict[str, Any]],
) -> dict[str, str]:
    desired_by_scenario = {
        "b-useful-01": "train",
        "b-scope-01": "train",
        "b-scope-02": "validation",
        "b-honest-01": "validation",
        "mixed-01": "validation",
        "b-continuity-01": "unseen_test",
        "b-consistency-01": "unseen_test",
    }
    result = {
        row["candidate_id"]: desired_by_scenario[row["scenario_id"]]
        for row in supervision_rows
    }
    by_component: dict[str, set[str]] = {}
    for candidate_id, component in components.items():
        by_component.setdefault(component, set()).add(result[candidate_id])
    conflicts = {component: splits for component, splits in by_component.items() if len(splits) != 1}
    if conflicts:
        raise TrainingDataError(f"rehearsal near-duplicate closure conflicts with fixed smoke split: {conflicts}")
    validate_group_closure(components, result)
    return result


def _split_index(
    supervision_rows: list[dict[str, Any]],
    dataset_revision: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "dataset_revision": dataset_revision,
        "splits": {
            split: sorted(
                row["candidate_id"]
                for row in supervision_rows
                if row["proposed_split"] == split
            )
            for split in ("train", "validation", "unseen_test")
        },
    }


def _statistics(
    supervision_rows: list[dict[str, Any]],
    pair_rows: list[dict[str, Any]],
    token_summary: dict[str, Any],
) -> dict[str, Any]:
    split_counts = Counter(row["proposed_split"] for row in supervision_rows)
    label_counts = Counter(row["binary_label"] for row in supervision_rows)
    pair_counts = Counter(row["kind"] for row in pair_rows)
    label_by_split: dict[str, dict[str, int]] = {}
    pair_by_split: dict[str, dict[str, int]] = {}
    split_by_candidate = {row["candidate_id"]: row["proposed_split"] for row in supervision_rows}
    for split in ("train", "validation", "unseen_test"):
        label_by_split[split] = dict(
            sorted(
                Counter(
                    row["binary_label"]
                    for row in supervision_rows
                    if row["proposed_split"] == split
                ).items()
            )
        )
        pair_by_split[split] = dict(
            sorted(
                Counter(
                    row["kind"]
                    for row in pair_rows
                    if split_by_candidate[row["preferred_candidate_id"]] == split
                ).items()
            )
        )
    return {
        "candidate_count": len(supervision_rows),
        "scenario_group_count": len({row["scenario_group"] for row in supervision_rows}),
        "split_counts": dict(sorted(split_counts.items())),
        "binary_counts": dict(sorted(label_counts.items())),
        "binary_by_split": label_by_split,
        "pair_counts": dict(sorted(pair_counts.items())),
        "pairs_by_split": pair_by_split,
        "token_census": token_summary,
    }


def _contract_hashes(teacher_freeze: Path | None) -> dict[str, str]:
    paths = [
        DESIGN_LOCK_PATH,
        BASE_DESIGN_LOCK_PATH,
        SCHEMA_PATH,
        GENERATOR_PROMPT_PATH,
        REVIEWER_PROMPT_PATH,
        REPO_ROOT / "eval/templates/publication-critic/input-contract-v2.md",
        REPO_ROOT / "eval/templates/publication-critic/qualification-rubric-v1.md",
        REPO_ROOT / "eval/templates/publication-critic/render-contract-v3.json",
        REPO_ROOT / "eval/templates/publication-critic/product-packet-limits-v1.json",
        REPO_ROOT / "eval/tools/generate_publication_critic_training_data.py",
        Path(__file__),
    ]
    paths.extend(sorted((EVAL_ROOT / "rondo_eval/publication_critic/training_data").glob("*.py")))
    if teacher_freeze is not None:
        paths.append(teacher_freeze)
    return {
        path.relative_to(REPO_ROOT).as_posix(): sha256_file(path)
        for path in sorted(paths)
    }


def _data_card(
    dataset_revision: str,
    mode: str,
    statistics: dict[str, Any],
    teacher_identity: dict[str, Any],
    reports: dict[str, Any],
) -> str:
    counts = statistics["binary_counts"]
    pairs = statistics["pair_counts"]
    split_counts = statistics["split_counts"]
    tokens = statistics["token_census"]
    return f"""# Publication Critic training data {dataset_revision}

This is the Plan 059 M3-B1a `{mode}` freeze. It contains PublicationPacket v1 model inputs plus separate Binary and pair supervision. Labels, splits, defects, source, pair direction, and teacher metadata are never included in model-visible messages.

## Contents

- Candidates: {statistics['candidate_count']} ({counts.get('PASS', 0)} PASS, {counts.get('REWRITE', 0)} REWRITE)
- Splits: train {split_counts.get('train', 0)}, validation {split_counts.get('validation', 0)}, unseen_test {split_counts.get('unseen_test', 0)}
- Pairs: {pairs.get('boundary', 0)} Boundary Q+/Q- and {pairs.get('within_pass', 0)} Within-PASS
- Exact-tokenizer census: {tokens['token_total']} total tokens, per-candidate range {tokens['token_min']}..{tokens['token_max']}, {tokens['dropped_oldest_publications_total']} total dropped oldest publications
- Near-duplicate edges: {len(reports['near_duplicate_edges'])}; these edges participate in group closure
- Plan 054 reference matches: {len(reports['plan054_reference_matches'])}
- Cross-split label-exclusive repeated model-visible fragments: {len(reports['model_visible_text_shortcuts'])}

## Identity and review

- Generator: `{teacher_identity['generator']['model']}` / `{teacher_identity['generator']['reasoning_effort']}` / `{teacher_identity['generator']['session_identity']}`
- Independent reviewer: `{teacher_identity['reviewer']['model']}` / `{teacher_identity['reviewer']['reasoning_effort']}` / `{teacher_identity['reviewer']['session_identity']}`
- Generator prompt SHA-256: `{teacher_identity['generator']['prompt_sha256']}`
- Reviewer prompt SHA-256: `{teacher_identity['reviewer']['prompt_sha256']}`

Every frozen candidate and pair has a terminal accepting independent review. Raw generator/reviewer records remain in the ignored Plan 059 namespace and are not training inputs.

## Consumer boundary

`membership.json` is cumulative: C1 is all train Binary supervision, C2 adds train Boundary pairs, and C3 adds train Within-PASS pairs. The default consumer denies validation and unseen-test access; explicit evaluation mode is required. `train-only-smoke-bundle.json` physically contains only train members.

## Limits

This dataset has not been used for training and does not establish model quality or unlock M3-B1b. Plan 059 independent acceptance and user-approved integration remain separate decisions.
"""


def finalize(args: argparse.Namespace) -> dict[str, Any]:
    raw_dir = args.raw_dir.resolve()
    if IGNORED_NAMESPACE not in raw_dir.parents or raw_dir.is_symlink() or not raw_dir.is_dir():
        raise TrainingDataError("raw directory must be a safe child of the Plan 059 ignored namespace")
    if stat.S_IMODE(raw_dir.stat().st_mode) != 0o700:
        raise TrainingDataError("raw directory must be mode 0700")
    output_dir, ignored_output = _prepare_output(args.output_dir)
    design_lock = _load_design_lock()
    dataset_revision = str(design_lock["dataset_revision"])
    schema = _load_json(SCHEMA_PATH)
    if schema.get("schema") != "rondo-publication-critic-training-data-schema-v1":
        raise TrainingDataError("training-data schema identity drifted")
    scenarios = _load_jsonl(raw_dir / "scenarios.jsonl", secure_ignored=True)
    packets = _load_jsonl(raw_dir / "packets.jsonl", secure_ignored=True)
    raw_supervision = _load_jsonl(raw_dir / "supervision.jsonl", secure_ignored=True)
    raw_pairs = _load_jsonl(raw_dir / "pairs.jsonl", secure_ignored=True)
    candidate_reviews = _load_jsonl(raw_dir / "candidate-reviews.jsonl", secure_ignored=True)
    pair_reviews = _load_jsonl(raw_dir / "pair-reviews.jsonl", secure_ignored=True)
    generator_run = _load_json(raw_dir / "generator-run.json", secure_ignored=True)
    reviewer_run = _load_json(raw_dir / "reviewer-run.json", secure_ignored=True)

    allowed_sources = _allowed_source_ids(design_lock)
    validate_generation_batch(
        scenarios,
        packets,
        raw_supervision,
        raw_pairs,
        allowed_source_ids=allowed_sources,
        repo_root=REPO_ROOT,
    )
    for row in candidate_reviews:
        validate_candidate_review(row)
    for row in pair_reviews:
        validate_pair_review(row)
    supervision, pairs = _merge_terminal_reviews(
        raw_supervision,
        raw_pairs,
        candidate_reviews,
        pair_reviews,
    )
    reviewer_identity = reviewer_run.get("reviewer_identity")
    if not isinstance(reviewer_identity, dict):
        raise TrainingDataError("reviewer run lacks reviewer_identity")
    if any(row["reviewer_identity"] != reviewer_identity for row in candidate_reviews + pair_reviews):
        raise TrainingDataError("review rows do not share the reviewer run identity")
    generator_identity = generator_run.get("generator_identity")
    if not isinstance(generator_identity, dict):
        raise TrainingDataError("generator run lacks generator_identity")
    if any(row["generator_identity"] != generator_identity for row in supervision):
        raise TrainingDataError("supervision rows do not share the generator run identity")
    if generator_run.get("mode") != args.mode:
        raise TrainingDataError("generator mode differs from finalizer mode")

    packet_hashes = reject_exact_duplicates(packets)
    dedup = design_lock["dedup_contract"]
    near_edges = find_near_duplicate_edges(
        packets,
        threshold=float(dedup["near_duplicate_threshold"]),
    )
    reference_rows = _load_jsonl(REFERENCE_PACKETS_PATH)
    reference_packets = {
        str(row["sample_id"]): row["packet"]
        for row in reference_rows
    }
    reference_matches = find_reference_matches(
        packets,
        reference_packets,
        threshold=float(dedup["plan054_reference_threshold"]),
    )
    if reference_matches:
        raise TrainingDataError("Plan 059 candidates are too close to the frozen Plan 054 cohort")

    components = build_group_components(supervision, pairs, near_duplicate_edges=near_edges)
    if args.mode == "formal":
        assignments = deterministic_grouped_stratified_split(
            components,
            supervision,
            pairs,
            design_lock,
        )
    else:
        assignments = _rehearsal_assignments(components, supervision)
    validate_group_closure(components, assignments)
    for row in supervision:
        row["proposed_split"] = assignments[row["candidate_id"]]

    snapshot = args.tokenizer_snapshot.resolve()
    expected_revision = design_lock["input_identity"]["tokenizer_revision"]
    if snapshot.name != expected_revision or snapshot.is_symlink() or not snapshot.is_dir():
        raise TrainingDataError("exact tokenizer snapshot identity is missing or drifted")
    tokenizer = load_exact_tokenizer(snapshot)
    fixed = load_fixed_input_contract(REPO_ROOT)
    census_rows_tuple, token_summary = census_packets(
        packets,
        tokenizer,
        fixed.rubric,
        repo_root=REPO_ROOT,
    )
    census_rows = list(census_rows_tuple)
    omissions = {
        row["candidate_id"]: row["dropped_oldest_publications"]
        for row in census_rows
    }
    validate_dataset(
        packets,
        supervision,
        pairs,
        scenario_rows=scenarios,
        candidate_reviews=candidate_reviews,
        pair_reviews=pair_reviews,
        dropped_oldest_publications=omissions,
        repo_root=REPO_ROOT,
        final=True,
        allowed_source_ids=allowed_sources,
    )

    failures = ()
    if args.mode == "formal":
        failures = coverage_failures(assignments, supervision, pairs, design_lock)
        if failures:
            raise TrainingDataError(f"formal coverage minimums failed: {failures}")
    dimensions = design_lock["shortcut_checks"]["dimensions"]
    contingencies = shortcut_contingencies(supervision, dimensions)
    reject_perfect_shortcuts(contingencies, minimum_support=4)
    visible_shortcut_contract = design_lock["visible_text_shortcut_contract"]
    visible_shortcuts = model_visible_text_shortcut_findings(
        packets,
        supervision,
        minimum_candidate_support=int(visible_shortcut_contract["minimum_candidate_support"]),
        minimum_split_support=int(visible_shortcut_contract["minimum_split_support"]),
    )
    reject_model_visible_text_shortcuts(visible_shortcuts)

    membership = build_memberships(supervision, pairs, dataset_revision=dataset_revision)
    consumer = DatasetConsumer.from_rows(
        packets,
        supervision,
        pairs,
        membership,
        repo_root=REPO_ROOT,
    )
    c1 = consumer.stage("C1")
    c2 = consumer.stage("C2")
    c3 = consumer.stage("C3")
    if c1["pairs"] or any(pair["kind"] != "boundary" for pair in c2["pairs"]):
        raise TrainingDataError("C1/C2 cumulative membership is invalid")
    if len(c3["pairs"]) != len(c2["pairs"]) + sum(
        pair["kind"] == "within_pass" and assignments[pair["preferred_candidate_id"]] == "train"
        for pair in pairs
    ):
        raise TrainingDataError("C3 cumulative membership is invalid")
    try:
        consumer.evaluation_split("unseen_test")
    except TrainingDataError:
        pass
    else:
        raise TrainingDataError("default consumer unexpectedly exposes unseen_test")
    evaluation_consumer = DatasetConsumer.from_rows(
        packets,
        supervision,
        pairs,
        membership,
        repo_root=REPO_ROOT,
        allow_evaluation=True,
    )
    if len(evaluation_consumer.evaluation_split("unseen_test")) != sum(
        row["proposed_split"] == "unseen_test" for row in supervision
    ):
        raise TrainingDataError("explicit evaluation consumer cannot reproduce unseen_test")
    for packet_row in packets:
        messages = build_messages(packet_row["packet"], fixed.rubric)
        if len(messages) != 2 or [row["role"] for row in messages] != ["user", "assistant"]:
            raise TrainingDataError(f"candidate does not materialize to two ordered messages: {packet_row['candidate_id']}")

    split_index = _split_index(supervision, dataset_revision)
    teacher_identity = {
        "schema": "rondo-publication-critic-plan059-teacher-identity-v1",
        "generator": generator_identity,
        "reviewer": reviewer_identity,
        "generator_run_id": generator_run.get("run_id"),
        "review_run_kind": reviewer_run.get("run_kind"),
    }
    reports = {
        "schema": "rondo-publication-critic-training-finalization-report-v1",
        "mode": args.mode,
        "review": {
            "candidate_decisions": dict(sorted(Counter(row["decision"] for row in candidate_reviews).items())),
            "pair_decisions": dict(sorted(Counter(row["decision"] for row in pair_reviews).items())),
        },
        "coverage_failures": list(failures),
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
        "shortcut_contingencies": contingencies,
        "model_visible_text_shortcuts": list(visible_shortcuts),
        "token_summary": token_summary,
        "consumer": {
            "c1_binary": len(c1["binary"]),
            "c1_pairs": len(c1["pairs"]),
            "c2_binary": len(c2["binary"]),
            "c2_pairs": len(c2["pairs"]),
            "c3_binary": len(c3["binary"]),
            "c3_pairs": len(c3["pairs"]),
            "default_holdout_access": "denied",
            "model_message_roles": ["user", "assistant"],
        },
    }
    statistics = _statistics(supervision, pairs, token_summary)

    base_files = {
        "scenarios.jsonl": _jsonl_bytes(scenarios),
        "packets.jsonl": _jsonl_bytes(packets),
        "supervision.jsonl": _jsonl_bytes(supervision),
        "pairs.jsonl": _jsonl_bytes(pairs),
        "token-census.jsonl": _jsonl_bytes(census_rows),
        "split-index.json": _json_bytes(split_index),
        "membership.json": _json_bytes(membership),
        "teacher-identity.json": _json_bytes(teacher_identity),
        "reports.json": _json_bytes(reports),
    }
    for name, content in base_files.items():
        _write(output_dir / name, content, ignored=ignored_output)
    source_hashes = {
        name: sha256_file(output_dir / name)
        for name in ("packets.jsonl", "supervision.jsonl", "pairs.jsonl", "membership.json")
    }
    bundle = build_train_only_smoke_bundle(
        packets,
        supervision,
        pairs,
        dataset_revision=dataset_revision,
        source_hashes=source_hashes,
    )
    validate_train_only_smoke_bundle(bundle, repo_root=REPO_ROOT)
    _write(
        output_dir / "train-only-smoke-bundle.json",
        _json_bytes(bundle),
        ignored=ignored_output,
    )
    _write(
        output_dir / "DATA_CARD.md",
        _data_card(dataset_revision, args.mode, statistics, teacher_identity, reports).encode("utf-8"),
        ignored=ignored_output,
    )

    contracts = _contract_hashes(args.teacher_freeze)
    relative_paths = sorted(path.name for path in output_dir.iterdir())
    manifest = build_freeze_manifest(
        output_dir,
        relative_paths,
        dataset_revision=dataset_revision,
        input_identity=design_lock["input_identity"],
        design_lock_sha256=sha256_file(DESIGN_LOCK_PATH),
        generation_commit=args.generation_commit,
        contracts=contracts,
        statistics=statistics,
    )
    _write(output_dir / "manifest.json", _json_bytes(manifest), ignored=ignored_output)
    verify_freeze_manifest(
        output_dir,
        manifest,
        expected_input_identity=design_lock["input_identity"],
    )
    frozen_consumer = DatasetConsumer.from_frozen_directory(
        output_dir,
        expected_input_identity=design_lock["input_identity"],
        repo_root=REPO_ROOT,
    )
    frozen_consumer.stage("C3")
    return {
        "schema": "rondo-publication-critic-plan059-finalizer-result-v1",
        "mode": args.mode,
        "output_dir": str(output_dir),
        "manifest_content_sha256": manifest["content_sha256"],
        "statistics": statistics,
        "near_duplicate_edges": len(near_edges),
        "plan054_reference_matches": len(reference_matches),
        "coverage_failures": list(failures),
        "consumer": reports["consumer"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("rehearsal", "formal"), required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tokenizer-snapshot", type=Path, required=True)
    parser.add_argument("--generation-commit", required=True)
    parser.add_argument("--teacher-freeze", type=Path)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if len(args.generation_commit) != 40 or any(
        character not in "0123456789abcdef" for character in args.generation_commit
    ):
        raise TrainingDataError("generation commit must be a full lowercase Git SHA")
    if args.teacher_freeze is not None:
        args.teacher_freeze = args.teacher_freeze.resolve()
        if REPO_ROOT not in args.teacher_freeze.parents or not args.teacher_freeze.is_file():
            raise TrainingDataError("teacher freeze must be a tracked file in this repository")
    result = finalize(args)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
