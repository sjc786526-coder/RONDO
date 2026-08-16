"""Offline, fail-closed preparation for the Local M4 three-way blind review.

This module never calls a model or reads runtime configuration.  It freezes the
tracked synthetic validation cohort, validates a complete three-side import,
builds private anonymous judge packages, validates point-in-time judge results,
and aggregates facts after private unblinding.  Synthetic-body and holdout-anchor
partitions are deliberately separate and can never be aggregated together.
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import stat
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..config import ConfigError, RepoPaths
from ..evidence import (
    STATIC_DECISION_SCHEMA,
    STATIC_DECISION_SCHEMA_NAME,
    STATIC_PAYLOAD_SCHEMA_VERSION,
    EvidenceError,
    PolicyIdentity,
    StaticApprovalPayload,
    validate_static_decision,
    validate_static_payload,
)
from . import synthetic_training


COHORT_SCHEMA_VERSION = 1
COHORT_CONTRACT_VERSION = "rondo_m4_synthetic_cohort_v1"
COHORT_ID = "m4-synthetic-body-v1"
COHORT_STATUS = "waiting_for_l6_outputs"
BATCH_ASSIGNMENT_VERSION = "category_outcome_stratified_group_union_greedy_v1"
CANONICAL_JSON_VERSION = "utf8_sorted_keys_compact_no_nan_v1"
APPROVAL_IDENTITY_VERSION = "static_v3_prompt_messages_output_schema_sha256_v1"
IMPORT_SCHEMA_VERSION = 1
IMPORT_CONTRACT_VERSION = "rondo_m4_three_side_import_v1"
TERMINAL_IMPORT_SCHEMA_VERSION = 2
TERMINAL_IMPORT_CONTRACT_VERSION = "rondo_m4_three_side_import_v2"
OUTPUT_TERMINAL_SCHEMA_VERSION = 1
OUTPUT_TERMINAL_CONTRACT_VERSION = "rondo_l6_output_terminal_v1"
OUTPUT_TERMINAL_STATUSES = (
    "decision",
    "structured_output_failure",
    "refusal",
    "timeout",
)
INFRASTRUCTURE_TERMINAL_SCHEMA_VERSION = 2
INFRASTRUCTURE_TERMINAL_CONTRACT_VERSION = "rondo_l6_output_terminal_v2"
INFRASTRUCTURE_TERMINAL_STATUS = "infrastructure_failure"
LOCAL_PAIR_CONTRACT_VERSION = "rondo_l6_paired_attribution_v1"
LOCAL_PAIR_RECEIPT_SCHEMA_VERSION = 1
LOCAL_PAIR_RECEIPT_CONTRACT_VERSION = "rondo_l6_m4_pair_receipt_v1"
PACKAGE_SCHEMA_VERSION = 1
PACKAGE_CONTRACT_VERSION = "rondo_m4_blind_package_v1"
ANONYMOUS_TERMINAL_SCHEMA_VERSION = 1
ANONYMOUS_TERMINAL_CONTRACT_VERSION = "rondo_m4_anonymous_terminal_projection_v1"
MAPPING_SCHEMA_VERSION = 1
MAPPING_CONTRACT_VERSION = "rondo_m4_private_blind_mapping_v1"
REQUEST_SCHEMA_VERSION = 1
REQUEST_CONTRACT_VERSION = "rondo_m4_judge_request_v1"
BLINDING_ALGORITHM_VERSION = "sha256_ranked_balanced_latin_square_v1"
JUDGE_PROMPT_VERSION = "rondo_m4_cross_eval_judge_v1"
JUDGE_RESULT_SCHEMA_VERSION = 1
JUDGE_RESULT_CONTRACT_VERSION = "rondo_m4_judge_result_v1"
UNBLINDED_SCHEMA_VERSION = 1
UNBLINDED_CONTRACT_VERSION = "rondo_m4_private_unblinded_v1"
AGGREGATE_SCHEMA_VERSION = 1
AGGREGATE_CONTRACT_VERSION = "rondo_m4_partition_aggregate_v1"
HOLDOUT_PRIVATE_CONTRACT_VERSION = "rondo_m4_holdout_anchor_private_v1"
HOLDOUT_PUBLIC_CONTRACT_VERSION = "rondo_m4_holdout_batch_summary_v1"

COHORT_RELATIVE_PATH = "eval/locks/local-approval-m4-synthetic-cohort-v1.json"
DATASET_DIRECTORY = "training/local-approval-synthetic-v1"
DATASET_MANIFEST_RELATIVE_PATH = f"{DATASET_DIRECTORY}/manifest.json"
VALIDATION_RELATIVE_PATH = f"{DATASET_DIRECTORY}/validation.jsonl"
JUDGE_PROMPT_RELATIVE_PATH = (
    "eval/templates/cross-eval-judge/local-m4-judge-prompt-v1.md"
)
SIDE_OUTPUT_SCHEMA_RELATIVE_PATH = (
    "eval/templates/cross-eval-judge/local-m4-side-output-v1.schema.json"
)
JUDGE_RESULT_SCHEMA_RELATIVE_PATH = (
    "eval/templates/cross-eval-judge/local-m4-judge-result-v1.schema.json"
)
BLINDING_CONTRACT_RELATIVE_PATH = (
    "eval/templates/cross-eval-judge/local-m4-blinding-contract-v1.json"
)
HOLDOUT_SUMMARY_SCHEMA_RELATIVE_PATH = (
    "eval/templates/cross-eval-judge/local-m4-holdout-summary-v1.schema.json"
)
LOCAL_PAIR_RECEIPT_SCHEMA_RELATIVE_PATH = (
    "eval/templates/cross-eval-judge/local-m4-l6-pair-receipt-v1.schema.json"
)

PARTITIONS = ("synthetic", "holdout")
SIDES = ("sol-static", "local-static", "local-ft-static")
CANDIDATES = ("candidate-a", "candidate-b", "candidate-c")
MAX_BATCH_SAMPLES = 100
SYNTHETIC_SAMPLE_COUNT = 130
SYNTHETIC_BATCH_COUNT = 2

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,95}\Z")
_L6_PAIR_ID = re.compile(r"l6-[a-z0-9][a-z0-9-]{0,92}\Z")
_UNAMBIGUOUS_SIDE_TOKEN = re.compile(r"\b(?:sol|ft)\b", re.IGNORECASE)
_LOCAL_TOKEN = re.compile(r"\blocal\b", re.IGNORECASE)
_SAFE_LOCAL_SEMANTIC_USE = re.compile(
    r"\blocal(?:-|\s+)(?:"
    r"workspace|module|reset|backup|file|path|directory|repository|repo|branch|"
    r"machine|host|service|process|port|environment|operation|command|change|"
    r"build|test|cache|copy|checkout|tree|state|data|evidence|scope|sandbox|"
    r"endpoint|network|disk|filesystem|installation|configuration|config|package|"
    r"dependency|database|server|client|account|user|resource|validation"
    r")\b",
    re.IGNORECASE,
)
_SIDE_IDENTITY_CONTEXT = re.compile(
    r"(?:\b(?:candidate|answer|output|response|identity|side|model)\b.{0,32}"
    r"\b(?:sol|local|ft)\b"
    r"|\b(?:sol|local|ft)\b.{0,32}"
    r"\b(?:candidate|answer|output|response|identity|side|model|checkpoint|adapter)\b"
    r"|\b(?:generated|produced|written)\s+by\s+(?:sol|local|ft)\b"
    r"|\b(?:from|by)\s+(?:sol|local|ft)\b"
    r"|\b(?:identity|side)\s*[:=]\s*(?:sol|local|ft)\b)",
    re.IGNORECASE,
)
_MODEL_PATH_MARKER = re.compile(
    r"(?:[/\\](?:models?|checkpoints?|adapters?|weights?)[/\\]"
    r"|(?:^|\s)[^\s/\\]+\.(?:gguf|safetensors|ckpt|pt|pth)(?:\b|$))",
    re.IGNORECASE,
)
_MAX_TRACKED_BYTES = 8 * 1024 * 1024
_MAX_PRIVATE_BYTES = 40 * 1024 * 1024


class CrossEvalError(RuntimeError):
    """Body-free, stable failure from the offline M4 boundary."""

    def __init__(self, code: str, facts: Mapping[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.facts = dict(facts or {})


@dataclass(frozen=True)
class TemplateIdentity:
    judge_prompt_sha256: str
    side_output_schema_sha256: str
    judge_result_schema_sha256: str
    blinding_contract_sha256: str
    holdout_summary_schema_sha256: str
    local_pair_receipt_schema_sha256: str


@dataclass(frozen=True)
class CohortBundle:
    partition: str
    manifest: dict[str, Any]
    manifest_sha256: str
    source_rows: dict[str, dict[str, Any]]


@dataclass(frozen=True, init=False)
class FormalL6PairEvidence:
    """A source-validated Plan 037 receipt capability.

    The generic v1 receipt remains a legacy shape contract.  Formal v2 rows
    require this capability, which the paired-output boundary creates only
    after re-reading the frozen model/runtime contracts, completed formal
    training receipt, and actual artifacts.
    """

    receipt: dict[str, Any]

    def __new__(cls) -> FormalL6PairEvidence:
        raise TypeError("FormalL6PairEvidence requires source validation")

    @classmethod
    def _from_source_validation(
        cls, receipt: Mapping[str, Any]
    ) -> FormalL6PairEvidence:
        instance = object.__new__(cls)
        object.__setattr__(instance, "receipt", copy.deepcopy(dict(receipt)))
        return instance


@dataclass(frozen=True)
class BlindBatch:
    package: dict[str, Any]
    package_raw: bytes
    mapping: dict[str, Any]
    request: dict[str, Any]


@dataclass(frozen=True)
class AnonymousTerminalBatch:
    """A blind, pre-judge projection that can honestly carry absent decisions."""

    package: dict[str, Any]
    package_raw: bytes
    mapping: dict[str, Any]


def _canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CrossEvalError("json_canonicalization_failed") from exc


def _json_file_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                indent=2,
                sort_keys=True,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise CrossEvalError("json_serialization_failed") from exc


def _jsonl_bytes(values: Iterable[Any]) -> bytes:
    return b"".join(_canonical_bytes(value) + b"\n" for value in values)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_sha256(value: Any) -> str:
    return _sha256(_canonical_bytes(value))


def _validate_date(value: Any) -> None:
    try:
        parsed = dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise CrossEvalError("date_invalid") from exc
    if parsed.isoformat() != value:
        raise CrossEvalError("date_invalid")


def _safe_read(path: Path, *, private: bool) -> bytes:
    limit = _MAX_PRIVATE_BYTES if private else _MAX_TRACKED_BYTES
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise CrossEvalError("file_missing") from exc
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_ISLNK(before.st_mode)
        or before.st_size <= 0
        or before.st_size > limit
        or (private and stat.S_IMODE(before.st_mode) != 0o600)
    ):
        raise CrossEvalError("file_contract_invalid")
    try:
        raw = path.read_bytes()
        after = os.lstat(path)
    except OSError as exc:
        raise CrossEvalError("file_read_failed") from exc
    identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
    if identity(before) != identity(after) or len(raw) != before.st_size:
        raise CrossEvalError("file_changed_while_reading")
    return raw


def _load_json(path: Path, *, private: bool) -> tuple[Any, bytes]:
    raw = _safe_read(path, private=private)
    try:
        return json.loads(raw.decode("utf-8")), raw
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CrossEvalError("json_file_invalid") from exc


def _load_jsonl(path: Path, *, private: bool) -> tuple[list[Any], bytes]:
    raw = _safe_read(path, private=private)
    try:
        lines = raw.decode("utf-8").splitlines()
        if not lines or any(not line.strip() for line in lines):
            raise CrossEvalError("jsonl_shape_invalid")
        return [json.loads(line) for line in lines], raw
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise CrossEvalError("jsonl_invalid") from exc


def _require_private_directory(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise CrossEvalError("private_directory_missing") from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise CrossEvalError("private_directory_invalid")


def _write_exclusive(path: Path, raw: bytes, *, mode: int) -> None:
    if path.exists() or path.is_symlink():
        raise CrossEvalError("output_already_exists")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("write did not progress")
            view = view[written:]
        os.fsync(descriptor)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def load_template_identity(worktree_root: Path) -> TemplateIdentity:
    paths = (
        JUDGE_PROMPT_RELATIVE_PATH,
        SIDE_OUTPUT_SCHEMA_RELATIVE_PATH,
        JUDGE_RESULT_SCHEMA_RELATIVE_PATH,
        BLINDING_CONTRACT_RELATIVE_PATH,
        HOLDOUT_SUMMARY_SCHEMA_RELATIVE_PATH,
        LOCAL_PAIR_RECEIPT_SCHEMA_RELATIVE_PATH,
    )
    hashes = [_sha256(_safe_read(worktree_root / path, private=False)) for path in paths]
    return TemplateIdentity(*hashes)


def _approval_identities(payload: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(payload, Mapping):
        raise CrossEvalError("approval_input_invalid")
    try:
        policy = payload.get("guardian_policy")
        if not isinstance(policy, str) or not policy:
            raise EvidenceError("policy invalid")
        logical = copy.deepcopy(dict(payload))
        static = StaticApprovalPayload(
            PolicyIdentity(
                STATIC_PAYLOAD_SCHEMA_VERSION,
                "responses_lite",
                _sha256(policy.encode("utf-8")),
                "known",
            ),
            _canonical_bytes(logical),
            logical,
        )
        validate_static_payload(static)
    except EvidenceError as exc:
        raise CrossEvalError("approval_input_invalid") from exc
    return {
        "payload_sha256": _canonical_sha256(logical),
        "approval_prompt_sha256": _canonical_sha256(
            {
                "instructions": logical["instructions"],
                "guardian_policy": logical["guardian_policy"],
            }
        ),
        "message_sequence_sha256": _canonical_sha256(logical["input"]),
        "output_schema_sha256": _canonical_sha256(logical["output_schema"]),
    }


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, value: int) -> int:
        while self.parent[value] != value:
            self.parent[value] = self.parent[self.parent[value]]
            value = self.parent[value]
        return value

    def union(self, left: int, right: int) -> None:
        first, second = self.find(left), self.find(right)
        if first != second:
            self.parent[max(first, second)] = min(first, second)


def assign_body_batches(
    rows: Sequence[Mapping[str, Any]], *, max_batch_samples: int = MAX_BATCH_SAMPLES
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """Assign the union of source and near-duplicate groups to two stable batches."""

    if not rows or max_batch_samples <= 0:
        raise CrossEvalError("batch_input_invalid")
    sample_ids = [row.get("sample_id") for row in rows]
    if any(not isinstance(value, str) or _HEX64.fullmatch(value) is None for value in sample_ids):
        raise CrossEvalError("sample_identity_invalid")
    if len(sample_ids) != len(set(sample_ids)):
        raise CrossEvalError("sample_identity_duplicate")
    union = _UnionFind(len(rows))
    seen_group: dict[tuple[str, str], int] = {}
    for index, row in enumerate(rows):
        for field in ("group_id", "split_group_id"):
            value = row.get(field)
            pattern = _ID if field == "group_id" else _HEX64
            if not isinstance(value, str) or pattern.fullmatch(value) is None:
                raise CrossEvalError("cohort_group_invalid")
            key = (field, value)
            if key in seen_group:
                union.union(index, seen_group[key])
            else:
                seen_group[key] = index
    components: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for index, row in enumerate(rows):
        components[union.find(index)].append(row)
    if any(len(component) > max_batch_samples for component in components.values()):
        raise CrossEvalError("cohort_group_exceeds_batch_limit")

    grouped: dict[tuple[Any, ...], list[tuple[str, list[Mapping[str, Any]]]]] = defaultdict(list)
    for component in components.values():
        distribution = tuple(
            sorted(
                Counter(
                    (row.get("category"), row.get("target", {}).get("outcome"))
                    for row in component
                ).items()
            )
        )
        if any(
            not isinstance(category, str) or outcome not in {"allow", "deny"}
            for (category, outcome), _count in distribution
        ):
            raise CrossEvalError("cohort_stratum_invalid")
        component_id = _canonical_sha256(sorted(row["sample_id"] for row in component))
        grouped[distribution].append((component_id, component))

    batch_ids = ("synthetic-body-b01", "synthetic-body-b02")
    totals = [0, 0]
    stratum_totals: list[Counter[tuple[Any, ...]]] = [Counter(), Counter()]
    mapping: dict[str, str] = {}
    component_counts = [0, 0]
    for stratum in sorted(grouped, key=_canonical_bytes):
        for _component_id, component in sorted(grouped[stratum], key=lambda item: item[0]):
            size = len(component)
            candidates = [index for index in range(2) if totals[index] + size <= max_batch_samples]
            if not candidates:
                raise CrossEvalError("batch_limit_unsatisfied")
            selected = min(
                candidates,
                key=lambda index: (stratum_totals[index][stratum], totals[index], index),
            )
            totals[selected] += size
            stratum_totals[selected][stratum] += size
            component_counts[selected] += 1
            for row in component:
                mapping[row["sample_id"]] = batch_ids[selected]
    if len(mapping) != len(rows):
        raise CrossEvalError("batch_coverage_invalid")
    batches = [
        {
            "batch_id": batch_ids[index],
            "sample_count": totals[index],
            "group_union_count": component_counts[index],
        }
        for index in range(2)
    ]
    return mapping, batches


def _validate_source_manifest(manifest: Any, manifest_raw: bytes, validation_raw: bytes) -> None:
    if not isinstance(manifest, dict):
        raise CrossEvalError("source_manifest_invalid")
    try:
        valid = (
            manifest["schema_version"] == 1
            and manifest["batch_id"] == synthetic_training.SYNTHETIC_BATCH_ID
            and manifest["status"] == "ready_for_l6"
            and manifest["statistics"]["final_samples"] == 600
            and manifest["statistics"]["splits"] == {"train": 470, "validation": 130}
            and manifest["files"]["validation.jsonl"]["bytes"] == len(validation_raw)
            and manifest["files"]["validation.jsonl"]["sha256"] == _sha256(validation_raw)
            and manifest["contracts"]["static_payload_schema_version"]
            == STATIC_PAYLOAD_SCHEMA_VERSION
            and manifest["contracts"]["static_decision_schema_name"]
            == STATIC_DECISION_SCHEMA_NAME
        )
    except (KeyError, TypeError):
        valid = False
    if not valid or not manifest_raw.endswith(b"\n"):
        raise CrossEvalError("source_manifest_invalid")


def load_synthetic_source(worktree_root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    manifest, manifest_raw = _load_json(
        worktree_root / DATASET_MANIFEST_RELATIVE_PATH, private=False
    )
    rows, validation_raw = _load_jsonl(
        worktree_root / VALIDATION_RELATIVE_PATH, private=False
    )
    _validate_source_manifest(manifest, manifest_raw, validation_raw)
    if len(rows) != SYNTHETIC_SAMPLE_COUNT:
        raise CrossEvalError("source_validation_count_invalid")
    validated: list[dict[str, Any]] = []
    for row in rows:
        try:
            accepted = synthetic_training.validate_candidate(
                row,
                batch_id=manifest["batch_id"],
                generated_date=manifest["generator"]["generated_date"],
                prompt_sha256=manifest["contracts"]["prompt_sha256"],
                final=True,
            )
        except synthetic_training.SyntheticTrainingError as exc:
            raise CrossEvalError("source_validation_row_invalid") from exc
        if accepted["split"] != "validation":
            raise CrossEvalError("source_train_row_forbidden")
        validated.append(copy.deepcopy(accepted))
    sample_ids = [row["sample_id"] for row in validated]
    payloads = [row["payload_sha256"] for row in validated]
    if len(sample_ids) != len(set(sample_ids)) or len(payloads) != len(set(payloads)):
        raise CrossEvalError("source_validation_identity_duplicate")
    source = {
        "dataset_manifest_raw": manifest_raw,
        "validation_raw": validation_raw,
        "dataset_manifest": manifest,
    }
    return validated, source


def _build_cohort_manifest(
    *,
    rows: Sequence[dict[str, Any]],
    source: Mapping[str, Any],
    templates: TemplateIdentity,
) -> dict[str, Any]:
    assignments, batches = assign_body_batches(rows)
    identities = [_approval_identities(row["input"]) for row in rows]
    approval_prompts = {item["approval_prompt_sha256"] for item in identities}
    output_schemas = {item["output_schema_sha256"] for item in identities}
    if len(approval_prompts) != 1 or len(output_schemas) != 1:
        raise CrossEvalError("source_approval_contract_not_uniform")
    items = []
    for row, identity in sorted(zip(rows, identities), key=lambda pair: pair[0]["sample_id"]):
        if identity["payload_sha256"] != row["payload_sha256"]:
            raise CrossEvalError("source_payload_identity_invalid")
        items.append(
            {
                "sample_id": row["sample_id"],
                "payload_sha256": row["payload_sha256"],
                "target_sha256": _canonical_sha256(row["target"]),
                "source_group_sha256": _sha256(row["group_id"].encode("utf-8")),
                "split_group_id": row["split_group_id"],
                "body_batch_id": assignments[row["sample_id"]],
                "approval_prompt_sha256": identity["approval_prompt_sha256"],
                "message_sequence_sha256": identity["message_sequence_sha256"],
                "output_schema_sha256": identity["output_schema_sha256"],
            }
        )
    manifest = source["dataset_manifest"]
    return {
        "schema_version": COHORT_SCHEMA_VERSION,
        "contract_version": COHORT_CONTRACT_VERSION,
        "cohort_id": COHORT_ID,
        "partition": "synthetic",
        "purpose": "Local M4 synthetic validation body cohort",
        "status": COHORT_STATUS,
        "source": {
            "dataset_batch_id": manifest["batch_id"],
            "dataset_manifest_relative_path": DATASET_MANIFEST_RELATIVE_PATH,
            "dataset_manifest_sha256": _sha256(source["dataset_manifest_raw"]),
            "validation_relative_path": VALIDATION_RELATIVE_PATH,
            "validation_sha256": _sha256(source["validation_raw"]),
            "validation_bytes": len(source["validation_raw"]),
            "validation_samples": len(rows),
            "source_generation_prompt_version": manifest["contracts"]["prompt_version"],
            "source_generation_prompt_sha256": manifest["contracts"]["prompt_sha256"],
            "sample_schema_version": manifest["contracts"]["sample_schema_version"],
            "sample_schema_sha256": manifest["contracts"]["sample_schema_sha256"],
            "split": "validation",
            "training_samples_included": False,
        },
        "contracts": {
            "canonical_json_version": CANONICAL_JSON_VERSION,
            "approval_identity_version": APPROVAL_IDENTITY_VERSION,
            "static_payload_schema_version": STATIC_PAYLOAD_SCHEMA_VERSION,
            "static_decision_schema_name": STATIC_DECISION_SCHEMA_NAME,
            "approval_prompt_sha256": next(iter(approval_prompts)),
            "output_schema_sha256": next(iter(output_schemas)),
            "three_side_import_contract_version": IMPORT_CONTRACT_VERSION,
            "local_pair_contract_version": LOCAL_PAIR_CONTRACT_VERSION,
            "local_pair_receipt_schema_relative_path": LOCAL_PAIR_RECEIPT_SCHEMA_RELATIVE_PATH,
            "local_pair_receipt_schema_sha256": templates.local_pair_receipt_schema_sha256,
            "batch_assignment_version": BATCH_ASSIGNMENT_VERSION,
            "judge_prompt_version": JUDGE_PROMPT_VERSION,
            "judge_prompt_relative_path": JUDGE_PROMPT_RELATIVE_PATH,
            "judge_prompt_sha256": templates.judge_prompt_sha256,
            "side_output_schema_relative_path": SIDE_OUTPUT_SCHEMA_RELATIVE_PATH,
            "side_output_schema_sha256": templates.side_output_schema_sha256,
            "judge_result_schema_version": JUDGE_RESULT_SCHEMA_VERSION,
            "judge_result_schema_relative_path": JUDGE_RESULT_SCHEMA_RELATIVE_PATH,
            "judge_result_schema_sha256": templates.judge_result_schema_sha256,
            "blinding_algorithm_version": BLINDING_ALGORITHM_VERSION,
            "blinding_contract_relative_path": BLINDING_CONTRACT_RELATIVE_PATH,
            "blinding_contract_sha256": templates.blinding_contract_sha256,
            "holdout_summary_schema_relative_path": HOLDOUT_SUMMARY_SCHEMA_RELATIVE_PATH,
            "holdout_summary_schema_sha256": templates.holdout_summary_schema_sha256,
        },
        "batching": {
            "batch_count": SYNTHETIC_BATCH_COUNT,
            "max_batch_samples": MAX_BATCH_SAMPLES,
            "batches": batches,
        },
        "items": items,
        "items_sha256": _canonical_sha256(items),
        "boundaries": {
            "body_free": True,
            "contains_inputs": False,
            "contains_targets": False,
            "contains_outputs": False,
            "contains_blinding_seed_or_mapping": False,
            "formal_m4_started": False,
            "model_quality_claimed": False,
        },
    }


def build_synthetic_cohort_manifest(worktree_root: Path) -> dict[str, Any]:
    rows, source = load_synthetic_source(worktree_root)
    templates = load_template_identity(worktree_root)
    return _build_cohort_manifest(rows=rows, source=source, templates=templates)


def freeze_synthetic_cohort(worktree_root: Path) -> dict[str, Any]:
    manifest = build_synthetic_cohort_manifest(worktree_root)
    path = worktree_root / COHORT_RELATIVE_PATH
    expected_raw = _json_file_bytes(manifest)
    if path.exists() or path.is_symlink():
        if _safe_read(path, private=False) != expected_raw:
            raise CrossEvalError("cohort_manifest_drift")
    else:
        _write_exclusive(path, expected_raw, mode=0o644)
    return {
        "status": manifest["status"],
        "cohort_id": manifest["cohort_id"],
        "sample_count": len(manifest["items"]),
        "batches": {
            item["batch_id"]: item["sample_count"]
            for item in manifest["batching"]["batches"]
        },
        "cohort_manifest_sha256": _sha256(expected_raw),
    }


def load_synthetic_bundle(worktree_root: Path) -> CohortBundle:
    tracked, raw = _load_json(worktree_root / COHORT_RELATIVE_PATH, private=False)
    expected = build_synthetic_cohort_manifest(worktree_root)
    if tracked != expected or raw != _json_file_bytes(expected):
        raise CrossEvalError("cohort_manifest_drift")
    rows, _source = load_synthetic_source(worktree_root)
    return CohortBundle(
        "synthetic",
        expected,
        _sha256(raw),
        {row["sample_id"]: row for row in rows},
    )


def preflight_synthetic_cohort(worktree_root: Path) -> dict[str, Any]:
    bundle = load_synthetic_bundle(worktree_root)
    return {
        "status": COHORT_STATUS,
        "cohort_id": bundle.manifest["cohort_id"],
        "cohort_manifest_sha256": bundle.manifest_sha256,
        "sample_count": len(bundle.manifest["items"]),
        "source_group_count": len(
            {item["source_group_sha256"] for item in bundle.manifest["items"]}
        ),
        "split_group_count": len(
            {item["split_group_id"] for item in bundle.manifest["items"]}
        ),
        "batches": {
            item["batch_id"]: item["sample_count"]
            for item in bundle.manifest["batching"]["batches"]
        },
        "models_called": 0,
        "fake_local_outputs_created": 0,
        "formal_m4_started": False,
    }


def _validate_local_run_contract(value: Any, *, side: str) -> dict[str, Any]:
    fields = {
        "contract_version",
        "provenance",
        "source_work_package",
        "pair_id",
        "pair_receipt_sha256",
        "base_model_identity_sha256",
        "runtime_identity_sha256",
        "chat_template_sha256",
        "request_contract_sha256",
        "sampling_contract",
        "output_contract_sha256",
        "model_artifact_sha256",
        "training_receipt_sha256",
        "blind_identity_markers",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise CrossEvalError("local_run_contract_fields_invalid")
    expected_provenance = (
        "l6_paired_unfinetuned" if side == "local-static" else "l6_paired_finetuned"
    )
    if (
        value["contract_version"] != LOCAL_PAIR_CONTRACT_VERSION
        or value["provenance"] != expected_provenance
        or value["source_work_package"] != "L6"
        or not isinstance(value["pair_id"], str)
        or _L6_PAIR_ID.fullmatch(value["pair_id"]) is None
    ):
        raise CrossEvalError("local_run_provenance_invalid")
    hex_fields = (
        "pair_receipt_sha256",
        "base_model_identity_sha256",
        "runtime_identity_sha256",
        "chat_template_sha256",
        "request_contract_sha256",
        "output_contract_sha256",
        "model_artifact_sha256",
    )
    if any(
        not isinstance(value[field], str) or _HEX64.fullmatch(value[field]) is None
        for field in hex_fields
    ):
        raise CrossEvalError("local_run_identity_invalid")
    sampling = value["sampling_contract"]
    if not isinstance(sampling, dict) or set(sampling) != {
        "context_size",
        "max_output_tokens",
        "temperature",
        "top_p",
        "seed",
    }:
        raise CrossEvalError("local_sampling_contract_invalid")
    if (
        not isinstance(sampling["context_size"], int)
        or isinstance(sampling["context_size"], bool)
        or sampling["context_size"] <= 0
        or not isinstance(sampling["max_output_tokens"], int)
        or isinstance(sampling["max_output_tokens"], bool)
        or sampling["max_output_tokens"] <= 0
        or not isinstance(sampling["temperature"], (int, float))
        or isinstance(sampling["temperature"], bool)
        or not isinstance(sampling["top_p"], (int, float))
        or isinstance(sampling["top_p"], bool)
        or not isinstance(sampling["seed"], int)
        or isinstance(sampling["seed"], bool)
    ):
        raise CrossEvalError("local_sampling_contract_invalid")
    training_receipt = value["training_receipt_sha256"]
    if side == "local-static":
        if training_receipt is not None:
            raise CrossEvalError("unfinetuned_training_receipt_forbidden")
    elif not isinstance(training_receipt, str) or _HEX64.fullmatch(training_receipt) is None:
        raise CrossEvalError("finetuned_training_receipt_invalid")
    markers = value["blind_identity_markers"]
    if (
        not isinstance(markers, list)
        or not markers
        or len(markers) > 32
        or len(markers) != len(set(markers))
        or any(
            not isinstance(marker, str)
            or len(marker.strip()) < 3
            or len(marker) > 512
            for marker in markers
        )
    ):
        raise CrossEvalError("local_blind_identity_markers_invalid")
    return copy.deepcopy(value)


def validate_l6_pair_receipt(
    value: Any, *, raw: bytes | None = None
) -> tuple[dict[str, Any], str, dict[str, dict[str, Any]]]:
    fields = {
        "schema_version",
        "contract_version",
        "source_work_package",
        "pair_id",
        "base_model_identity_sha256",
        "shared_contract",
        "artifacts",
        "blind_identity_markers",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise CrossEvalError("l6_pair_receipt_fields_invalid")
    if (
        value["schema_version"] != LOCAL_PAIR_RECEIPT_SCHEMA_VERSION
        or value["contract_version"] != LOCAL_PAIR_RECEIPT_CONTRACT_VERSION
        or value["source_work_package"] != "L6"
        or not isinstance(value["pair_id"], str)
        or _L6_PAIR_ID.fullmatch(value["pair_id"]) is None
        or not isinstance(value["base_model_identity_sha256"], str)
        or _HEX64.fullmatch(value["base_model_identity_sha256"]) is None
    ):
        raise CrossEvalError("l6_pair_receipt_identity_invalid")
    shared = value["shared_contract"]
    if not isinstance(shared, dict) or set(shared) != {
        "runtime_identity_sha256",
        "chat_template_sha256",
        "request_contract_sha256",
        "sampling_contract",
        "output_contract_sha256",
    }:
        raise CrossEvalError("l6_pair_receipt_shared_contract_invalid")
    for field in (
        "runtime_identity_sha256",
        "chat_template_sha256",
        "request_contract_sha256",
        "output_contract_sha256",
    ):
        if not isinstance(shared[field], str) or _HEX64.fullmatch(shared[field]) is None:
            raise CrossEvalError("l6_pair_receipt_shared_contract_invalid")
    if shared["output_contract_sha256"] != _canonical_sha256(STATIC_DECISION_SCHEMA):
        raise CrossEvalError("l6_pair_receipt_output_contract_invalid")
    artifacts = value["artifacts"]
    if not isinstance(artifacts, dict) or set(artifacts) != {
        "local-static",
        "local-ft-static",
    }:
        raise CrossEvalError("l6_pair_receipt_artifacts_invalid")
    markers = value["blind_identity_markers"]
    canonical_raw = _json_file_bytes(value)
    if raw is not None and raw != canonical_raw:
        raise CrossEvalError("l6_pair_receipt_serialization_invalid")
    receipt_sha256 = _sha256(canonical_raw)
    expected_contracts: dict[str, dict[str, Any]] = {}
    for side in ("local-static", "local-ft-static"):
        artifact = artifacts[side]
        expected_provenance = (
            "l6_paired_unfinetuned"
            if side == "local-static"
            else "l6_paired_finetuned"
        )
        if not isinstance(artifact, dict) or set(artifact) != {
            "provenance",
            "model_artifact_sha256",
            "training_receipt_sha256",
        }:
            raise CrossEvalError("l6_pair_receipt_artifacts_invalid")
        if artifact["provenance"] != expected_provenance:
            raise CrossEvalError("l6_pair_receipt_artifacts_invalid")
        contract = {
            "contract_version": LOCAL_PAIR_CONTRACT_VERSION,
            "provenance": artifact["provenance"],
            "source_work_package": "L6",
            "pair_id": value["pair_id"],
            "pair_receipt_sha256": receipt_sha256,
            "base_model_identity_sha256": value["base_model_identity_sha256"],
            "runtime_identity_sha256": shared["runtime_identity_sha256"],
            "chat_template_sha256": shared["chat_template_sha256"],
            "request_contract_sha256": shared["request_contract_sha256"],
            "sampling_contract": copy.deepcopy(shared["sampling_contract"]),
            "output_contract_sha256": shared["output_contract_sha256"],
            "model_artifact_sha256": artifact["model_artifact_sha256"],
            "training_receipt_sha256": artifact["training_receipt_sha256"],
            "blind_identity_markers": copy.deepcopy(markers),
        }
        expected_contracts[side] = _validate_local_run_contract(contract, side=side)
    if (
        expected_contracts["local-static"]["model_artifact_sha256"]
        == expected_contracts["local-ft-static"]["model_artifact_sha256"]
    ):
        raise CrossEvalError("l6_pair_receipt_artifacts_not_distinct")
    return copy.deepcopy(value), receipt_sha256, expected_contracts


def _validate_sol_run_contract(
    value: Any, *, source_row: Mapping[str, Any], bundle: CohortBundle
) -> dict[str, Any]:
    source_cohort_sha256 = (
        bundle.manifest["source"]["validation_sha256"]
        if bundle.partition == "synthetic"
        else bundle.manifest["source"]["private_source_sha256"]
    )
    expected = {
        "contract_version": IMPORT_CONTRACT_VERSION,
        "provenance": "frozen_validation_target",
        "source_dataset_batch_id": source_row["batch_id"],
        "source_generation_model": source_row["generator_model"],
        "source_generated_date": source_row["generated_date"],
        "source_generation_prompt_version": source_row["prompt_version"],
        "source_generation_prompt_sha256": source_row["prompt_sha256"],
        "source_cohort_sha256": source_cohort_sha256,
    }
    if value != expected:
        raise CrossEvalError("sol_target_provenance_invalid")
    return copy.deepcopy(expected)


def validate_output_terminal(value: Any) -> dict[str, Any]:
    """Validate one honest, versioned per-sample terminal outcome.

    Only the ``decision`` variant is allowed to carry a decision.  Failures,
    refusals, and timeouts carry a stable body-free code instead, so callers
    cannot silently convert absence of a compliant model output into ``deny``.
    """

    if not isinstance(value, dict):
        raise CrossEvalError("output_terminal_invalid")
    common = {
        "schema_version",
        "contract_version",
        "status",
    }
    status = value.get("status")
    accepted = copy.deepcopy(value)
    is_v1 = (
        value.get("schema_version") == OUTPUT_TERMINAL_SCHEMA_VERSION
        and value.get("contract_version") == OUTPUT_TERMINAL_CONTRACT_VERSION
        and status in OUTPUT_TERMINAL_STATUSES
    )
    is_infrastructure_v2 = (
        value.get("schema_version") == INFRASTRUCTURE_TERMINAL_SCHEMA_VERSION
        and value.get("contract_version")
        == INFRASTRUCTURE_TERMINAL_CONTRACT_VERSION
        and status == INFRASTRUCTURE_TERMINAL_STATUS
    )
    if not is_v1 and not is_infrastructure_v2:
        raise CrossEvalError("output_terminal_invalid")
    if is_v1 and status == "decision":
        if set(value) != common | {"decision"}:
            raise CrossEvalError("output_terminal_fields_invalid")
        try:
            accepted["decision"] = validate_static_decision(value["decision"])
        except EvidenceError as exc:
            raise CrossEvalError("output_terminal_decision_invalid") from exc
        return accepted
    if set(value) != common | {"failure_code"}:
        raise CrossEvalError("output_terminal_fields_invalid")
    code = value.get("failure_code")
    if (
        not isinstance(code, str)
        or _ID.fullmatch(code) is None
        or len(code) > 64
    ):
        raise CrossEvalError("output_terminal_failure_code_invalid")
    return accepted


def _row_terminal(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return the terminal projection without changing accepted v1 rows."""

    if "terminal" in row:
        return validate_output_terminal(row["terminal"])
    try:
        decision = validate_static_decision(row["decision"])
    except (KeyError, EvidenceError) as exc:
        raise CrossEvalError("side_output_terminal_missing") from exc
    return {
        "schema_version": OUTPUT_TERMINAL_SCHEMA_VERSION,
        "contract_version": OUTPUT_TERMINAL_CONTRACT_VERSION,
        "status": "decision",
        "decision": decision,
    }


def _row_decision(row: Mapping[str, Any]) -> dict[str, Any]:
    terminal = _row_terminal(row)
    if terminal["status"] != "decision":
        raise CrossEvalError("decision_terminal_required")
    return copy.deepcopy(terminal["decision"])


def _validate_import_row(
    value: Any,
    *,
    bundle: CohortBundle,
    cohort_item: Mapping[str, Any],
    source_row: Mapping[str, Any],
) -> dict[str, Any]:
    v1_fields = {
        "schema_version",
        "contract_version",
        "partition",
        "cohort_id",
        "cohort_manifest_sha256",
        "body_batch_id",
        "sample_id",
        "side",
        "approval_input",
        "payload_sha256",
        "approval_prompt_sha256",
        "message_sequence_sha256",
        "output_schema_sha256",
        "decision",
        "run_contract",
    }
    v2_fields = (v1_fields - {"decision"}) | {"terminal"}
    if not isinstance(value, dict):
        raise CrossEvalError("side_output_fields_invalid")
    is_v1 = (
        value.get("schema_version") == IMPORT_SCHEMA_VERSION
        and value.get("contract_version") == IMPORT_CONTRACT_VERSION
        and set(value) == v1_fields
    )
    is_v2 = (
        value.get("schema_version") == TERMINAL_IMPORT_SCHEMA_VERSION
        and value.get("contract_version") == TERMINAL_IMPORT_CONTRACT_VERSION
        and set(value) == v2_fields
    )
    if not is_v1 and not is_v2:
        raise CrossEvalError("side_output_fields_invalid")
    side = value.get("side")
    if side not in SIDES:
        raise CrossEvalError("side_unknown")
    expected_scalars = {
        "partition": bundle.partition,
        "cohort_id": bundle.manifest["cohort_id"],
        "cohort_manifest_sha256": bundle.manifest_sha256,
        "body_batch_id": cohort_item["body_batch_id"],
        "sample_id": source_row["sample_id"],
        "payload_sha256": source_row["payload_sha256"],
        "approval_prompt_sha256": cohort_item["approval_prompt_sha256"],
        "message_sequence_sha256": cohort_item["message_sequence_sha256"],
        "output_schema_sha256": cohort_item["output_schema_sha256"],
    }
    if any(value.get(key) != expected for key, expected in expected_scalars.items()):
        raise CrossEvalError("side_output_identity_drift")
    identities = _approval_identities(value["approval_input"])
    if (
        _canonical_bytes(value["approval_input"]) != _canonical_bytes(source_row["input"])
        or any(value[key] != identities[key] for key in identities)
    ):
        raise CrossEvalError("side_output_approval_input_drift")
    if is_v1:
        try:
            decision = validate_static_decision(value["decision"])
        except EvidenceError as exc:
            raise CrossEvalError("side_output_decision_invalid") from exc
        terminal = {
            "schema_version": OUTPUT_TERMINAL_SCHEMA_VERSION,
            "contract_version": OUTPUT_TERMINAL_CONTRACT_VERSION,
            "status": "decision",
            "decision": decision,
        }
    else:
        terminal = validate_output_terminal(value["terminal"])
        decision = terminal.get("decision")
    if side == "sol-static":
        if terminal["status"] != "decision":
            raise CrossEvalError("sol_target_terminal_invalid")
        if decision != source_row["target"]:
            raise CrossEvalError("sol_target_drift")
        run_contract = _validate_sol_run_contract(
            value["run_contract"], source_row=source_row, bundle=bundle
        )
    else:
        run_contract = _validate_local_run_contract(value["run_contract"], side=side)
        if run_contract["output_contract_sha256"] != cohort_item["output_schema_sha256"]:
            raise CrossEvalError("local_output_contract_drift")
    accepted = copy.deepcopy(value)
    if is_v1:
        accepted["decision"] = decision
    else:
        accepted["terminal"] = terminal
    accepted["run_contract"] = run_contract
    return accepted


def validate_cohort_bundle(bundle: CohortBundle) -> None:
    if not isinstance(bundle, CohortBundle) or bundle.partition not in PARTITIONS:
        raise CrossEvalError("cohort_bundle_invalid")
    manifest = bundle.manifest
    items = manifest.get("items") if isinstance(manifest, dict) else None
    if (
        not isinstance(items, list)
        or not items
        or manifest.get("partition") != bundle.partition
        or manifest.get("items_sha256") != _canonical_sha256(items)
        or bundle.manifest_sha256 != _sha256(_json_file_bytes(manifest))
    ):
        raise CrossEvalError("cohort_bundle_invalid")
    sample_ids = [item.get("sample_id") for item in items if isinstance(item, dict)]
    if (
        len(sample_ids) != len(items)
        or len(sample_ids) != len(set(sample_ids))
        or set(sample_ids) != set(bundle.source_rows)
    ):
        raise CrossEvalError("cohort_sample_set_invalid")
    batch_counts: Counter[str] = Counter()
    source_batches: dict[str, set[str]] = defaultdict(set)
    split_batches: dict[str, set[str]] = defaultdict(set)
    for item in items:
        source = bundle.source_rows[item["sample_id"]]
        identities = _approval_identities(source["input"])
        expected = {
            "payload_sha256": source["payload_sha256"],
            "target_sha256": _canonical_sha256(source["target"]),
            "source_group_sha256": _sha256(source["group_id"].encode("utf-8")),
            "split_group_id": source["split_group_id"],
            "approval_prompt_sha256": identities["approval_prompt_sha256"],
            "message_sequence_sha256": identities["message_sequence_sha256"],
            "output_schema_sha256": identities["output_schema_sha256"],
        }
        if any(item.get(key) != value for key, value in expected.items()):
            raise CrossEvalError("cohort_item_identity_drift")
        batch_id = item.get("body_batch_id")
        if not isinstance(batch_id, str) or _ID.fullmatch(batch_id) is None:
            raise CrossEvalError("cohort_batch_id_invalid")
        batch_counts[batch_id] += 1
        source_batches[item["source_group_sha256"]].add(batch_id)
        split_batches[item["split_group_id"]].add(batch_id)
    if any(len(values) != 1 for values in source_batches.values()) or any(
        len(values) != 1 for values in split_batches.values()
    ):
        raise CrossEvalError("cohort_group_cross_batch")
    if any(count > MAX_BATCH_SAMPLES for count in batch_counts.values()):
        raise CrossEvalError("cohort_batch_limit_exceeded")
    batching = manifest.get("batching")
    if not isinstance(batching, dict) or batching.get("max_batch_samples") != MAX_BATCH_SAMPLES:
        raise CrossEvalError("cohort_batch_summary_invalid")
    declared = batching.get("batches")
    if not isinstance(declared, list) or batching.get("batch_count") != len(declared):
        raise CrossEvalError("cohort_batch_summary_invalid")
    declared_counts = {
        value.get("batch_id"): value.get("sample_count")
        for value in declared
        if isinstance(value, dict)
    }
    if declared_counts != dict(batch_counts):
        raise CrossEvalError("cohort_batch_summary_invalid")


def validate_three_side_rows(
    bundle: CohortBundle,
    values: Sequence[Any],
    *,
    l6_pair_receipt: Mapping[str, Any] | FormalL6PairEvidence | None,
) -> list[dict[str, Any]]:
    """Validate one complete, all-or-nothing three-side import.

    Legacy v1 decision rows retain their frozen structural contract.  Formal
    Plan 037 v2 rows cannot be imported from a self-reported receipt mapping;
    callers must retain source-validated evidence from ``paired_outputs``.
    """

    validate_cohort_bundle(bundle)
    if l6_pair_receipt is None:
        raise CrossEvalError("l6_pair_receipt_required")
    contains_v2_local = any(
        isinstance(value, dict)
        and value.get("side") in {"local-static", "local-ft-static"}
        and value.get("schema_version") == TERMINAL_IMPORT_SCHEMA_VERSION
        for value in values
    )
    if isinstance(l6_pair_receipt, FormalL6PairEvidence):
        receipt_value: Mapping[str, Any] = l6_pair_receipt.receipt
    else:
        if contains_v2_local:
            raise CrossEvalError("l6_pair_sources_required")
        receipt_value = l6_pair_receipt
    _receipt, _receipt_sha256, expected_local_contracts = validate_l6_pair_receipt(
        receipt_value
    )
    items = {item["sample_id"]: item for item in bundle.manifest["items"]}
    expected_count = len(items) * len(SIDES)
    if len(values) != expected_count:
        raise CrossEvalError("three_side_import_incomplete")
    accepted: dict[tuple[str, str], dict[str, Any]] = {}
    for value in values:
        if not isinstance(value, dict):
            raise CrossEvalError("side_output_invalid")
        sample_id = value.get("sample_id")
        side = value.get("side")
        if side not in SIDES:
            raise CrossEvalError("side_unknown")
        if sample_id not in items or sample_id not in bundle.source_rows:
            raise CrossEvalError("sample_unknown")
        key = (sample_id, side)
        if key in accepted:
            raise CrossEvalError("side_output_duplicate")
        accepted[key] = _validate_import_row(
            value,
            bundle=bundle,
            cohort_item=items[sample_id],
            source_row=bundle.source_rows[sample_id],
        )
    expected_keys = {(sample_id, side) for sample_id in items for side in SIDES}
    if set(accepted) != expected_keys:
        raise CrossEvalError("three_side_import_incomplete")

    per_side_contracts: dict[str, set[bytes]] = {side: set() for side in SIDES}
    for (sample_id, side), row in accepted.items():
        del sample_id
        per_side_contracts[side].add(_canonical_bytes(row["run_contract"]))
    if any(len(values) != 1 for values in per_side_contracts.values()):
        raise CrossEvalError("side_run_contract_not_uniform")
    local_static = json.loads(next(iter(per_side_contracts["local-static"])).decode("utf-8"))
    local_ft = json.loads(next(iter(per_side_contracts["local-ft-static"])).decode("utf-8"))
    shared_fields = (
        "contract_version",
        "source_work_package",
        "pair_id",
        "pair_receipt_sha256",
        "base_model_identity_sha256",
        "runtime_identity_sha256",
        "chat_template_sha256",
        "request_contract_sha256",
        "sampling_contract",
        "output_contract_sha256",
    )
    if any(local_static[field] != local_ft[field] for field in shared_fields):
        raise CrossEvalError("local_pair_contract_mismatch")
    if local_static["model_artifact_sha256"] == local_ft["model_artifact_sha256"]:
        raise CrossEvalError("local_pair_artifacts_not_distinct")
    if (
        local_static != expected_local_contracts["local-static"]
        or local_ft != expected_local_contracts["local-ft-static"]
    ):
        raise CrossEvalError("local_pair_receipt_mismatch")
    return [accepted[key] for key in sorted(accepted)]


def validate_three_side_import(
    worktree_root: Path, input_path: Path, pair_receipt_path: Path
) -> tuple[CohortBundle, list[dict[str, Any]], dict[str, Any]]:
    bundle = load_synthetic_bundle(worktree_root)
    values, _raw = _load_jsonl(input_path, private=True)
    receipt, receipt_raw = _load_json(pair_receipt_path, private=True)
    normalized_receipt, _sha, _contracts = validate_l6_pair_receipt(
        receipt, raw=receipt_raw
    )
    return (
        bundle,
        validate_three_side_rows(
            bundle, values, l6_pair_receipt=normalized_receipt
        ),
        normalized_receipt,
    )


def build_private_holdout_bundle(
    records: Sequence[Any], *, holdout_batch_id: str
) -> CohortBundle:
    """Validate a future private holdout projection without writing or publishing it."""

    fields = {
        "schema_version",
        "contract_version",
        "holdout_batch_id",
        "sample_id",
        "source_group_id",
        "split_group_id",
        "approval_input",
        "payload_sha256",
        "sol_target",
        "teacher_model",
        "generated_date",
        "teacher_prompt_version",
        "teacher_prompt_sha256",
    }
    if not isinstance(holdout_batch_id, str) or _ID.fullmatch(holdout_batch_id) is None:
        raise CrossEvalError("holdout_batch_id_invalid")
    normalized: list[dict[str, Any]] = []
    for value in records:
        if not isinstance(value, dict) or set(value) != fields:
            raise CrossEvalError("holdout_source_fields_invalid")
        if (
            value["schema_version"] != 1
            or value["contract_version"] != HOLDOUT_PRIVATE_CONTRACT_VERSION
            or value["holdout_batch_id"] != holdout_batch_id
            or not isinstance(value["sample_id"], str)
            or _HEX64.fullmatch(value["sample_id"]) is None
            or not isinstance(value["source_group_id"], str)
            or _ID.fullmatch(value["source_group_id"]) is None
            or not isinstance(value["split_group_id"], str)
            or _HEX64.fullmatch(value["split_group_id"]) is None
            or not isinstance(value["teacher_model"], str)
            or not value["teacher_model"]
            or not isinstance(value["teacher_prompt_version"], str)
            or not value["teacher_prompt_version"]
            or not isinstance(value["teacher_prompt_sha256"], str)
            or _HEX64.fullmatch(value["teacher_prompt_sha256"]) is None
        ):
            raise CrossEvalError("holdout_source_identity_invalid")
        _validate_date(value["generated_date"])
        identities = _approval_identities(value["approval_input"])
        if identities["payload_sha256"] != value["payload_sha256"]:
            raise CrossEvalError("holdout_payload_identity_invalid")
        try:
            target = validate_static_decision(value["sol_target"])
        except EvidenceError as exc:
            raise CrossEvalError("holdout_sol_target_invalid") from exc
        normalized.append(
            {
                "batch_id": holdout_batch_id,
                "generator_model": value["teacher_model"],
                "generated_date": value["generated_date"],
                "prompt_version": value["teacher_prompt_version"],
                "prompt_sha256": value["teacher_prompt_sha256"],
                "sample_id": value["sample_id"],
                "group_id": value["source_group_id"],
                "split_group_id": value["split_group_id"],
                "category": "holdout_anchor",
                "input": copy.deepcopy(value["approval_input"]),
                "payload_sha256": value["payload_sha256"],
                "target": target,
            }
        )
    if not normalized or len(normalized) > MAX_BATCH_SAMPLES * 2:
        raise CrossEvalError("holdout_source_count_invalid")
    if len({row["sample_id"] for row in normalized}) != len(normalized):
        raise CrossEvalError("holdout_sample_duplicate")
    assignments, batches = assign_body_batches(normalized)
    for batch in batches:
        batch["batch_id"] = batch["batch_id"].replace("synthetic-body", "holdout-anchor")
    assignments = {
        sample_id: batch_id.replace("synthetic-body", "holdout-anchor")
        for sample_id, batch_id in assignments.items()
    }
    raw = _jsonl_bytes(
        {
            "sample_id": row["sample_id"],
            "payload_sha256": row["payload_sha256"],
            "source_group_sha256": _sha256(row["group_id"].encode("utf-8")),
            "split_group_id": row["split_group_id"],
            "target_sha256": _canonical_sha256(row["target"]),
            "teacher_model": row["generator_model"],
            "generated_date": row["generated_date"],
            "teacher_prompt_version": row["prompt_version"],
            "teacher_prompt_sha256": row["prompt_sha256"],
        }
        for row in sorted(normalized, key=lambda item: item["sample_id"])
    )
    items = []
    for row in sorted(normalized, key=lambda item: item["sample_id"]):
        identity = _approval_identities(row["input"])
        items.append(
            {
                "sample_id": row["sample_id"],
                "payload_sha256": row["payload_sha256"],
                "target_sha256": _canonical_sha256(row["target"]),
                "source_group_sha256": _sha256(row["group_id"].encode("utf-8")),
                "split_group_id": row["split_group_id"],
                "body_batch_id": assignments[row["sample_id"]],
                "approval_prompt_sha256": identity["approval_prompt_sha256"],
                "message_sequence_sha256": identity["message_sequence_sha256"],
                "output_schema_sha256": identity["output_schema_sha256"],
            }
        )
    source_sha = _sha256(raw)
    manifest = {
        "schema_version": 1,
        "contract_version": HOLDOUT_PRIVATE_CONTRACT_VERSION,
        "cohort_id": f"m4-holdout-{holdout_batch_id}",
        "partition": "holdout",
        "status": COHORT_STATUS,
        "source": {
            "private_source_sha256": source_sha,
            "sample_count": len(normalized),
            "tracked_item_projection_allowed": False,
        },
        "contracts": {
            "static_payload_schema_version": STATIC_PAYLOAD_SCHEMA_VERSION,
            "static_decision_schema_name": STATIC_DECISION_SCHEMA_NAME,
            "three_side_import_contract_version": IMPORT_CONTRACT_VERSION,
            "local_pair_contract_version": LOCAL_PAIR_CONTRACT_VERSION,
            "blinding_algorithm_version": BLINDING_ALGORITHM_VERSION,
        },
        "batching": {
            "batch_count": len([batch for batch in batches if batch["sample_count"]]),
            "max_batch_samples": MAX_BATCH_SAMPLES,
            "batches": [batch for batch in batches if batch["sample_count"]],
        },
        "items": items,
        "items_sha256": _canonical_sha256(items),
        "visibility": "private_only",
    }
    manifest_raw = _json_file_bytes(manifest)
    return CohortBundle(
        "holdout",
        manifest,
        _sha256(manifest_raw),
        {row["sample_id"]: row for row in normalized},
    )


def _side_identity_markers(rows: Sequence[Mapping[str, Any]]) -> set[str]:
    markers = set(SIDES)
    for row in rows:
        contract = row["run_contract"]
        fields = (
            (
                "provenance",
                "source_dataset_batch_id",
                "source_generation_model",
            )
            if row["side"] == "sol-static"
            else (
                "provenance",
                "pair_id",
                "pair_receipt_sha256",
                "base_model_identity_sha256",
                "runtime_identity_sha256",
                "chat_template_sha256",
                "request_contract_sha256",
                "model_artifact_sha256",
                "training_receipt_sha256",
            )
        )
        for field in fields:
            value = contract.get(field)
            if isinstance(value, str) and len(value) >= 6:
                markers.add(value)
        if row["side"] != "sol-static":
            markers.update(contract["blind_identity_markers"])
    return markers


def _contains_marker(value: Any, markers: Iterable[str]) -> bool:
    lowered = tuple(marker.casefold() for marker in markers if marker)

    def visit(item: Any) -> bool:
        if isinstance(item, Mapping):
            return any(visit(key) or visit(nested) for key, nested in item.items())
        if isinstance(item, list):
            return any(visit(nested) for nested in item)
        if isinstance(item, str):
            text = item.casefold()
            return any(marker in text for marker in lowered)
        return False

    return visit(value)


def _contains_forbidden_side_identity(value: Any) -> bool:
    def visit(item: Any) -> bool:
        if isinstance(item, Mapping):
            return any(visit(key) or visit(nested) for key, nested in item.items())
        if isinstance(item, list):
            return any(visit(nested) for nested in item)
        if isinstance(item, str):
            local_uses = list(_LOCAL_TOKEN.finditer(item))
            unsafe_local = any(
                _SAFE_LOCAL_SEMANTIC_USE.match(item, match.start()) is None
                for match in local_uses
            )
            return bool(
                _UNAMBIGUOUS_SIDE_TOKEN.search(item)
                or unsafe_local
                or _SIDE_IDENTITY_CONTEXT.search(item)
                or _MODEL_PATH_MARKER.search(item)
            )
        return False

    return visit(value)


def _balanced_side_orders(
    sample_ids: Sequence[str], *, batch_id: str, seed: bytes
) -> tuple[list[str], dict[str, tuple[str, str, str]]]:
    if not isinstance(seed, bytes) or len(seed) < 16:
        raise CrossEvalError("blinding_seed_invalid")

    def rank(label: str) -> bytes:
        return hashlib.sha256(
            b"rondo-m4-blinding-v1\0"
            + seed
            + b"\0"
            + batch_id.encode("utf-8")
            + b"\0"
            + label.encode("utf-8")
        ).digest()

    shuffled = sorted(
        sample_ids,
        key=lambda sample_id: (rank(f"sample:{sample_id}"), sample_id),
    )
    orders: dict[str, tuple[str, str, str]] = {}
    for start in range(0, len(shuffled), 3):
        block = shuffled[start : start + 3]
        base = int.from_bytes(rank(f"block:{start}:base"), "big") % 3
        direction = -1 if rank(f"block:{start}:direction")[0] & 1 else 1
        permutations = []
        for offset in range(3):
            rotation = (base + direction * offset) % 3
            permutations.append(tuple(SIDES[(rotation + index) % 3] for index in range(3)))
        permutation_order = sorted(
            range(3),
            key=lambda index: (rank(f"block:{start}:permutation:{index}"), index),
        )
        for sample_id, permutation_index in zip(block, permutation_order):
            order = permutations[permutation_index]
            orders[sample_id] = order
    return shuffled, orders


def _position_counts(mapping_entries: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, int]]:
    counts = {side: {candidate: 0 for candidate in CANDIDATES} for side in SIDES}
    for entry in mapping_entries:
        positions = entry.get("positions")
        if not isinstance(positions, list) or len(positions) != 3:
            raise CrossEvalError("blind_mapping_shape_invalid")
        for position in positions:
            candidate = position.get("candidate_id") if isinstance(position, dict) else None
            side = position.get("side") if isinstance(position, dict) else None
            if candidate not in CANDIDATES or side not in SIDES:
                raise CrossEvalError("blind_mapping_shape_invalid")
            counts[side][candidate] += 1
    for side in SIDES:
        values = list(counts[side].values())
        if max(values) - min(values) > 1:
            raise CrossEvalError("blind_positions_unbalanced")
    return counts


def build_anonymous_terminal_batches(
    bundle: CohortBundle,
    rows: Sequence[Mapping[str, Any]],
    *,
    seed: bytes,
    l6_pair_receipt: Mapping[str, Any],
) -> list[AnonymousTerminalBatch]:
    """Build balanced anonymous candidates without inventing missing decisions.

    This is deliberately a pre-judge projection, not a replacement for the
    frozen v1 judge package.  A later formal review can bind an explicit judge
    prompt/result contract to this versioned shape.  The existing v1 decision
    package and its judging semantics remain unchanged.
    """

    normalized = validate_three_side_rows(
        bundle, rows, l6_pair_receipt=l6_pair_receipt
    )
    by_key = {(row["sample_id"], row["side"]): row for row in normalized}
    cohort_items = {item["sample_id"]: item for item in bundle.manifest["items"]}
    markers = _side_identity_markers(normalized) | {seed.hex()}
    results: list[AnonymousTerminalBatch] = []
    batch_ids = sorted({item["body_batch_id"] for item in cohort_items.values()})
    for batch_id in batch_ids:
        sample_ids = sorted(
            sample_id
            for sample_id, item in cohort_items.items()
            if item["body_batch_id"] == batch_id
        )
        shuffled, orders = _balanced_side_orders(sample_ids, batch_id=batch_id, seed=seed)
        package_samples = []
        mapping_entries = []
        for sample_id in shuffled:
            source = bundle.source_rows[sample_id]
            order = orders[sample_id]
            candidates = [
                {
                    "candidate_id": candidate_id,
                    "terminal": _row_terminal(by_key[(sample_id, side)]),
                }
                for candidate_id, side in zip(CANDIDATES, order)
            ]
            package_samples.append(
                {
                    "sample_id": sample_id,
                    "payload_sha256": source["payload_sha256"],
                    "approval_input": copy.deepcopy(source["input"]),
                    "candidates": candidates,
                }
            )
            mapping_entries.append(
                {
                    "sample_id": sample_id,
                    "positions": [
                        {"candidate_id": candidate_id, "side": side}
                        for candidate_id, side in zip(CANDIDATES, order)
                    ],
                }
            )
        package = {
            "schema_version": ANONYMOUS_TERMINAL_SCHEMA_VERSION,
            "contract_version": ANONYMOUS_TERMINAL_CONTRACT_VERSION,
            "partition": bundle.partition,
            "cohort_id": bundle.manifest["cohort_id"],
            "cohort_manifest_sha256": bundle.manifest_sha256,
            "body_batch_id": batch_id,
            "samples": package_samples,
        }
        terminals = [
            candidate["terminal"]
            for sample in package_samples
            for candidate in sample["candidates"]
        ]
        if _contains_marker(package, markers) or _contains_forbidden_side_identity(
            terminals
        ):
            raise CrossEvalError("blind_package_side_leak")
        package_raw = _json_file_bytes(package)
        mapping = {
            "schema_version": MAPPING_SCHEMA_VERSION,
            "contract_version": MAPPING_CONTRACT_VERSION,
            "partition": bundle.partition,
            "cohort_manifest_sha256": bundle.manifest_sha256,
            "body_batch_id": batch_id,
            "package_sha256": _sha256(package_raw),
            "seed_sha256": _sha256(seed),
            "position_counts": _position_counts(mapping_entries),
            "entries": mapping_entries,
        }
        results.append(AnonymousTerminalBatch(package, package_raw, mapping))
    return results


def build_blind_batches(
    bundle: CohortBundle,
    rows: Sequence[Mapping[str, Any]],
    *,
    judge_model: str,
    judged_date: str,
    seed: bytes,
    templates: TemplateIdentity,
    l6_pair_receipt: Mapping[str, Any],
) -> list[BlindBatch]:
    if not isinstance(judge_model, str) or not judge_model.strip():
        raise CrossEvalError("judge_model_invalid")
    _validate_date(judged_date)
    normalized = validate_three_side_rows(
        bundle, rows, l6_pair_receipt=l6_pair_receipt
    )
    if any(_row_terminal(row)["status"] != "decision" for row in normalized):
        raise CrossEvalError("judge_package_v1_requires_decision_terminals")
    by_key = {(row["sample_id"], row["side"]): row for row in normalized}
    cohort_items = {item["sample_id"]: item for item in bundle.manifest["items"]}
    markers = _side_identity_markers(normalized) | {seed.hex()}
    results: list[BlindBatch] = []
    batch_ids = sorted({item["body_batch_id"] for item in cohort_items.values()})
    for batch_id in batch_ids:
        sample_ids = sorted(
            sample_id
            for sample_id, item in cohort_items.items()
            if item["body_batch_id"] == batch_id
        )
        shuffled, orders = _balanced_side_orders(sample_ids, batch_id=batch_id, seed=seed)
        package_samples = []
        mapping_entries = []
        for sample_id in shuffled:
            source = bundle.source_rows[sample_id]
            order = orders[sample_id]
            candidates = [
                {
                    "candidate_id": candidate_id,
                    "decision": _row_decision(by_key[(sample_id, side)]),
                }
                for candidate_id, side in zip(CANDIDATES, order)
            ]
            package_samples.append(
                {
                    "sample_id": sample_id,
                    "payload_sha256": source["payload_sha256"],
                    "approval_input": copy.deepcopy(source["input"]),
                    "candidates": candidates,
                }
            )
            mapping_entries.append(
                {
                    "sample_id": sample_id,
                    "positions": [
                        {"candidate_id": candidate_id, "side": side}
                        for candidate_id, side in zip(CANDIDATES, order)
                    ],
                }
            )
        package = {
            "schema_version": PACKAGE_SCHEMA_VERSION,
            "contract_version": PACKAGE_CONTRACT_VERSION,
            "partition": bundle.partition,
            "cohort_id": bundle.manifest["cohort_id"],
            "cohort_manifest_sha256": bundle.manifest_sha256,
            "body_batch_id": batch_id,
            "judge_prompt_version": JUDGE_PROMPT_VERSION,
            "judge_prompt_sha256": templates.judge_prompt_sha256,
            "judge_result_schema_version": JUDGE_RESULT_SCHEMA_VERSION,
            "judge_result_schema_sha256": templates.judge_result_schema_sha256,
            "samples": package_samples,
        }
        decisions = [
            candidate["decision"]
            for sample in package_samples
            for candidate in sample["candidates"]
        ]
        if _contains_marker(package, markers) or _contains_forbidden_side_identity(
            decisions
        ):
            raise CrossEvalError("blind_package_side_leak")
        package_raw = _json_file_bytes(package)
        package_sha = _sha256(package_raw)
        mapping = {
            "schema_version": MAPPING_SCHEMA_VERSION,
            "contract_version": MAPPING_CONTRACT_VERSION,
            "partition": bundle.partition,
            "cohort_manifest_sha256": bundle.manifest_sha256,
            "body_batch_id": batch_id,
            "package_sha256": package_sha,
            "seed_sha256": _sha256(seed),
            "position_counts": _position_counts(mapping_entries),
            "entries": mapping_entries,
        }
        request = {
            "schema_version": REQUEST_SCHEMA_VERSION,
            "contract_version": REQUEST_CONTRACT_VERSION,
            "partition": bundle.partition,
            "cohort_manifest_sha256": bundle.manifest_sha256,
            "body_batch_id": batch_id,
            "package_sha256": package_sha,
            "sample_count": len(package_samples),
            "judge_prompt_version": JUDGE_PROMPT_VERSION,
            "judge_prompt_sha256": templates.judge_prompt_sha256,
            "judge_result_schema_version": JUDGE_RESULT_SCHEMA_VERSION,
            "judge_result_schema_sha256": templates.judge_result_schema_sha256,
            "expected_judge_model": judge_model,
            "expected_judged_date": judged_date,
            "status": "awaiting_judge_results",
        }
        results.append(BlindBatch(package, package_raw, mapping, request))
    return results


def _validate_judge_result_row(
    value: Any,
    *,
    blind: BlindBatch,
    expected_sample_ids: set[str],
    markers: set[str],
) -> dict[str, Any]:
    fields = {
        "schema_version",
        "contract_version",
        "partition",
        "cohort_manifest_sha256",
        "body_batch_id",
        "package_sha256",
        "sample_id",
        "judge_prompt_version",
        "judge_prompt_sha256",
        "judge_model",
        "judged_date",
        "independent_judgment",
        "candidate_assessments",
        "preferred_candidates",
        "all_candidates_inadequate",
        "comparative_rationale",
    }
    if not isinstance(value, dict) or set(value) != fields:
        raise CrossEvalError("judge_result_fields_invalid")
    request = blind.request
    expected = {
        "schema_version": JUDGE_RESULT_SCHEMA_VERSION,
        "contract_version": JUDGE_RESULT_CONTRACT_VERSION,
        "partition": request["partition"],
        "cohort_manifest_sha256": request["cohort_manifest_sha256"],
        "body_batch_id": request["body_batch_id"],
        "package_sha256": request["package_sha256"],
        "judge_prompt_version": request["judge_prompt_version"],
        "judge_prompt_sha256": request["judge_prompt_sha256"],
        "judge_model": request["expected_judge_model"],
        "judged_date": request["expected_judged_date"],
    }
    if any(value.get(key) != expected_value for key, expected_value in expected.items()):
        raise CrossEvalError("judge_result_identity_drift")
    if value.get("sample_id") not in expected_sample_ids:
        raise CrossEvalError("judge_result_sample_unknown")
    _validate_date(value["judged_date"])
    try:
        independent = validate_static_decision(value["independent_judgment"])
    except EvidenceError as exc:
        raise CrossEvalError("judge_independent_judgment_invalid") from exc
    assessments = value["candidate_assessments"]
    if not isinstance(assessments, list) or len(assessments) != 3:
        raise CrossEvalError("judge_candidate_assessments_invalid")
    normalized_assessments = []
    seen = set()
    for assessment in assessments:
        if not isinstance(assessment, dict) or set(assessment) != {
            "candidate_id",
            "approval_judgment",
            "reason_quality",
            "rationale",
        }:
            raise CrossEvalError("judge_candidate_assessments_invalid")
        if (
            assessment["candidate_id"] not in CANDIDATES
            or assessment["candidate_id"] in seen
            or assessment["approval_judgment"]
            not in {"supported", "unsupported", "uncertain"}
            or assessment["reason_quality"] not in {"strong", "adequate", "weak"}
            or not isinstance(assessment["rationale"], str)
            or not assessment["rationale"].strip()
        ):
            raise CrossEvalError("judge_candidate_assessments_invalid")
        seen.add(assessment["candidate_id"])
        normalized_assessments.append(copy.deepcopy(assessment))
    if seen != set(CANDIDATES):
        raise CrossEvalError("judge_candidate_assessments_invalid")
    preferred = value["preferred_candidates"]
    inadequate = value["all_candidates_inadequate"]
    if (
        not isinstance(preferred, list)
        or len(preferred) != len(set(preferred))
        or any(candidate not in CANDIDATES for candidate in preferred)
        or not isinstance(inadequate, bool)
        or (inadequate and preferred)
        or (not inadequate and not preferred)
        or not isinstance(value["comparative_rationale"], str)
        or not value["comparative_rationale"].strip()
    ):
        raise CrossEvalError("judge_preference_invalid")
    if _contains_marker(value, markers) or _contains_forbidden_side_identity(value):
        raise CrossEvalError("judge_result_side_leak")
    accepted = copy.deepcopy(value)
    accepted["independent_judgment"] = independent
    accepted["candidate_assessments"] = normalized_assessments
    return accepted


def validate_judge_results(
    blind: BlindBatch,
    values: Sequence[Any],
    *,
    markers: set[str],
) -> list[dict[str, Any]]:
    expected_sample_ids = {item["sample_id"] for item in blind.package["samples"]}
    if len(values) != len(expected_sample_ids):
        raise CrossEvalError("judge_result_set_incomplete")
    accepted: dict[str, dict[str, Any]] = {}
    for value in values:
        row = _validate_judge_result_row(
            value,
            blind=blind,
            expected_sample_ids=expected_sample_ids,
            markers=markers,
        )
        sample_id = row["sample_id"]
        if sample_id in accepted:
            raise CrossEvalError("judge_result_duplicate")
        accepted[sample_id] = row
    if set(accepted) != expected_sample_ids:
        raise CrossEvalError("judge_result_set_incomplete")
    return [accepted[sample_id] for sample_id in sorted(accepted)]


def unblind_batch(
    bundle: CohortBundle,
    imported_rows: Sequence[Mapping[str, Any]],
    blind: BlindBatch,
    judge_values: Sequence[Any],
    *,
    l6_pair_receipt: Mapping[str, Any],
) -> dict[str, Any]:
    if _sha256(blind.package_raw) != blind.mapping.get("package_sha256"):
        raise CrossEvalError("blind_mapping_package_drift")
    if blind.request.get("package_sha256") != blind.mapping.get("package_sha256"):
        raise CrossEvalError("judge_request_package_drift")
    if blind.mapping.get("cohort_manifest_sha256") != bundle.manifest_sha256:
        raise CrossEvalError("blind_mapping_cohort_drift")
    _position_counts(blind.mapping.get("entries", []))
    normalized = validate_three_side_rows(
        bundle, imported_rows, l6_pair_receipt=l6_pair_receipt
    )
    by_key = {(row["sample_id"], row["side"]): row for row in normalized}
    markers = _side_identity_markers(normalized)
    results = validate_judge_results(blind, judge_values, markers=markers)
    package_samples = {item["sample_id"]: item for item in blind.package["samples"]}
    mapping_entries = {
        item["sample_id"]: item for item in blind.mapping.get("entries", [])
    }
    expected_samples = set(package_samples)
    if set(mapping_entries) != expected_samples or len(mapping_entries) != len(
        blind.mapping.get("entries", [])
    ):
        raise CrossEvalError("blind_mapping_sample_set_invalid")
    records = []
    for result in results:
        sample_id = result["sample_id"]
        positions = mapping_entries[sample_id]["positions"]
        candidate_to_side = {item["candidate_id"]: item["side"] for item in positions}
        if set(candidate_to_side) != set(CANDIDATES) or set(
            candidate_to_side.values()
        ) != set(SIDES):
            raise CrossEvalError("blind_mapping_shape_invalid")
        package_decisions = {
            item["candidate_id"]: item["decision"]
            for item in package_samples[sample_id]["candidates"]
        }
        for candidate_id, side in candidate_to_side.items():
            if package_decisions.get(candidate_id) != _row_decision(
                by_key[(sample_id, side)]
            ):
                raise CrossEvalError("blind_mapping_decision_mismatch")
        assessment_by_candidate = {
            item["candidate_id"]: item for item in result["candidate_assessments"]
        }
        records.append(
            {
                "sample_id": sample_id,
                "payload_sha256": bundle.source_rows[sample_id]["payload_sha256"],
                "judge_independent_judgment": result["independent_judgment"],
                "sides": [
                    {
                        "side": side,
                        "decision": _row_decision(by_key[(sample_id, side)]),
                        "candidate_id": candidate_id,
                        "assessment": assessment_by_candidate[candidate_id],
                        "preferred": candidate_id in result["preferred_candidates"],
                    }
                    for candidate_id, side in sorted(candidate_to_side.items())
                ],
                "all_candidates_inadequate": result["all_candidates_inadequate"],
                "comparative_rationale": result["comparative_rationale"],
            }
        )
    return {
        "schema_version": UNBLINDED_SCHEMA_VERSION,
        "contract_version": UNBLINDED_CONTRACT_VERSION,
        "partition": bundle.partition,
        "cohort_manifest_sha256": bundle.manifest_sha256,
        "body_batch_id": blind.request["body_batch_id"],
        "package_sha256": blind.request["package_sha256"],
        "judge_prompt_version": blind.request["judge_prompt_version"],
        "judge_prompt_sha256": blind.request["judge_prompt_sha256"],
        "judge_model": blind.request["expected_judge_model"],
        "judged_date": blind.request["expected_judged_date"],
        "sample_count": len(records),
        "records": sorted(records, key=lambda item: item["sample_id"]),
    }


def aggregate_unblinded(values: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not values:
        raise CrossEvalError("aggregate_input_empty")
    partitions = {value.get("partition") for value in values}
    if len(partitions) != 1 or next(iter(partitions)) not in PARTITIONS:
        raise CrossEvalError("aggregate_partition_mixed")
    partition = next(iter(partitions))
    cohort_hashes = {value.get("cohort_manifest_sha256") for value in values}
    if len(cohort_hashes) != 1:
        raise CrossEvalError("aggregate_cohort_mixed")
    batch_ids = [value.get("body_batch_id") for value in values]
    if any(not isinstance(batch_id, str) for batch_id in batch_ids) or len(batch_ids) != len(
        set(batch_ids)
    ):
        raise CrossEvalError("aggregate_batch_invalid")
    if any(
        not isinstance(value.get("judge_model"), str)
        or not value["judge_model"].strip()
        or not isinstance(value.get("judged_date"), str)
        for value in values
    ):
        raise CrossEvalError("aggregate_judge_identity_invalid")
    for value in values:
        _validate_date(value["judged_date"])
    seen_samples = set()
    side_facts: dict[str, dict[str, Any]] = {
        side: {
            "candidate_outcomes": Counter(),
            "judge_outcome_agreement": 0,
            "judge_deny_side_allow": 0,
            "judge_allow_side_deny": 0,
            "sole_preferred": 0,
            "tied_preferred": 0,
            "not_preferred": 0,
            "all_candidates_inadequate": 0,
            "approval_judgments": Counter(),
            "reason_quality": Counter(),
        }
        for side in SIDES
    }
    judge_outcomes: Counter[str] = Counter()
    sample_count = 0
    for batch in values:
        if (
            batch.get("schema_version") != UNBLINDED_SCHEMA_VERSION
            or batch.get("contract_version") != UNBLINDED_CONTRACT_VERSION
            or not isinstance(batch.get("records"), list)
            or batch.get("sample_count") != len(batch["records"])
        ):
            raise CrossEvalError("aggregate_batch_contract_invalid")
        for record in batch["records"]:
            sample_id = record.get("sample_id") if isinstance(record, dict) else None
            if not isinstance(sample_id, str) or sample_id in seen_samples:
                raise CrossEvalError("aggregate_sample_duplicate")
            seen_samples.add(sample_id)
            sides = record.get("sides")
            if (
                not isinstance(sides, list)
                or len(sides) != len(SIDES)
                or {item.get("side") for item in sides} != set(SIDES)
            ):
                raise CrossEvalError("aggregate_side_set_invalid")
            preferred_count = sum(bool(item.get("preferred")) for item in sides)
            inadequate = record.get("all_candidates_inadequate")
            if (
                not isinstance(inadequate, bool)
                or (inadequate and preferred_count)
                or (not inadequate and preferred_count == 0)
            ):
                raise CrossEvalError("aggregate_preference_invalid")
            judge_outcome = record.get("judge_independent_judgment", {}).get("outcome")
            if judge_outcome not in {"allow", "deny"}:
                raise CrossEvalError("aggregate_judge_outcome_invalid")
            judge_outcomes[judge_outcome] += 1
            for item in sides:
                side = item["side"]
                outcome = item.get("decision", {}).get("outcome")
                assessment = item.get("assessment")
                if (
                    outcome not in {"allow", "deny"}
                    or not isinstance(assessment, dict)
                    or assessment.get("approval_judgment")
                    not in {"supported", "unsupported", "uncertain"}
                    or assessment.get("reason_quality")
                    not in {"strong", "adequate", "weak"}
                ):
                    raise CrossEvalError("aggregate_side_record_invalid")
                facts = side_facts[side]
                facts["candidate_outcomes"][outcome] += 1
                if outcome == judge_outcome:
                    facts["judge_outcome_agreement"] += 1
                elif judge_outcome == "deny":
                    facts["judge_deny_side_allow"] += 1
                else:
                    facts["judge_allow_side_deny"] += 1
                if inadequate:
                    facts["all_candidates_inadequate"] += 1
                if item.get("preferred"):
                    facts["sole_preferred" if preferred_count == 1 else "tied_preferred"] += 1
                else:
                    facts["not_preferred"] += 1
                facts["approval_judgments"][assessment.get("approval_judgment")] += 1
                facts["reason_quality"][assessment.get("reason_quality")] += 1
            sample_count += 1
    projected_sides = {}
    for side, facts in side_facts.items():
        projected_sides[side] = {
            key: dict(sorted(value.items())) if isinstance(value, Counter) else value
            for key, value in facts.items()
        }
    return {
        "schema_version": AGGREGATE_SCHEMA_VERSION,
        "contract_version": AGGREGATE_CONTRACT_VERSION,
        "partition": partition,
        "cohort_manifest_sha256": next(iter(cohort_hashes)),
        "body_batch_ids": sorted(batch_ids),
        "sample_count": sample_count,
        "judge_models": sorted({value.get("judge_model") for value in values}),
        "judged_dates": sorted({value.get("judged_date") for value in values}),
        "judge_outcomes": dict(sorted(judge_outcomes.items())),
        "sides": projected_sides,
        "decision": None,
        "thresholds": None,
        "synthetic_holdout_combined": False,
    }


def public_holdout_summary(aggregate: Mapping[str, Any]) -> dict[str, Any]:
    fields = {
        "schema_version",
        "contract_version",
        "partition",
        "cohort_manifest_sha256",
        "body_batch_ids",
        "sample_count",
        "judge_models",
        "judged_dates",
        "judge_outcomes",
        "sides",
        "decision",
        "thresholds",
        "synthetic_holdout_combined",
    }
    if not isinstance(aggregate, Mapping) or set(aggregate) != fields:
        raise CrossEvalError("holdout_projection_fields_invalid")
    if (
        aggregate.get("schema_version") != AGGREGATE_SCHEMA_VERSION
        or aggregate.get("contract_version") != AGGREGATE_CONTRACT_VERSION
        or aggregate.get("partition") != "holdout"
        or aggregate.get("decision") is not None
        or aggregate.get("thresholds") is not None
        or aggregate.get("synthetic_holdout_combined") is not False
    ):
        raise CrossEvalError("holdout_projection_partition_invalid")
    sample_count = aggregate.get("sample_count")
    cohort_sha = aggregate.get("cohort_manifest_sha256")
    batches = aggregate.get("body_batch_ids")
    models = aggregate.get("judge_models")
    dates = aggregate.get("judged_dates")
    if (
        not isinstance(sample_count, int)
        or isinstance(sample_count, bool)
        or sample_count <= 0
        or not isinstance(cohort_sha, str)
        or _HEX64.fullmatch(cohort_sha) is None
        or not isinstance(batches, list)
        or not batches
        or len(batches) != len(set(batches))
        or any(not isinstance(item, str) or _ID.fullmatch(item) is None for item in batches)
        or not isinstance(models, list)
        or not models
        or len(models) != len(set(models))
        or any(not isinstance(item, str) or not item.strip() for item in models)
        or not isinstance(dates, list)
        or not dates
        or len(dates) != len(set(dates))
    ):
        raise CrossEvalError("holdout_projection_identity_invalid")
    for value in dates:
        _validate_date(value)

    def count_map(value: Any, keys: set[str], *, total: int) -> dict[str, int]:
        if (
            not isinstance(value, Mapping)
            or not value
            or not set(value).issubset(keys)
            or any(
                not isinstance(count, int) or isinstance(count, bool) or count < 0
                for count in value.values()
            )
            or sum(value.values()) != total
        ):
            raise CrossEvalError("holdout_projection_counts_invalid")
        return {key: value[key] for key in sorted(value)}

    judge_outcomes = count_map(
        aggregate.get("judge_outcomes"), {"allow", "deny"}, total=sample_count
    )
    sides = aggregate.get("sides")
    side_fields = {
        "candidate_outcomes",
        "judge_outcome_agreement",
        "judge_deny_side_allow",
        "judge_allow_side_deny",
        "sole_preferred",
        "tied_preferred",
        "not_preferred",
        "all_candidates_inadequate",
        "approval_judgments",
        "reason_quality",
    }
    if not isinstance(sides, Mapping) or set(sides) != set(SIDES):
        raise CrossEvalError("holdout_projection_sides_invalid")
    projected_sides: dict[str, dict[str, Any]] = {}
    for side in SIDES:
        facts = sides[side]
        if not isinstance(facts, Mapping) or set(facts) != side_fields:
            raise CrossEvalError("holdout_projection_side_fields_invalid")
        scalar_names = side_fields - {
            "candidate_outcomes",
            "approval_judgments",
            "reason_quality",
        }
        if any(
            not isinstance(facts[name], int)
            or isinstance(facts[name], bool)
            or facts[name] < 0
            for name in scalar_names
        ):
            raise CrossEvalError("holdout_projection_counts_invalid")
        if (
            facts["judge_outcome_agreement"]
            + facts["judge_deny_side_allow"]
            + facts["judge_allow_side_deny"]
            != sample_count
            or facts["sole_preferred"]
            + facts["tied_preferred"]
            + facts["not_preferred"]
            != sample_count
            or facts["all_candidates_inadequate"] > sample_count
        ):
            raise CrossEvalError("holdout_projection_counts_invalid")
        projected_sides[side] = {
            "candidate_outcomes": count_map(
                facts["candidate_outcomes"], {"allow", "deny"}, total=sample_count
            ),
            "judge_outcome_agreement": facts["judge_outcome_agreement"],
            "judge_deny_side_allow": facts["judge_deny_side_allow"],
            "judge_allow_side_deny": facts["judge_allow_side_deny"],
            "sole_preferred": facts["sole_preferred"],
            "tied_preferred": facts["tied_preferred"],
            "not_preferred": facts["not_preferred"],
            "all_candidates_inadequate": facts["all_candidates_inadequate"],
            "approval_judgments": count_map(
                facts["approval_judgments"],
                {"supported", "unsupported", "uncertain"},
                total=sample_count,
            ),
            "reason_quality": count_map(
                facts["reason_quality"], {"strong", "adequate", "weak"}, total=sample_count
            ),
        }
    allowed = {
        "schema_version": 1,
        "contract_version": HOLDOUT_PUBLIC_CONTRACT_VERSION,
        "partition": "holdout",
        "cohort_manifest_sha256": cohort_sha,
        "body_batch_ids": sorted(batches),
        "sample_count": sample_count,
        "judge_models": sorted(models),
        "judged_dates": sorted(dates),
        "judge_outcomes": judge_outcomes,
        "sides": projected_sides,
        "tasks": None,
        "decision": None,
        "thresholds": None,
        "synthetic_holdout_combined": False,
    }
    return allowed


def _task_preflight_directory(worktree_root: Path) -> Path:
    paths = RepoPaths.discover(worktree_root)
    current = paths.common_root / "eval-data"
    try:
        root_info = os.lstat(current)
    except OSError as exc:
        raise CrossEvalError("eval_data_root_missing") from exc
    if not stat.S_ISDIR(root_info.st_mode) or stat.S_ISLNK(root_info.st_mode):
        raise CrossEvalError("eval_data_root_invalid")
    for component in ("local-approval", "m4", "plan036-preflight-v1"):
        current = current / component
        if not current.exists():
            os.mkdir(current, 0o700)
        _require_private_directory(current)
    return current


def _require_execution_private_directory(
    worktree_root: Path, private_dir: Path
) -> Path:
    paths = RepoPaths.discover(worktree_root)
    eval_data = paths.common_root / "eval-data"
    base = eval_data / "cross-eval"
    try:
        eval_data_info = os.lstat(eval_data)
        base_info = os.lstat(base)
        private_info = os.lstat(private_dir)
        resolved_base = base.resolve(strict=True)
        resolved_private = private_dir.resolve(strict=True)
    except OSError as exc:
        raise CrossEvalError("cross_eval_private_directory_missing") from exc
    if (
        not stat.S_ISDIR(eval_data_info.st_mode)
        or stat.S_ISLNK(eval_data_info.st_mode)
        or not stat.S_ISDIR(base_info.st_mode)
        or stat.S_ISLNK(base_info.st_mode)
        or stat.S_IMODE(base_info.st_mode) != 0o700
        or not stat.S_ISDIR(private_info.st_mode)
        or stat.S_ISLNK(private_info.st_mode)
        or stat.S_IMODE(private_info.st_mode) != 0o700
        or resolved_private.parent != resolved_base
        or _ID.fullmatch(private_dir.name) is None
    ):
        raise CrossEvalError("cross_eval_private_directory_out_of_scope")
    _require_private_directory(private_dir)
    return resolved_private


def write_preflight_receipt(worktree_root: Path, private_dir: Path) -> dict[str, Any]:
    expected_directory = _task_preflight_directory(worktree_root)
    if private_dir.resolve(strict=True) != expected_directory.resolve(strict=True):
        raise CrossEvalError("preflight_private_directory_out_of_scope")
    result = preflight_synthetic_cohort(worktree_root)
    receipt = {
        "schema_version": 1,
        "purpose": "Plan 036 no-model synthetic cohort preflight",
        **result,
    }
    path = private_dir / "preflight-receipt.json"
    raw = _json_file_bytes(receipt)
    if path.exists() or path.is_symlink():
        if _safe_read(path, private=True) != raw:
            raise CrossEvalError("preflight_receipt_drift")
    else:
        _write_exclusive(path, raw, mode=0o600)
    return result


def write_blind_batch_files(
    private_dir: Path, blind_batches: Sequence[BlindBatch], *, seed: bytes
) -> dict[str, Any]:
    _require_private_directory(private_dir)
    seed_record = {
        "schema_version": 1,
        "algorithm_version": BLINDING_ALGORITHM_VERSION,
        "seed_hex": seed.hex(),
        "seed_sha256": _sha256(seed),
    }
    _write_exclusive(
        private_dir / "blinding-seed.json", _json_file_bytes(seed_record), mode=0o600
    )
    summaries = []
    for blind in blind_batches:
        batch_id = blind.request["body_batch_id"]
        _write_exclusive(
            private_dir / f"judge-package-{batch_id}.json",
            blind.package_raw,
            mode=0o600,
        )
        _write_exclusive(
            private_dir / f"blind-map-{batch_id}.json",
            _json_file_bytes(blind.mapping),
            mode=0o600,
        )
        _write_exclusive(
            private_dir / f"judge-request-{batch_id}.json",
            _json_file_bytes(blind.request),
            mode=0o600,
        )
        summaries.append(
            {
                "body_batch_id": batch_id,
                "sample_count": blind.request["sample_count"],
                "package_sha256": blind.request["package_sha256"],
                "positions_balanced": True,
            }
        )
    return {
        "status": "awaiting_judge_results",
        "batch_count": len(summaries),
        "batches": summaries,
        "seed_private": True,
        "mapping_private": True,
    }


def prepare_private_blind_review(
    *,
    worktree_root: Path,
    outputs_path: Path,
    pair_receipt_path: Path,
    private_dir: Path,
    judge_model: str,
    judged_date: str,
    seed: bytes | None = None,
) -> dict[str, Any]:
    resolved_private = _require_execution_private_directory(worktree_root, private_dir)
    if (
        outputs_path.parent.resolve(strict=True) != resolved_private
        or pair_receipt_path.parent.resolve(strict=True) != resolved_private
    ):
        raise CrossEvalError("import_artifact_out_of_private_batch")
    bundle, rows, pair_receipt = validate_three_side_import(
        worktree_root, outputs_path, pair_receipt_path
    )
    templates = load_template_identity(worktree_root)
    private_seed = seed if seed is not None else secrets.token_bytes(32)
    blind_batches = build_blind_batches(
        bundle,
        rows,
        judge_model=judge_model,
        judged_date=judged_date,
        seed=private_seed,
        templates=templates,
        l6_pair_receipt=pair_receipt,
    )
    return write_blind_batch_files(private_dir, blind_batches, seed=private_seed)


def _load_and_rebuild_private_blinds(
    *,
    worktree_root: Path,
    outputs_path: Path,
    pair_receipt_path: Path,
    private_dir: Path,
) -> tuple[
    CohortBundle, list[dict[str, Any]], dict[str, Any], list[BlindBatch]
]:
    resolved_private = _require_execution_private_directory(worktree_root, private_dir)
    if (
        outputs_path.parent.resolve(strict=True) != resolved_private
        or pair_receipt_path.parent.resolve(strict=True) != resolved_private
    ):
        raise CrossEvalError("import_artifact_out_of_private_batch")
    bundle, rows, pair_receipt = validate_three_side_import(
        worktree_root, outputs_path, pair_receipt_path
    )
    seed_record, _seed_raw = _load_json(
        private_dir / "blinding-seed.json", private=True
    )
    if (
        not isinstance(seed_record, dict)
        or set(seed_record) != {
            "schema_version",
            "algorithm_version",
            "seed_hex",
            "seed_sha256",
        }
        or seed_record["schema_version"] != 1
        or seed_record["algorithm_version"] != BLINDING_ALGORITHM_VERSION
        or not isinstance(seed_record["seed_hex"], str)
    ):
        raise CrossEvalError("blinding_seed_record_invalid")
    try:
        seed = bytes.fromhex(seed_record["seed_hex"])
    except ValueError as exc:
        raise CrossEvalError("blinding_seed_record_invalid") from exc
    if len(seed) < 16 or seed_record["seed_sha256"] != _sha256(seed):
        raise CrossEvalError("blinding_seed_record_invalid")
    batch_ids = sorted(
        {item["body_batch_id"] for item in bundle.manifest["items"]}
    )
    requests = []
    for batch_id in batch_ids:
        request, _raw = _load_json(
            private_dir / f"judge-request-{batch_id}.json", private=True
        )
        if not isinstance(request, dict):
            raise CrossEvalError("judge_request_invalid")
        requests.append(request)
    judge_models = {request.get("expected_judge_model") for request in requests}
    judged_dates = {request.get("expected_judged_date") for request in requests}
    if len(judge_models) != 1 or len(judged_dates) != 1:
        raise CrossEvalError("judge_request_identity_mixed")
    rebuilt = build_blind_batches(
        bundle,
        rows,
        judge_model=next(iter(judge_models)),
        judged_date=next(iter(judged_dates)),
        seed=seed,
        templates=load_template_identity(worktree_root),
        l6_pair_receipt=pair_receipt,
    )
    for blind in rebuilt:
        batch_id = blind.request["body_batch_id"]
        package_raw = _safe_read(
            private_dir / f"judge-package-{batch_id}.json", private=True
        )
        mapping, mapping_raw = _load_json(
            private_dir / f"blind-map-{batch_id}.json", private=True
        )
        request, request_raw = _load_json(
            private_dir / f"judge-request-{batch_id}.json", private=True
        )
        if (
            package_raw != blind.package_raw
            or mapping != blind.mapping
            or mapping_raw != _json_file_bytes(blind.mapping)
            or request != blind.request
            or request_raw != _json_file_bytes(blind.request)
        ):
            raise CrossEvalError("private_blind_artifact_drift")
    return bundle, rows, pair_receipt, rebuilt


def import_unblind_and_aggregate(
    *,
    worktree_root: Path,
    outputs_path: Path,
    pair_receipt_path: Path,
    private_dir: Path,
) -> dict[str, Any]:
    bundle, rows, pair_receipt, blinds = _load_and_rebuild_private_blinds(
        worktree_root=worktree_root,
        outputs_path=outputs_path,
        pair_receipt_path=pair_receipt_path,
        private_dir=private_dir,
    )
    markers = _side_identity_markers(rows)
    validated_results: list[tuple[BlindBatch, list[dict[str, Any]]]] = []
    for blind in blinds:
        batch_id = blind.request["body_batch_id"]
        judge_values, _raw = _load_jsonl(
            private_dir / f"judge-results-{batch_id}.jsonl", private=True
        )
        validated_results.append(
            (
                blind,
                validate_judge_results(blind, judge_values, markers=markers),
            )
        )
    unblinded = [
        unblind_batch(
            bundle,
            rows,
            blind,
            judge_values,
            l6_pair_receipt=pair_receipt,
        )
        for blind, judge_values in validated_results
    ]
    aggregate = aggregate_unblinded(unblinded)
    output_paths = [
        private_dir / f"unblinded-{batch['body_batch_id']}.json"
        for batch in unblinded
    ] + [private_dir / "aggregate.json"]
    if any(path.exists() or path.is_symlink() for path in output_paths):
        raise CrossEvalError("output_already_exists")
    for batch in unblinded:
        batch_id = batch["body_batch_id"]
        _write_exclusive(
            private_dir / f"unblinded-{batch_id}.json",
            _json_file_bytes(batch),
            mode=0o600,
        )
    _write_exclusive(
        private_dir / "aggregate.json", _json_file_bytes(aggregate), mode=0o600
    )
    return {
        "status": "complete",
        "partition": aggregate["partition"],
        "sample_count": aggregate["sample_count"],
        "body_batch_ids": aggregate["body_batch_ids"],
        "decision": None,
        "thresholds": None,
        "synthetic_holdout_combined": False,
    }


def _print_result(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m rondo_eval.local_approval.cross_eval"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze-synthetic-cohort")
    freeze.add_argument("--worktree-root", type=Path, required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--worktree-root", type=Path, required=True)
    preflight.add_argument("--private-dir", type=Path, required=True)
    verify_import = commands.add_parser("verify-import")
    verify_import.add_argument("--worktree-root", type=Path, required=True)
    verify_import.add_argument("--outputs", type=Path, required=True)
    verify_import.add_argument("--pair-receipt", type=Path, required=True)
    pack = commands.add_parser("pack")
    pack.add_argument("--worktree-root", type=Path, required=True)
    pack.add_argument("--outputs", type=Path, required=True)
    pack.add_argument("--pair-receipt", type=Path, required=True)
    pack.add_argument("--private-dir", type=Path, required=True)
    pack.add_argument("--judge-model", required=True)
    pack.add_argument("--judged-date", required=True)
    import_results = commands.add_parser("import-results")
    import_results.add_argument("--worktree-root", type=Path, required=True)
    import_results.add_argument("--outputs", type=Path, required=True)
    import_results.add_argument("--pair-receipt", type=Path, required=True)
    import_results.add_argument("--private-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "freeze-synthetic-cohort":
            result = freeze_synthetic_cohort(args.worktree_root)
        elif args.command == "preflight":
            result = write_preflight_receipt(args.worktree_root, args.private_dir)
        elif args.command == "verify-import":
            bundle, rows, _receipt = validate_three_side_import(
                args.worktree_root, args.outputs, args.pair_receipt
            )
            result = {
                "status": "ready_for_blind_packaging",
                "partition": bundle.partition,
                "sample_count": len(bundle.manifest["items"]),
                "side_output_count": len(rows),
            }
        elif args.command == "pack":
            result = prepare_private_blind_review(
                worktree_root=args.worktree_root,
                outputs_path=args.outputs,
                pair_receipt_path=args.pair_receipt,
                private_dir=args.private_dir,
                judge_model=args.judge_model,
                judged_date=args.judged_date,
            )
        else:
            result = import_unblind_and_aggregate(
                worktree_root=args.worktree_root,
                outputs_path=args.outputs,
                pair_receipt_path=args.pair_receipt,
                private_dir=args.private_dir,
            )
        _print_result(result)
        return 0
    except CrossEvalError as exc:
        report: dict[str, Any] = {"status": "not_ready", "blocker": exc.code}
        if exc.facts:
            report["facts"] = exc.facts
        _print_result(report)
        return 2
    except (ConfigError, OSError):
        _print_result({"status": "not_ready", "blocker": "filesystem_error"})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
