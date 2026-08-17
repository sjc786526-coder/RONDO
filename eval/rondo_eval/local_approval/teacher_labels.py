"""Freeze and verify one human-present Sol teacher-label batch.

This module never calls a model.  It prepares the exact canonical static v3
payloads selected from the production archive, records decisions supplied by
the current human-present Codex/Sol session, and verifies the complete batch
before emitting private L3 import metadata and a body-free tracked summary.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat
import sys
import termios
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from ..config import RepoPaths, RuntimeConfig
from ..evidence import (
    STATIC_DECISION_SCHEMA_NAME,
    STATIC_PAYLOAD_SCHEMA_VERSION,
    EvidenceError,
    PolicyIdentity,
    StaticApprovalPayload,
    build_static_payload,
    static_payload_bytes_for_consumer,
    validate_static_decision,
)
from ..terminal_bench.live import (
    TerminalBenchRunError,
    _read_safe_evidence_file as read_production_evidence_file,
    _validate_guardian_meta as validate_production_guardian_meta,
)
from . import token_census
from .qualification import _identity


MANIFEST_SCHEMA_VERSION = 1
OUTBOUND_SCHEMA_VERSION = 1
RAW_RESPONSE_SCHEMA_VERSION = 1
ATTEMPT_SCHEMA_VERSION = 1
LABEL_SCHEMA_VERSION = 1
PREPARE_RECEIPT_SCHEMA_VERSION = 1
IMPORT_METADATA_SCHEMA_VERSION = 1
SUMMARY_SCHEMA_VERSION = 1
IDENTITY_RULE_VERSION = "rondo_guardian_semantic_v1"
REPRESENTATIVE_RULE_VERSION = "frozen_e_final_sha256_lexicographic_v1"
PROMPT_VERSION = "rondo_sol_teacher_prompt_v1"
PROMPT_RELATIVE_PATH = (
    "eval/templates/local-approval/sol-teacher-prompt-v1.md"
)
LABEL_SCHEMA_RELATIVE_PATH = (
    "eval/templates/local-approval/sol-teacher-label-v1.schema.json"
)
CENSUS_RELATIVE_PATH = token_census.RESULT_RELATIVE_PATH
RUN_LEDGER_RELATIVE_PATH = "eval/results/runs.jsonl"
TEACHER_MODEL = "gpt-5.6-sol"
CONTEXT_SIZE = 12_288
MAX_OUTPUT_TOKENS = 512

# Plan 032 freezes this source snapshot.  A mismatch is a changed input set,
# not a reason to rewrite the planned counts into the result.
EXPECTED_SOURCE_INSTANCES = 47
EXPECTED_SEMANTIC_IDENTITIES = 45
EXPECTED_DUPLICATE_INSTANCES = 2
EXPECTED_12K_FIT_INSTANCES = 42
EXPECTED_SELECTED_LABELS = 40
EXPECTED_REQUEST_SHAPE = "responses_lite"
EXPECTED_CENSUS_DIGEST = (
    "22b8452717f1bcfa692cffa69389ebb4a21a0aef1a9187cd066879a6b0831144"
)

_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_BATCH_ID = re.compile(r"[0-9]{8}-[a-z0-9][a-z0-9-]{0,63}\Z")
_APPROVAL_START = ">>> APPROVAL REQUEST START\n"
_APPROVAL_END = ">>> APPROVAL REQUEST END\n"
_PLANNED_ACTION_HEADER = "Planned action JSON:\n"
_NETWORK_ACTION_HEADER = "Network access JSON:\n"
_MAX_TRACKED_FILE_BYTES = 16 * 1024 * 1024
_MAX_PRIVATE_FILE_BYTES = 64 * 1024 * 1024


class TeacherLabelsError(RuntimeError):
    """Fail-closed error with a stable, body-free diagnostic code."""

    def __init__(self, code: str, facts: Mapping[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.facts = dict(facts or {})


@dataclass(frozen=True)
class PreparedInstance:
    source_relative_path: str
    run_id: str
    review_id: str
    task_id: str
    e_final_sha256: str
    meta_sha256: str
    request_shape: str
    static_payload_sha256: str
    action_fingerprint_sha256: str
    semantic_id: str
    partition: str
    input_tokens: int
    fits_12k: bool
    canonical_payload: dict[str, Any]


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
        raise TeacherLabelsError("json_canonicalization_failed") from exc


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


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
        raise TeacherLabelsError("json_serialization_failed") from exc


def _jsonl_bytes(values: Iterable[Any]) -> bytes:
    return b"".join(_canonical_bytes(value) + b"\n" for value in values)


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _is_hex64(value: Any) -> bool:
    return isinstance(value, str) and _HEX64.fullmatch(value) is not None


def _safe_read(path: Path, *, limit: int, private: bool = False) -> bytes:
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise TeacherLabelsError("file_missing") from exc
    if not stat.S_ISREG(before.st_mode) or stat.S_ISLNK(before.st_mode):
        raise TeacherLabelsError("file_not_regular")
    if before.st_size <= 0 or before.st_size > limit:
        raise TeacherLabelsError("file_size_invalid")
    if private and stat.S_IMODE(before.st_mode) != 0o600:
        raise TeacherLabelsError("private_file_mode_invalid")
    try:
        raw = path.read_bytes()
        after = os.lstat(path)
    except OSError as exc:
        raise TeacherLabelsError("file_read_failed") from exc
    if _identity(before) != _identity(after) or len(raw) != before.st_size:
        raise TeacherLabelsError("file_changed_while_reading")
    return raw


def _load_json(path: Path, *, private: bool = False) -> tuple[Any, bytes]:
    raw = _safe_read(
        path,
        limit=_MAX_PRIVATE_FILE_BYTES if private else _MAX_TRACKED_FILE_BYTES,
        private=private,
    )
    try:
        return json.loads(raw.decode("utf-8")), raw
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TeacherLabelsError("json_file_invalid") from exc


def _load_jsonl(path: Path, *, private: bool = True) -> tuple[list[Any], bytes]:
    raw = _safe_read(
        path,
        limit=_MAX_PRIVATE_FILE_BYTES if private else _MAX_TRACKED_FILE_BYTES,
        private=private,
    )
    values: list[Any] = []
    try:
        for line in raw.decode("utf-8").splitlines():
            if not line.strip():
                raise TeacherLabelsError("jsonl_blank_line")
            values.append(json.loads(line))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TeacherLabelsError("jsonl_invalid") from exc
    if not values:
        raise TeacherLabelsError("jsonl_empty")
    return values, raw


def _write_exclusive(path: Path, raw: bytes, *, mode: int) -> None:
    if path.exists() or path.is_symlink():
        raise TeacherLabelsError("output_already_exists")
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        remaining = memoryview(raw)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("write did not progress")
            remaining = remaining[written:]
        os.fsync(descriptor)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        os.close(descriptor)
    os.replace(temporary, path)


def _write_or_match(path: Path, raw: bytes, *, mode: int) -> None:
    if path.exists() and not path.is_symlink():
        existing = _safe_read(
            path,
            limit=_MAX_PRIVATE_FILE_BYTES if mode == 0o600 else _MAX_TRACKED_FILE_BYTES,
            private=mode == 0o600,
        )
        if existing != raw:
            raise TeacherLabelsError("existing_output_differs")
        return
    _write_exclusive(path, raw, mode=mode)


def _require_private_directory(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise TeacherLabelsError("private_directory_missing") from exc
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_ISLNK(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise TeacherLabelsError("private_directory_invalid")


def _prepare_private_directory(source_root: Path, private_dir: Path, batch_id: str) -> None:
    if not source_root.is_absolute() or not private_dir.is_absolute():
        raise TeacherLabelsError("root_path_not_absolute")
    expected_base = source_root / "eval-data" / "teacher-labels"
    if private_dir.parent != expected_base or private_dir.name != batch_id:
        raise TeacherLabelsError("private_directory_out_of_scope")
    eval_data = source_root / "eval-data"
    try:
        eval_info = os.lstat(eval_data)
    except OSError as exc:
        raise TeacherLabelsError("eval_data_root_missing") from exc
    if not stat.S_ISDIR(eval_info.st_mode) or stat.S_ISLNK(eval_info.st_mode):
        raise TeacherLabelsError("eval_data_root_invalid")
    if not expected_base.exists():
        os.mkdir(expected_base, 0o700)
    _require_private_directory(expected_base)
    if private_dir.exists() or private_dir.is_symlink():
        raise TeacherLabelsError("private_batch_already_exists")
    os.mkdir(private_dir, 0o700)
    _require_private_directory(private_dir)


def extract_approval_action(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Extract the last complete, terminal approval action from static v3 input."""

    items = payload.get("input") if isinstance(payload, Mapping) else None
    if not isinstance(items, list):
        raise TeacherLabelsError("static_input_missing")
    message_texts: list[tuple[int, str, str]] = []
    for index, item in enumerate(items):
        if not isinstance(item, Mapping):
            raise TeacherLabelsError("static_input_item_invalid")
        role = item.get("role")
        if role not in {"user", "assistant"}:
            # Canonical static v3 currently contains messages only.  Reject
            # unknown item shapes instead of skipping a possibly meaningful
            # item after an approval block.
            raise TeacherLabelsError("static_input_item_unsupported")
        content = item.get("content")
        if not isinstance(content, list):
            raise TeacherLabelsError("static_message_content_invalid")
        text_parts: list[str] = []
        for part in content:
            text = part.get("text") if isinstance(part, Mapping) else None
            if not isinstance(text, str):
                raise TeacherLabelsError("static_message_text_invalid")
            text_parts.append(text)
        message_texts.append((index, role, "".join(text_parts)))

    candidates: list[tuple[int, str, int]] = []
    for index, role, message_text in message_texts:
        start = message_text.rfind(_APPROVAL_START)
        if start >= 0:
            candidates.append((index, role, start))
    if not candidates:
        raise TeacherLabelsError("approval_request_start_missing")
    message_index, role, start = candidates[-1]
    if role != "user" or message_index != len(items) - 1:
        raise TeacherLabelsError("approval_request_not_terminal")
    combined = message_texts[-1][2]
    body_start = start + len(_APPROVAL_START)
    end = combined.find(_APPROVAL_END, body_start)
    if end < 0:
        raise TeacherLabelsError("approval_request_end_missing")
    if _APPROVAL_START in combined[body_start:end]:
        raise TeacherLabelsError("approval_request_boundary_nested")
    if combined[end + len(_APPROVAL_END) :].strip():
        raise TeacherLabelsError("approval_request_not_terminal")
    block = combined[body_start:end]
    header_counts = {
        _PLANNED_ACTION_HEADER: block.count(_PLANNED_ACTION_HEADER),
        _NETWORK_ACTION_HEADER: block.count(_NETWORK_ACTION_HEADER),
    }
    matching = [header for header, count in header_counts.items() if count == 1]
    if len(matching) != 1 or any(count > 1 for count in header_counts.values()):
        raise TeacherLabelsError("approval_action_header_ambiguous")
    raw_action = block.split(matching[0], 1)[1].strip()
    try:
        action, offset = json.JSONDecoder().raw_decode(raw_action)
    except json.JSONDecodeError as exc:
        raise TeacherLabelsError("approval_action_json_invalid") from exc
    if raw_action[offset:].strip() or not isinstance(action, dict):
        raise TeacherLabelsError("approval_action_json_not_unique_object")
    _validate_supported_action(action, header=matching[0])
    return action


def _validate_supported_action(action: Mapping[str, Any], *, header: str) -> None:
    # The frozen Plan 032 source set contains only unified exec_command actions.
    # Anything else is a future identity-rule decision and must not be guessed.
    if header != _PLANNED_ACTION_HEADER or action.get("tool") != "exec_command":
        raise TeacherLabelsError("approval_action_shape_unsupported")
    required = {"tool", "command", "cwd", "sandbox_permissions", "tty"}
    allowed = required | {"additional_permissions", "justification"}
    if not required.issubset(action) or not set(action).issubset(allowed):
        raise TeacherLabelsError("exec_command_action_fields_invalid")
    command = action["command"]
    if (
        not isinstance(command, list)
        or not command
        or any(not isinstance(part, str) for part in command)
        or not isinstance(action["cwd"], str)
        or not action["cwd"].startswith("/")
        or action["sandbox_permissions"]
        not in {"use_default", "require_escalated", "with_additional_permissions"}
        or not isinstance(action["tty"], bool)
    ):
        raise TeacherLabelsError("exec_command_action_values_invalid")
    if "justification" in action and not isinstance(action["justification"], str):
        raise TeacherLabelsError("exec_command_justification_invalid")
    if "additional_permissions" in action and not isinstance(
        action["additional_permissions"], Mapping
    ):
        raise TeacherLabelsError("exec_command_additional_permissions_invalid")


def semantic_id_for(task_id: str, action: Mapping[str, Any]) -> tuple[str, str]:
    action_fingerprint = _sha256(_canonical_bytes(action))
    return action_fingerprint, _semantic_id_from_fingerprint(
        task_id, action_fingerprint
    )


def _semantic_id_from_fingerprint(task_id: str, action_fingerprint: str) -> str:
    if not isinstance(task_id, str) or not task_id:
        raise TeacherLabelsError("task_id_invalid")
    if not _is_hex64(action_fingerprint):
        raise TeacherLabelsError("action_fingerprint_invalid")
    semantic_id = hashlib.sha256(
        b"rondo-guardian-semantic-v1\0"
        + task_id.encode("utf-8")
        + b"\0"
        + action_fingerprint.encode("ascii")
    ).hexdigest()
    return semantic_id


def partition_for(semantic_id: str) -> str:
    if not _is_hex64(semantic_id):
        raise TeacherLabelsError("semantic_id_invalid")
    return "holdout" if int(semantic_id[:8], 16) % 10 < 4 else "seed"


def _load_ledger_tasks(worktree_root: Path) -> dict[str, str]:
    """Index the task of every Guardian evidence run recorded in the ledger.

    The ledger also carries rows that are not Guardian evidence runs, such as
    the imported and replayed L3 shadow rows, which legitimately summarize many
    tasks at once or hide them entirely.  Only rows that bind their own run
    artifact directory and carry a Guardian identity can produce evidence, so
    only those are required to name exactly one task.
    """

    path = worktree_root / RUN_LEDGER_RELATIVE_PATH
    raw = _safe_read(path, limit=_MAX_TRACKED_FILE_BYTES)
    tasks_by_run: dict[str, str] = {}
    try:
        lines = raw.decode("utf-8").splitlines()
        for line in lines:
            if not line.strip():
                continue
            record = json.loads(line)
            if not isinstance(record, dict):
                raise TeacherLabelsError("run_ledger_invalid")
            run_id = record.get("run_id")
            if not isinstance(run_id, str):
                continue
            configuration = record.get("config")
            if (
                record.get("artifacts") != f"eval-data/runs/{run_id}"
                or not isinstance(configuration, dict)
                or not isinstance(configuration.get("effective_guardian_model"), str)
                or not isinstance(configuration.get("guardian_effort"), str)
            ):
                continue
            tasks = record.get("tasks")
            if not isinstance(tasks, list) or len(tasks) != 1:
                raise TeacherLabelsError("run_task_not_unique", {"run_id": run_id})
            task_id = tasks[0].get("task_id") if isinstance(tasks[0], dict) else None
            if not isinstance(task_id, str) or not task_id:
                raise TeacherLabelsError("run_task_id_invalid", {"run_id": run_id})
            if run_id in tasks_by_run:
                raise TeacherLabelsError("run_ledger_duplicate", {"run_id": run_id})
            tasks_by_run[run_id] = task_id
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TeacherLabelsError("run_ledger_invalid") from exc
    return tasks_by_run


def _validate_census(worktree_root: Path) -> tuple[dict[str, int], dict[str, Any]]:
    path = worktree_root / CENSUS_RELATIVE_PATH
    value, raw = _load_json(path)
    if not isinstance(value, dict):
        raise TeacherLabelsError("census_invalid")
    required = {
        "schema_version",
        "purpose",
        "status",
        "missing_counts",
        "identity",
        "anchor",
        "records",
        "summary",
        "digest",
    }
    if (
        set(value) != required
        or type(value["schema_version"]) is not int
        or value["schema_version"] != token_census.CENSUS_SCHEMA_VERSION
        or value["status"] != "complete"
        or type(value["missing_counts"]) is not int
        or value["missing_counts"] != 0
        or value["digest"] != EXPECTED_CENSUS_DIGEST
        or value["digest"]
        != _canonical_sha256({key: item for key, item in value.items() if key != "digest"})
        or not isinstance(value["records"], list)
        or len(value["records"]) != EXPECTED_SOURCE_INSTANCES
    ):
        raise TeacherLabelsError("census_contract_mismatch")
    counts: dict[str, int] = {}
    for record in value["records"]:
        fits = record.get("fits") if isinstance(record, dict) else None
        if (
            not isinstance(record, dict)
            or set(record) != {"e_final_sha256", "status", "input_tokens", "fits"}
            or not _is_hex64(record["e_final_sha256"])
            or record["status"] != "counted"
            or not isinstance(record["input_tokens"], int)
            or isinstance(record["input_tokens"], bool)
            or record["input_tokens"] <= 0
            or not isinstance(fits, dict)
            or set(fits) != {"4k", "8k"}
            or any(not isinstance(fit, bool) for fit in fits.values())
            or fits["4k"] != (record["input_tokens"] + MAX_OUTPUT_TOKENS <= 4096)
            or fits["8k"] != (record["input_tokens"] + MAX_OUTPUT_TOKENS <= 8192)
            or record["e_final_sha256"] in counts
        ):
            raise TeacherLabelsError("census_record_invalid")
        counts[record["e_final_sha256"]] = record["input_tokens"]
    return counts, {
        "schema_version": value["schema_version"],
        "digest": value["digest"],
        "file_sha256": _sha256(raw),
    }


def _read_meta(
    source_root: Path,
    relative_path: str,
    *,
    expected_model: str,
    expected_effort: str,
) -> tuple[dict[str, Any], str]:
    e_final_path = source_root / relative_path
    meta_path = e_final_path.with_name("meta.json")
    try:
        before = os.lstat(meta_path)
        raw = read_production_evidence_file(source_root, meta_path)
        after = os.lstat(meta_path)
    except (OSError, TerminalBenchRunError) as exc:
        raise TeacherLabelsError("evidence_meta_read_failed") from exc
    if _identity(before) != _identity(after):
        raise TeacherLabelsError("evidence_meta_changed_while_reading")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise TeacherLabelsError("evidence_meta_invalid") from exc
    if not isinstance(value, dict):
        raise TeacherLabelsError("evidence_meta_invalid")
    review_id = value.get("review_id")
    if not isinstance(review_id, str) or not review_id:
        raise TeacherLabelsError("evidence_meta_invalid")
    try:
        validate_production_guardian_meta(
            value,
            review_id=review_id,
            expected_model=expected_model,
            expected_effort=expected_effort,
        )
    except TerminalBenchRunError as exc:
        raise TeacherLabelsError("evidence_meta_invalid") from exc
    return value, _sha256(raw)


def _previous_representatives(path: Path | None) -> dict[str, tuple[str, str | None]]:
    if path is None:
        return {}
    value, _raw = _load_json(path, private=True)
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != MANIFEST_SCHEMA_VERSION
        or value.get("identity_rule_version") != IDENTITY_RULE_VERSION
        or value.get("representative_rule_version") != REPRESENTATIVE_RULE_VERSION
        or not isinstance(value.get("instances"), list)
    ):
        raise TeacherLabelsError("previous_manifest_invalid")
    result: dict[str, tuple[str, str | None]] = {}
    for item in value["instances"]:
        if not isinstance(item, dict):
            raise TeacherLabelsError("previous_manifest_invalid")
        semantic_id = item.get("semantic_id")
        representative = item.get("semantic_representative_e_final_sha256")
        label_representative = item.get("label_representative_e_final_sha256")
        if (
            not _is_hex64(semantic_id)
            or not _is_hex64(representative)
            or (label_representative is not None and not _is_hex64(label_representative))
        ):
            raise TeacherLabelsError("previous_manifest_invalid")
        frozen = (representative, label_representative)
        if semantic_id in result and result[semantic_id] != frozen:
            raise TeacherLabelsError("previous_manifest_conflict")
        result[semantic_id] = frozen
    return result


def _choose_representatives(
    instances: Sequence[PreparedInstance],
    previous: Mapping[str, tuple[str, str | None]],
) -> tuple[dict[str, str], dict[str, str | None]]:
    groups: dict[str, list[PreparedInstance]] = {}
    for item in instances:
        groups.setdefault(item.semantic_id, []).append(item)
    semantic_representatives: dict[str, str] = {}
    label_representatives: dict[str, str | None] = {}
    for semantic_id, members in groups.items():
        member_hashes = {member.e_final_sha256 for member in members}
        fit_hashes = {member.e_final_sha256 for member in members if member.fits_12k}
        frozen = previous.get(semantic_id)
        if frozen is None:
            semantic_representatives[semantic_id] = min(member_hashes)
            label_representatives[semantic_id] = min(fit_hashes) if fit_hashes else None
            continue
        if frozen[0] not in member_hashes:
            raise TeacherLabelsError("frozen_semantic_representative_missing")
        if frozen[1] is not None and frozen[1] not in fit_hashes:
            raise TeacherLabelsError("frozen_label_representative_missing")
        semantic_representatives[semantic_id] = frozen[0]
        label_representatives[semantic_id] = (
            frozen[1] if frozen[1] is not None else (min(fit_hashes) if fit_hashes else None)
        )
    return semantic_representatives, label_representatives


def _usage(partition: str) -> str:
    if partition == "holdout":
        return "holdout_evaluation_only"
    return "seed_evaluation_and_future_synthesis_reference"


def _build_instance_records(
    instances: Sequence[PreparedInstance],
    previous: Mapping[str, tuple[str, str | None]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    semantic_reps, label_reps = _choose_representatives(instances, previous)
    records: list[dict[str, Any]] = []
    outbound: list[dict[str, Any]] = []
    for item in sorted(instances, key=lambda value: value.e_final_sha256):
        semantic_rep = semantic_reps[item.semantic_id]
        label_rep = label_reps[item.semantic_id]
        selected = label_rep == item.e_final_sha256
        if selected:
            exclusion_reason = None
        elif not item.fits_12k:
            exclusion_reason = "input_plus_output_exceeds_12288"
        else:
            exclusion_reason = "semantic_duplicate"
        record = {
            "source_instance_id": item.e_final_sha256,
            "source_relative_path": item.source_relative_path,
            "run_id": item.run_id,
            "review_id": item.review_id,
            "task_id": item.task_id,
            "e_final_sha256": item.e_final_sha256,
            "meta_sha256": item.meta_sha256,
            "request_shape": item.request_shape,
            "static_payload_sha256": item.static_payload_sha256,
            "action_fingerprint_sha256": item.action_fingerprint_sha256,
            "semantic_id": item.semantic_id,
            "partition": item.partition,
            "usage": _usage(item.partition),
            "semantic_representative_e_final_sha256": semantic_rep,
            "label_representative_e_final_sha256": label_rep,
            "is_semantic_representative": semantic_rep == item.e_final_sha256,
            "is_label_representative": selected,
            "input_tokens": item.input_tokens,
            "fits_12k": item.fits_12k,
            "selected": selected,
            "exclusion_reason": exclusion_reason,
        }
        records.append(record)
        if selected:
            outbound.append(
                {
                    "schema_version": OUTBOUND_SCHEMA_VERSION,
                    "batch_id": "",  # filled after the batch id is known
                    "semantic_id": item.semantic_id,
                    "representative_e_final_sha256": item.e_final_sha256,
                    "static_payload_sha256": item.static_payload_sha256,
                    "request_shape": item.request_shape,
                    "partition": item.partition,
                    "usage": _usage(item.partition),
                    "prompt_version": PROMPT_VERSION,
                    "prompt_sha256": "",
                    "label_schema_version": LABEL_SCHEMA_VERSION,
                    "label_schema_sha256": "",
                    "canonical_payload": item.canonical_payload,
                }
            )
    return records, sorted(outbound, key=lambda value: value["semantic_id"])


def build_batch_artifacts(
    *,
    worktree_root: Path,
    source_root: Path,
    batch_id: str,
    created_date: str,
    previous_manifest: Path | None = None,
) -> dict[str, Any]:
    """Recompute the frozen batch artifacts from the real production archive.

    This performs every source read, canonical payload build, semantic identity
    and partition derivation that ``prepare_batch`` performs, but writes
    nothing.  A later consumer can therefore re-derive the batch and require
    byte identity with the frozen private files.
    """

    if _BATCH_ID.fullmatch(batch_id) is None:
        raise TeacherLabelsError("batch_id_invalid")
    _validate_date(created_date)
    paths = RepoPaths.discover(worktree_root)
    if paths.worktree_root != worktree_root.resolve(strict=True):
        raise TeacherLabelsError("worktree_root_mismatch")
    if paths.common_root != source_root.resolve(strict=True):
        raise TeacherLabelsError("source_root_mismatch")

    prompt_raw = _safe_read(
        worktree_root / PROMPT_RELATIVE_PATH, limit=_MAX_TRACKED_FILE_BYTES
    )
    if f"Version: `{PROMPT_VERSION}`".encode() not in prompt_raw:
        raise TeacherLabelsError("prompt_version_mismatch")
    schema_value, schema_raw = _load_json(worktree_root / LABEL_SCHEMA_RELATIVE_PATH)
    if (
        not isinstance(schema_value, dict)
        or schema_value.get("title") != "RONDO Sol teacher label v1"
    ):
        raise TeacherLabelsError("label_schema_mismatch")
    prompt_sha = _sha256(prompt_raw)
    schema_sha = _sha256(schema_raw)
    token_counts, census_identity = _validate_census(worktree_root)
    ledger_tasks = _load_ledger_tasks(worktree_root)
    config = RuntimeConfig(paths, {}, "0" * 64)
    ledger_identities = token_census._expected_guardian_identities(config)
    try:
        evidence_inputs = token_census.collect_evidence_inputs(
            config, expected_count=EXPECTED_SOURCE_INSTANCES
        )
    except token_census.CensusError as exc:
        raise TeacherLabelsError(exc.code, exc.facts) from exc
    if {item.e_final_sha256 for item in evidence_inputs} != set(token_counts):
        raise TeacherLabelsError("census_evidence_set_mismatch")

    prepared: list[PreparedInstance] = []
    for item in evidence_inputs:
        run_id = Path(item.relative_path).parts[2]
        task_id = ledger_tasks.get(run_id)
        if task_id is None:
            raise TeacherLabelsError("evidence_task_missing", {"run_id": run_id})
        expected_identity = ledger_identities.get(run_id)
        if expected_identity is None:
            raise TeacherLabelsError("evidence_identity_missing", {"run_id": run_id})
        meta, meta_sha = _read_meta(
            source_root,
            item.relative_path,
            expected_model=expected_identity[0],
            expected_effort=expected_identity[1],
        )
        review_id = meta["review_id"]
        sol_bytes = static_payload_bytes_for_consumer(item.payload, "sol-static")
        local_bytes = static_payload_bytes_for_consumer(item.payload, "local-static")
        if sol_bytes != local_bytes:
            raise TeacherLabelsError("static_consumer_bytes_differ")
        action = extract_approval_action(item.payload.logical_payload)
        action_fingerprint, semantic_id = semantic_id_for(task_id, action)
        input_tokens = token_counts[item.e_final_sha256]
        prepared.append(
            PreparedInstance(
                source_relative_path=item.relative_path,
                run_id=run_id,
                review_id=review_id,
                task_id=task_id,
                e_final_sha256=item.e_final_sha256,
                meta_sha256=meta_sha,
                request_shape=item.request_shape,
                static_payload_sha256=_sha256(sol_bytes),
                action_fingerprint_sha256=action_fingerprint,
                semantic_id=semantic_id,
                partition=partition_for(semantic_id),
                input_tokens=input_tokens,
                fits_12k=input_tokens + MAX_OUTPUT_TOKENS <= CONTEXT_SIZE,
                canonical_payload=item.payload.logical_payload,
            )
        )

    previous = _previous_representatives(previous_manifest)
    records, outbound = _build_instance_records(prepared, previous)
    for item in outbound:
        item["batch_id"] = batch_id
        item["prompt_sha256"] = prompt_sha
        item["label_schema_sha256"] = schema_sha

    semantic_count = len({item.semantic_id for item in prepared})
    duplicate_count = len(prepared) - semantic_count
    fit_count = sum(item.fits_12k for item in prepared)
    selected_count = len(outbound)
    observed = {
        "source_instances": len(prepared),
        "semantic_unique": semantic_count,
        "duplicate_instances": duplicate_count,
        "fit_12k_instances": fit_count,
        "selected_labels": selected_count,
    }
    expected = {
        "source_instances": EXPECTED_SOURCE_INSTANCES,
        "semantic_unique": EXPECTED_SEMANTIC_IDENTITIES,
        "duplicate_instances": EXPECTED_DUPLICATE_INSTANCES,
        "fit_12k_instances": EXPECTED_12K_FIT_INSTANCES,
        "selected_labels": EXPECTED_SELECTED_LABELS,
    }
    if observed != expected:
        raise TeacherLabelsError(
            "plan_032_precheck_mismatch", {"expected": expected, "observed": observed}
        )
    selected_partitions = Counter(item["partition"] for item in outbound)
    all_partitions = Counter({
        partition: len({item.semantic_id for item in prepared if item.partition == partition})
        for partition in ("seed", "holdout")
    })
    exclusions = Counter(
        record["exclusion_reason"]
        for record in records
        if record["exclusion_reason"] is not None
    )
    counts = {
        **observed,
        "semantic_partitions": {
            "seed": all_partitions["seed"],
            "holdout": all_partitions["holdout"],
        },
        "selected_partitions": {
            "seed": selected_partitions["seed"],
            "holdout": selected_partitions["holdout"],
        },
        "exclusions": dict(sorted(exclusions.items())),
    }
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "batch_id": batch_id,
        "purpose": "first point-in-time gpt-5.6-sol teacher labels for L3 static replay",
        "created_date": created_date,
        "identity_rule_version": IDENTITY_RULE_VERSION,
        "representative_rule_version": REPRESENTATIVE_RULE_VERSION,
        "static_payload_schema_version": STATIC_PAYLOAD_SCHEMA_VERSION,
        "static_decision_schema_name": STATIC_DECISION_SCHEMA_NAME,
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha,
        "label_schema_version": LABEL_SCHEMA_VERSION,
        "label_schema_sha256": schema_sha,
        "census": census_identity,
        "context_contract": {
            "context_size": CONTEXT_SIZE,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "fit_rule": "input_tokens + max_output_tokens <= context_size",
        },
        "usage_contract": {
            "seed": "evaluation and future synthesis reference; real evidence itself is not training data",
            "holdout": "evaluation only; forbidden from synthesis context, synthesis prompt, synthesis-time reference, and training",
        },
        "counts": counts,
        "instances": records,
    }
    manifest_raw = _json_file_bytes(manifest)
    outbound_raw = _jsonl_bytes(outbound)
    receipt = {
        "schema_version": PREPARE_RECEIPT_SCHEMA_VERSION,
        "batch_id": batch_id,
        "created_date": created_date,
        "manifest_sha256": _sha256(manifest_raw),
        "outbound_sha256": _sha256(outbound_raw),
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": prompt_sha,
        "label_schema_version": LABEL_SCHEMA_VERSION,
        "label_schema_sha256": schema_sha,
        "census_digest": census_identity["digest"],
        "census_file_sha256": census_identity["file_sha256"],
        "selected_semantic_ids_sha256": _canonical_sha256(
            sorted(item["semantic_id"] for item in outbound)
        ),
    }
    receipt_raw = _json_file_bytes(receipt)
    return {
        "batch_id": batch_id,
        "counts": counts,
        "prompt_sha256": prompt_sha,
        "label_schema_sha256": schema_sha,
        "manifest": manifest,
        "manifest_raw": manifest_raw,
        "outbound": outbound,
        "outbound_raw": outbound_raw,
        "prepare_receipt": receipt,
        "prepare_receipt_raw": receipt_raw,
    }


def prepare_batch(
    *,
    worktree_root: Path,
    source_root: Path,
    private_dir: Path,
    batch_id: str,
    created_date: str,
    previous_manifest: Path | None = None,
) -> dict[str, Any]:
    artifacts = build_batch_artifacts(
        worktree_root=worktree_root,
        source_root=source_root,
        batch_id=batch_id,
        created_date=created_date,
        previous_manifest=previous_manifest,
    )
    manifest_raw = artifacts["manifest_raw"]
    outbound_raw = artifacts["outbound_raw"]
    receipt_raw = artifacts["prepare_receipt_raw"]
    _prepare_private_directory(source_root, private_dir, batch_id)
    _write_exclusive(private_dir / "manifest.json", manifest_raw, mode=0o600)
    _write_exclusive(private_dir / "outbound.jsonl", outbound_raw, mode=0o600)
    _write_exclusive(private_dir / "prepare-receipt.json", receipt_raw, mode=0o600)
    return {
        "status": "prepared",
        "batch_id": batch_id,
        "counts": artifacts["counts"],
        "prompt": {
            "version": PROMPT_VERSION,
            "sha256": artifacts["prompt_sha256"],
        },
        "label_schema": {
            "version": LABEL_SCHEMA_VERSION,
            "sha256": artifacts["label_schema_sha256"],
        },
        "manifest": {
            "version": MANIFEST_SCHEMA_VERSION,
            "sha256": _sha256(manifest_raw),
        },
        "outbound_sha256": _sha256(outbound_raw),
        "prepare_receipt_sha256": _sha256(receipt_raw),
        "private_directory": private_dir.as_posix(),
    }


def _manifest_selected(manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    manifest_fields = {
        "schema_version",
        "batch_id",
        "purpose",
        "created_date",
        "identity_rule_version",
        "representative_rule_version",
        "static_payload_schema_version",
        "static_decision_schema_name",
        "prompt_version",
        "prompt_sha256",
        "label_schema_version",
        "label_schema_sha256",
        "census",
        "context_contract",
        "usage_contract",
        "counts",
        "instances",
    }
    instance_fields = {
        "source_instance_id",
        "source_relative_path",
        "run_id",
        "review_id",
        "task_id",
        "e_final_sha256",
        "meta_sha256",
        "request_shape",
        "static_payload_sha256",
        "action_fingerprint_sha256",
        "semantic_id",
        "partition",
        "usage",
        "semantic_representative_e_final_sha256",
        "label_representative_e_final_sha256",
        "is_semantic_representative",
        "is_label_representative",
        "input_tokens",
        "fits_12k",
        "selected",
        "exclusion_reason",
    }
    usage_contract = {
        "seed": "evaluation and future synthesis reference; real evidence itself is not training data",
        "holdout": "evaluation only; forbidden from synthesis context, synthesis prompt, synthesis-time reference, and training",
    }
    if (
        not isinstance(manifest, dict)
        or set(manifest) != manifest_fields
        or type(manifest["schema_version"]) is not int
        or manifest["schema_version"] != MANIFEST_SCHEMA_VERSION
        or not isinstance(manifest["batch_id"], str)
        or _BATCH_ID.fullmatch(manifest["batch_id"]) is None
        or not isinstance(manifest["created_date"], str)
    ):
        raise TeacherLabelsError("manifest_contract_mismatch")
    _validate_date(manifest["created_date"])
    if (
        manifest["purpose"]
        != "first point-in-time gpt-5.6-sol teacher labels for L3 static replay"
        or manifest["identity_rule_version"] != IDENTITY_RULE_VERSION
        or manifest["representative_rule_version"] != REPRESENTATIVE_RULE_VERSION
        or type(manifest["static_payload_schema_version"]) is not int
        or manifest["static_payload_schema_version"] != STATIC_PAYLOAD_SCHEMA_VERSION
        or manifest["static_decision_schema_name"] != STATIC_DECISION_SCHEMA_NAME
        or manifest["prompt_version"] != PROMPT_VERSION
        or not _is_hex64(manifest["prompt_sha256"])
        or type(manifest["label_schema_version"]) is not int
        or manifest["label_schema_version"] != LABEL_SCHEMA_VERSION
        or not _is_hex64(manifest["label_schema_sha256"])
        or manifest["context_contract"]
        != {
            "context_size": CONTEXT_SIZE,
            "max_output_tokens": MAX_OUTPUT_TOKENS,
            "fit_rule": "input_tokens + max_output_tokens <= context_size",
        }
        or manifest["usage_contract"] != usage_contract
        or not isinstance(manifest["census"], dict)
        or set(manifest["census"]) != {"schema_version", "digest", "file_sha256"}
        or type(manifest["census"]["schema_version"]) is not int
        or manifest["census"]["schema_version"] != token_census.CENSUS_SCHEMA_VERSION
        or manifest["census"]["digest"] != EXPECTED_CENSUS_DIGEST
        or not _is_hex64(manifest["census"]["file_sha256"])
        or not isinstance(manifest["instances"], list)
        or len(manifest["instances"]) != EXPECTED_SOURCE_INSTANCES
    ):
        raise TeacherLabelsError("manifest_contract_mismatch")

    selected: dict[str, dict[str, Any]] = {}
    partitions: dict[str, str] = {}
    by_e_final: dict[str, dict[str, Any]] = {}
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in manifest["instances"]:
        if not isinstance(item, dict) or set(item) != instance_fields:
            raise TeacherLabelsError("manifest_instance_invalid")
        source_path = item["source_relative_path"]
        path_parts = Path(source_path).parts if isinstance(source_path, str) else ()
        string_fields = ("run_id", "review_id", "task_id", "request_shape")
        if (
            item["source_instance_id"] != item["e_final_sha256"]
            or any(not _is_hex64(item[field]) for field in (
                "e_final_sha256",
                "meta_sha256",
                "static_payload_sha256",
                "action_fingerprint_sha256",
                "semantic_id",
                "semantic_representative_e_final_sha256",
            ))
            or (
                item["label_representative_e_final_sha256"] is not None
                and not _is_hex64(item["label_representative_e_final_sha256"])
            )
            or not path_parts
            or Path(source_path).is_absolute()
            or ".." in path_parts
            or len(path_parts) != 6
            or path_parts[:2] != ("eval-data", "runs")
            or path_parts[2] != item["run_id"]
            or path_parts[3] != "guardian-evidence"
            or re.fullmatch(r"[0-9]{4}", path_parts[4]) is None
            or path_parts[5] != "E_final.json"
            or any(not isinstance(item[field], str) or not item[field] for field in string_fields)
            or item["request_shape"] != EXPECTED_REQUEST_SHAPE
            or item["semantic_id"]
            != _semantic_id_from_fingerprint(
                item["task_id"], item["action_fingerprint_sha256"]
            )
            or any(type(item[field]) is not bool for field in (
                "is_semantic_representative",
                "is_label_representative",
                "fits_12k",
                "selected",
            ))
            or not isinstance(item["input_tokens"], int)
            or isinstance(item["input_tokens"], bool)
            or item["input_tokens"] <= 0
            or item["fits_12k"]
            != (item["input_tokens"] + MAX_OUTPUT_TOKENS <= CONTEXT_SIZE)
            or item["e_final_sha256"] in by_e_final
        ):
            raise TeacherLabelsError("manifest_instance_invalid")
        semantic_id = item["semantic_id"]
        partition = item.get("partition")
        if partition != partition_for(semantic_id):
            raise TeacherLabelsError("manifest_partition_invalid")
        prior = partitions.setdefault(semantic_id, partition)
        if prior != partition:
            raise TeacherLabelsError("manifest_partition_conflict")
        if item["usage"] != _usage(partition):
            raise TeacherLabelsError("manifest_usage_invalid")
        by_e_final[item["e_final_sha256"]] = item
        groups.setdefault(semantic_id, []).append(item)
        if item.get("selected") is True:
            if semantic_id in selected:
                raise TeacherLabelsError("manifest_selected_duplicate")
            if (
                item.get("fits_12k") is not True
                or item.get("is_label_representative") is not True
                or item.get("exclusion_reason") is not None
                or item.get("usage") != _usage(partition)
            ):
                raise TeacherLabelsError("manifest_selected_invalid")
            selected[semantic_id] = item

    for semantic_id, members in groups.items():
        member_hashes = {item["e_final_sha256"] for item in members}
        fit_hashes = {item["e_final_sha256"] for item in members if item["fits_12k"]}
        semantic_reps = {item["semantic_representative_e_final_sha256"] for item in members}
        label_reps = {item["label_representative_e_final_sha256"] for item in members}
        if (
            len(semantic_reps) != 1
            or next(iter(semantic_reps)) not in member_hashes
            or len(label_reps) != 1
        ):
            raise TeacherLabelsError("manifest_representative_invalid")
        semantic_rep = next(iter(semantic_reps))
        label_rep = next(iter(label_reps))
        if (label_rep is None) != (not fit_hashes) or (
            label_rep is not None and label_rep not in fit_hashes
        ):
            raise TeacherLabelsError("manifest_label_representative_invalid")
        for item in members:
            expected_selected = item["e_final_sha256"] == label_rep
            if (
                item["is_semantic_representative"]
                != (item["e_final_sha256"] == semantic_rep)
                or item["is_label_representative"] != expected_selected
                or item["selected"] != expected_selected
            ):
                raise TeacherLabelsError("manifest_representative_flags_invalid")
            expected_exclusion = (
                None
                if expected_selected
                else "input_plus_output_exceeds_12288"
                if not item["fits_12k"]
                else "semantic_duplicate"
            )
            if item["exclusion_reason"] != expected_exclusion:
                raise TeacherLabelsError("manifest_exclusion_invalid")

    if len(selected) != EXPECTED_SELECTED_LABELS:
        raise TeacherLabelsError("manifest_selected_count_invalid")
    semantic_partitions = Counter(partitions.values())
    selected_partitions = Counter(item["partition"] for item in selected.values())
    exclusions = Counter(
        item["exclusion_reason"]
        for item in manifest["instances"]
        if item["exclusion_reason"] is not None
    )
    expected_counts = {
        "source_instances": EXPECTED_SOURCE_INSTANCES,
        "semantic_unique": len(groups),
        "duplicate_instances": len(manifest["instances"]) - len(groups),
        "fit_12k_instances": sum(item["fits_12k"] for item in manifest["instances"]),
        "selected_labels": len(selected),
        "semantic_partitions": {
            "seed": semantic_partitions["seed"],
            "holdout": semantic_partitions["holdout"],
        },
        "selected_partitions": {
            "seed": selected_partitions["seed"],
            "holdout": selected_partitions["holdout"],
        },
        "exclusions": dict(sorted(exclusions.items())),
    }
    if (
        manifest["counts"] != expected_counts
        or expected_counts["semantic_unique"] != EXPECTED_SEMANTIC_IDENTITIES
        or expected_counts["duplicate_instances"] != EXPECTED_DUPLICATE_INSTANCES
        or expected_counts["fit_12k_instances"] != EXPECTED_12K_FIT_INSTANCES
    ):
        raise TeacherLabelsError("manifest_counts_invalid")
    return selected


def _validate_outbound(
    outbound: Sequence[Any],
    manifest: Mapping[str, Any],
    selected: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    expected_fields = {
        "schema_version",
        "batch_id",
        "semantic_id",
        "representative_e_final_sha256",
        "static_payload_sha256",
        "request_shape",
        "partition",
        "usage",
        "prompt_version",
        "prompt_sha256",
        "label_schema_version",
        "label_schema_sha256",
        "canonical_payload",
    }
    by_id: dict[str, dict[str, Any]] = {}
    for row in outbound:
        if not isinstance(row, dict) or set(row) != expected_fields:
            raise TeacherLabelsError("outbound_row_fields_invalid")
        semantic_id = row["semantic_id"]
        source = selected.get(semantic_id)
        if source is None or semantic_id in by_id:
            raise TeacherLabelsError("outbound_identity_set_invalid")
        if (
            type(row["schema_version"]) is not int
            or type(row["label_schema_version"]) is not int
            or row["schema_version"] != OUTBOUND_SCHEMA_VERSION
            or row["batch_id"] != manifest["batch_id"]
            or row["representative_e_final_sha256"] != source["e_final_sha256"]
            or row["static_payload_sha256"] != source["static_payload_sha256"]
            or row["request_shape"] != source["request_shape"]
            or row["partition"] != source["partition"]
            or row["usage"] != source["usage"]
            or row["prompt_version"] != manifest["prompt_version"]
            or row["prompt_sha256"] != manifest["prompt_sha256"]
            or row["label_schema_version"] != manifest["label_schema_version"]
            or row["label_schema_sha256"] != manifest["label_schema_sha256"]
            or not isinstance(row["canonical_payload"], dict)
        ):
            raise TeacherLabelsError("outbound_binding_invalid")
        canonical = _canonical_bytes(row["canonical_payload"])
        if _sha256(canonical) != row["static_payload_sha256"]:
            raise TeacherLabelsError("outbound_payload_sha256_mismatch")
        action = extract_approval_action(row["canonical_payload"])
        action_fingerprint, recomputed_semantic_id = semantic_id_for(
            source["task_id"], action
        )
        if (
            action_fingerprint != source["action_fingerprint_sha256"]
            or recomputed_semantic_id != semantic_id
        ):
            raise TeacherLabelsError("outbound_semantic_identity_mismatch")
        policy = row["canonical_payload"].get("guardian_policy")
        if not isinstance(policy, str):
            raise TeacherLabelsError("outbound_policy_invalid")
        payload = StaticApprovalPayload(
            PolicyIdentity(
                STATIC_PAYLOAD_SCHEMA_VERSION,
                row["request_shape"],
                _sha256(policy.encode("utf-8")),
                "known",
            ),
            canonical,
            row["canonical_payload"],
        )
        try:
            sol_bytes = static_payload_bytes_for_consumer(payload, "sol-static")
            local_bytes = static_payload_bytes_for_consumer(payload, "local-static")
        except EvidenceError as exc:
            raise TeacherLabelsError("outbound_static_payload_invalid") from exc
        if sol_bytes != local_bytes:
            raise TeacherLabelsError("outbound_consumer_bytes_differ")
        by_id[semantic_id] = row
    if set(by_id) != set(selected):
        raise TeacherLabelsError("outbound_identity_set_invalid")
    return by_id


def _validate_frozen_batch(
    *, worktree_root: Path, private_dir: Path
) -> tuple[
    dict[str, Any],
    bytes,
    dict[str, dict[str, Any]],
    list[Any],
    bytes,
    bytes,
]:
    """Bind verify/summarize to prepare output and current tracked contracts."""

    paths = RepoPaths.discover(worktree_root)
    if paths.worktree_root != worktree_root.resolve(strict=True):
        raise TeacherLabelsError("worktree_root_mismatch")
    manifest, manifest_raw = _load_json(private_dir / "manifest.json", private=True)
    selected = _manifest_selected(manifest)
    outbound, outbound_raw = _load_jsonl(private_dir / "outbound.jsonl", private=True)
    _validate_outbound(outbound, manifest, selected)

    prompt_raw = _safe_read(
        worktree_root / PROMPT_RELATIVE_PATH, limit=_MAX_TRACKED_FILE_BYTES
    )
    schema_value, schema_raw = _load_json(worktree_root / LABEL_SCHEMA_RELATIVE_PATH)
    _counts, census_identity = _validate_census(worktree_root)
    if (
        f"Version: `{PROMPT_VERSION}`".encode() not in prompt_raw
        or not isinstance(schema_value, dict)
        or schema_value.get("title") != "RONDO Sol teacher label v1"
        or manifest["prompt_sha256"] != _sha256(prompt_raw)
        or manifest["label_schema_sha256"] != _sha256(schema_raw)
        or manifest["census"] != census_identity
    ):
        raise TeacherLabelsError("tracked_contract_drift")

    receipt, receipt_raw = _load_json(
        private_dir / "prepare-receipt.json", private=True
    )
    expected_receipt = {
        "schema_version": PREPARE_RECEIPT_SCHEMA_VERSION,
        "batch_id": manifest["batch_id"],
        "created_date": manifest["created_date"],
        "manifest_sha256": _sha256(manifest_raw),
        "outbound_sha256": _sha256(outbound_raw),
        "prompt_version": manifest["prompt_version"],
        "prompt_sha256": manifest["prompt_sha256"],
        "label_schema_version": manifest["label_schema_version"],
        "label_schema_sha256": manifest["label_schema_sha256"],
        "census_digest": manifest["census"]["digest"],
        "census_file_sha256": manifest["census"]["file_sha256"],
        "selected_semantic_ids_sha256": _canonical_sha256(sorted(selected)),
    }
    if (
        type(receipt.get("schema_version")) is not int
        or receipt != expected_receipt
    ):
        raise TeacherLabelsError("prepare_receipt_binding_invalid")
    return manifest, manifest_raw, selected, outbound, outbound_raw, receipt_raw


def validate_raw_responses(
    responses: Sequence[Any], selected_ids: set[str]
) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for response in responses:
        if not isinstance(response, dict) or set(response) != {"semantic_id", "decision"}:
            raise TeacherLabelsError("raw_response_fields_invalid")
        semantic_id = response["semantic_id"]
        if semantic_id not in selected_ids or semantic_id in by_id:
            raise TeacherLabelsError("raw_response_identity_invalid")
        try:
            decision = validate_static_decision(response["decision"])
        except EvidenceError as exc:
            raise TeacherLabelsError("raw_response_schema_invalid") from exc
        by_id[semantic_id] = {"semantic_id": semantic_id, "decision": decision}
    if set(by_id) != selected_ids:
        raise TeacherLabelsError("raw_response_set_incomplete")
    return by_id


def validate_attempts(
    attempts: Sequence[Any], selected_ids: set[str]
) -> dict[str, dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    expected_fields = {"schema_version", "semantic_id", "attempt", "retry_reason"}
    for value in attempts:
        if not isinstance(value, dict) or set(value) != expected_fields:
            raise TeacherLabelsError("attempt_fields_invalid")
        semantic_id = value["semantic_id"]
        attempt = value["attempt"]
        retry_reason = value["retry_reason"]
        if (
            type(value["schema_version"]) is not int
            or type(attempt) is not int
            or value["schema_version"] != ATTEMPT_SCHEMA_VERSION
            or semantic_id not in selected_ids
            or semantic_id in by_id
            or attempt not in {1, 2}
            or (attempt == 1 and retry_reason is not None)
            or (
                attempt == 2
                and retry_reason not in {"schema_invalid", "transport_failed"}
            )
        ):
            raise TeacherLabelsError("attempt_provenance_invalid")
        by_id[semantic_id] = value
    if set(by_id) != selected_ids:
        raise TeacherLabelsError("attempt_set_incomplete")
    return by_id


def record_raw_responses(
    *,
    worktree_root: Path,
    private_dir: Path,
    input_lines: Sequence[str],
    retry_reasons: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    _require_private_directory(private_dir)
    _manifest, _manifest_raw, selected, _outbound, _outbound_raw, _receipt_raw = (
        _validate_frozen_batch(worktree_root=worktree_root, private_dir=private_dir)
    )
    values: list[Any] = []
    for line in input_lines:
        if not line.strip():
            raise TeacherLabelsError("raw_response_blank_line")
        try:
            values.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise TeacherLabelsError("raw_response_json_invalid") from exc
    selected_ids = set(selected)
    validate_raw_responses(values, selected_ids)
    retries = dict(retry_reasons or {})
    if set(retries) - selected_ids or any(
        reason not in {"schema_invalid", "transport_failed"}
        for reason in retries.values()
    ):
        raise TeacherLabelsError("retry_reason_invalid")
    attempts = [
        {
            "schema_version": ATTEMPT_SCHEMA_VERSION,
            "semantic_id": semantic_id,
            "attempt": 2 if semantic_id in retries else 1,
            "retry_reason": retries.get(semantic_id),
        }
        for semantic_id in sorted(selected_ids)
    ]
    validate_attempts(attempts, selected_ids)
    # Preserve the exact model-return lines rather than reserializing them.
    raw = ("\n".join(input_lines) + "\n").encode("utf-8")
    attempts_raw = _jsonl_bytes(attempts)
    _write_exclusive(private_dir / "raw-responses.jsonl", raw, mode=0o600)
    _write_exclusive(private_dir / "attempts.jsonl", attempts_raw, mode=0o600)
    retry_counts = Counter(retries.values())
    return {
        "status": "recorded",
        "responses": len(values),
        "raw_responses_sha256": _sha256(raw),
        "attempts_sha256": _sha256(attempts_raw),
        "retries": {
            "schema_invalid": retry_counts["schema_invalid"],
            "transport_failed": retry_counts["transport_failed"],
            "total": len(retries),
        },
    }


def _read_terminated_lines(terminator: str) -> list[str]:
    """Read a complete batch without echoing private responses on a PTY."""

    original_terminal: list[Any] | None = None
    if sys.stdin.isatty():
        original_terminal = termios.tcgetattr(sys.stdin.fileno())
        private_terminal = list(original_terminal)
        private_terminal[3] &= ~termios.ECHO
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, private_terminal)
    try:
        lines: list[str] = []
        for line in sys.stdin:
            line = line.rstrip("\n")
            if line == terminator:
                return lines
            lines.append(line)
    finally:
        if original_terminal is not None:
            termios.tcsetattr(sys.stdin.fileno(), termios.TCSANOW, original_terminal)
    raise TeacherLabelsError("raw_response_terminator_missing")


def _validate_date(value: str) -> None:
    try:
        parsed = dt.date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise TeacherLabelsError("generated_date_invalid") from exc
    if parsed.isoformat() != value:
        raise TeacherLabelsError("generated_date_invalid")


def verify_batch(
    *,
    worktree_root: Path,
    private_dir: Path,
    teacher_model: str,
    generated_date: str,
) -> dict[str, Any]:
    _require_private_directory(private_dir)
    if teacher_model != TEACHER_MODEL:
        raise TeacherLabelsError("teacher_model_invalid")
    _validate_date(generated_date)
    manifest, manifest_raw, selected, _outbound, outbound_raw, receipt_raw = (
        _validate_frozen_batch(worktree_root=worktree_root, private_dir=private_dir)
    )
    raw_responses, raw_response_bytes = _load_jsonl(
        private_dir / "raw-responses.jsonl", private=True
    )
    decisions = validate_raw_responses(raw_responses, set(selected))
    attempt_rows, attempt_bytes = _load_jsonl(
        private_dir / "attempts.jsonl", private=True
    )
    attempts = validate_attempts(attempt_rows, set(selected))

    labels: list[dict[str, Any]] = []
    for semantic_id in sorted(selected):
        source = selected[semantic_id]
        labels.append(
            {
                "schema_version": LABEL_SCHEMA_VERSION,
                "batch_id": manifest["batch_id"],
                "semantic_id": semantic_id,
                "representative_e_final_sha256": source["e_final_sha256"],
                "static_payload_sha256": source["static_payload_sha256"],
                "partition": source["partition"],
                "usage": source["usage"],
                "prompt_version": manifest["prompt_version"],
                "prompt_sha256": manifest["prompt_sha256"],
                "teacher_model": teacher_model,
                "generated_date": generated_date,
                "attempt": attempts[semantic_id]["attempt"],
                "retry_reason": attempts[semantic_id]["retry_reason"],
                "decision": decisions[semantic_id]["decision"],
            }
        )
    labels_raw = _jsonl_bytes(labels)
    labels_sha = _sha256(labels_raw)
    labels_path = private_dir / "labels.jsonl"
    _write_or_match(labels_path, labels_raw, mode=0o600)

    selected_ids_sha = _canonical_sha256(sorted(selected))
    retry_counts = Counter(
        value["retry_reason"]
        for value in attempts.values()
        if value["retry_reason"] is not None
    )
    metadata = {
        "schema_version": IMPORT_METADATA_SCHEMA_VERSION,
        "batch_id": manifest["batch_id"],
        "status": "ready_for_l3",
        "ready_for_l3": True,
        "validation": "complete_set_format_identity_and_usage_checked",
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "manifest_sha256": _sha256(manifest_raw),
        "prepare_receipt_schema_version": PREPARE_RECEIPT_SCHEMA_VERSION,
        "prepare_receipt_sha256": _sha256(receipt_raw),
        "outbound_schema_version": OUTBOUND_SCHEMA_VERSION,
        "outbound_sha256": _sha256(outbound_raw),
        "raw_response_schema_version": RAW_RESPONSE_SCHEMA_VERSION,
        "raw_responses_sha256": _sha256(raw_response_bytes),
        "attempt_schema_version": ATTEMPT_SCHEMA_VERSION,
        "attempts_sha256": _sha256(attempt_bytes),
        "label_schema_version": LABEL_SCHEMA_VERSION,
        "label_schema_sha256": manifest["label_schema_sha256"],
        "labels_sha256": labels_sha,
        "selected_semantic_ids_sha256": selected_ids_sha,
        "label_count": len(labels),
        "prompt_version": manifest["prompt_version"],
        "prompt_sha256": manifest["prompt_sha256"],
        "teacher_model": teacher_model,
        "generated_dates": [generated_date],
        "retry_counts": {
            "schema_invalid": retry_counts["schema_invalid"],
            "transport_failed": retry_counts["transport_failed"],
            "total": sum(retry_counts.values()),
        },
        "usage_contract": manifest["usage_contract"],
        "publication": {
            "runs_jsonl_modified": False,
            "shadow_results_published": False,
        },
    }
    metadata_raw = _json_file_bytes(metadata)
    _write_or_match(private_dir / "import-metadata.json", metadata_raw, mode=0o600)
    return {
        "status": "ready_for_l3",
        "ready_for_l3": True,
        "labels": len(labels),
        "labels_sha256": labels_sha,
        "manifest_sha256": _sha256(manifest_raw),
        "import_metadata_sha256": _sha256(metadata_raw),
        "teacher_model": teacher_model,
        "generated_dates": [generated_date],
        "retries": metadata["retry_counts"],
    }


def build_summary(*, worktree_root: Path, private_dir: Path) -> dict[str, Any]:
    _require_private_directory(private_dir)
    metadata, metadata_raw = _load_json(
        private_dir / "import-metadata.json", private=True
    )
    if (
        not isinstance(metadata, dict)
        or metadata.get("teacher_model") != TEACHER_MODEL
        or not isinstance(metadata.get("generated_dates"), list)
        or len(metadata["generated_dates"]) != 1
        or not isinstance(metadata["generated_dates"][0], str)
    ):
        raise TeacherLabelsError("import_metadata_binding_invalid")
    # Re-run the complete frozen-input, decision, attempt, label and metadata
    # verification.  Existing outputs must byte-match the reconstructed values.
    verify_batch(
        worktree_root=worktree_root,
        private_dir=private_dir,
        teacher_model=TEACHER_MODEL,
        generated_date=metadata["generated_dates"][0],
    )
    manifest, manifest_raw, selected, _outbound, outbound_raw, receipt_raw = (
        _validate_frozen_batch(worktree_root=worktree_root, private_dir=private_dir)
    )
    _raw, raw_response_bytes = _load_jsonl(
        private_dir / "raw-responses.jsonl", private=True
    )
    _attempts, attempt_bytes = _load_jsonl(
        private_dir / "attempts.jsonl", private=True
    )
    _labels, labels_raw = _load_jsonl(private_dir / "labels.jsonl", private=True)
    metadata, metadata_raw = _load_json(
        private_dir / "import-metadata.json", private=True
    )
    if metadata.get("label_count") != len(selected):
        raise TeacherLabelsError("import_metadata_binding_invalid")
    return {
        "schema_version": SUMMARY_SCHEMA_VERSION,
        "batch_id": manifest["batch_id"],
        "purpose": "body-free lock for the first point-in-time Sol teacher-label batch",
        "status": "ready_for_l3",
        "ready_for_l3": True,
        "contracts": {
            "static_payload_schema_version": manifest["static_payload_schema_version"],
            "static_decision_schema_name": manifest["static_decision_schema_name"],
            "identity_rule_version": manifest["identity_rule_version"],
            "representative_rule_version": manifest["representative_rule_version"],
            "manifest_schema_version": manifest["schema_version"],
            "prepare_receipt_schema_version": PREPARE_RECEIPT_SCHEMA_VERSION,
            "outbound_schema_version": OUTBOUND_SCHEMA_VERSION,
            "raw_response_schema_version": RAW_RESPONSE_SCHEMA_VERSION,
            "attempt_schema_version": ATTEMPT_SCHEMA_VERSION,
            "label_schema_version": manifest["label_schema_version"],
            "import_metadata_schema_version": metadata["schema_version"],
        },
        "census": manifest["census"],
        "prompt": {
            "version": manifest["prompt_version"],
            "sha256": manifest["prompt_sha256"],
        },
        "label_schema_sha256": manifest["label_schema_sha256"],
        "teacher": {
            "model": metadata["teacher_model"],
            "generated_dates": metadata["generated_dates"],
            "nature": "point_in_time_sol_distillation_target_not_human_ground_truth",
        },
        "counts": manifest["counts"],
        "retries": metadata["retry_counts"],
        "private_artifacts": {
            "relative_directory": private_dir.relative_to(
                RepoPaths.discover(worktree_root).common_root
            ).as_posix(),
            "manifest_sha256": _sha256(manifest_raw),
            "prepare_receipt_sha256": _sha256(receipt_raw),
            "outbound_sha256": _sha256(outbound_raw),
            "raw_responses_sha256": _sha256(raw_response_bytes),
            "attempts_sha256": _sha256(attempt_bytes),
            "labels_sha256": _sha256(labels_raw),
            "import_metadata_sha256": _sha256(metadata_raw),
        },
        "boundaries": {
            "holdout_evaluation_only": True,
            "holdout_forbidden_from_synthesis_and_training": True,
            "runs_jsonl_modified": False,
            "shadow_results_published": False,
            "local_model_run": False,
            "api_backend_used": False,
        },
    }


def _summary_output(path: Path, summary: Mapping[str, Any]) -> dict[str, Any]:
    raw = _json_file_bytes(summary)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_or_match(path, raw, mode=0o644)
    return {
        "status": "summarized",
        "ready_for_l3": True,
        "summary_sha256": _sha256(raw),
        "output": path.as_posix(),
    }


def _transport_text(private_dir: Path, index: int) -> str:
    _require_private_directory(private_dir)
    outbound, _raw = _load_jsonl(private_dir / "outbound.jsonl", private=True)
    if index < 1 or index > len(outbound):
        raise TeacherLabelsError("transport_index_invalid")
    return (_canonical_bytes(outbound[index - 1]) + b"\n").decode("utf-8")


def _transport_info(
    private_dir: Path, index: int, chunk_characters: int
) -> dict[str, Any]:
    if chunk_characters < 1 or chunk_characters > 16_000:
        raise TeacherLabelsError("transport_chunk_size_invalid")
    value = _transport_text(private_dir, index)
    return {
        "transport_schema_version": 1,
        "index": index,
        "characters": len(value),
        "chunks": (len(value) + chunk_characters - 1) // chunk_characters,
        "chunk_characters": chunk_characters,
        "payload_sha256": _sha256(value.encode("utf-8")),
    }


def _print_result(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m rondo_eval.local_approval.teacher_labels"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--worktree-root", type=Path, required=True)
    prepare.add_argument("--source-root", type=Path, required=True)
    prepare.add_argument("--private-dir", type=Path, required=True)
    prepare.add_argument("--batch-id", required=True)
    prepare.add_argument("--created-date", required=True)
    prepare.add_argument("--previous-manifest", type=Path)

    transport_info = subparsers.add_parser("transport-info")
    transport_info.add_argument("--private-dir", type=Path, required=True)
    transport_info.add_argument("--index", type=int, required=True)
    transport_info.add_argument("--chunk-characters", type=int, default=12_000)

    record = subparsers.add_parser("record-raw")
    record.add_argument("--worktree-root", type=Path, required=True)
    record.add_argument("--private-dir", type=Path, required=True)
    record.add_argument("--transport-retry", action="append", default=[])
    record.add_argument("--schema-retry", action="append", default=[])
    record.add_argument(
        "--terminator",
        default="__RONDO_SOL_TEACHER_BATCH_END__",
        help="single line that ends stdin without becoming part of the raw file",
    )

    verify = subparsers.add_parser("verify")
    verify.add_argument("--worktree-root", type=Path, required=True)
    verify.add_argument("--private-dir", type=Path, required=True)
    verify.add_argument("--teacher-model", required=True)
    verify.add_argument("--generated-date", required=True)

    summarize = subparsers.add_parser("summarize")
    summarize.add_argument("--worktree-root", type=Path, required=True)
    summarize.add_argument("--private-dir", type=Path, required=True)
    summarize.add_argument("--output", type=Path, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "prepare":
            result = prepare_batch(
                worktree_root=args.worktree_root,
                source_root=args.source_root,
                private_dir=args.private_dir,
                batch_id=args.batch_id,
                created_date=args.created_date,
                previous_manifest=args.previous_manifest,
            )
            _print_result(result)
        elif args.command == "transport-info":
            _print_result(
                _transport_info(
                    args.private_dir, args.index, args.chunk_characters
                )
            )
        elif args.command == "record-raw":
            retries: dict[str, str] = {}
            for semantic_id in args.transport_retry:
                if semantic_id in retries:
                    raise TeacherLabelsError("retry_identity_duplicate")
                retries[semantic_id] = "transport_failed"
            for semantic_id in args.schema_retry:
                if semantic_id in retries:
                    raise TeacherLabelsError("retry_identity_duplicate")
                retries[semantic_id] = "schema_invalid"
            _print_result(
                record_raw_responses(
                    worktree_root=args.worktree_root,
                    private_dir=args.private_dir,
                    input_lines=_read_terminated_lines(args.terminator),
                    retry_reasons=retries,
                )
            )
        elif args.command == "verify":
            _print_result(
                verify_batch(
                    worktree_root=args.worktree_root,
                    private_dir=args.private_dir,
                    teacher_model=args.teacher_model,
                    generated_date=args.generated_date,
                )
            )
        else:
            summary = build_summary(
                worktree_root=args.worktree_root, private_dir=args.private_dir
            )
            _print_result(_summary_output(args.output, summary))
    except TeacherLabelsError as exc:
        report = {"status": "not_ready", "blocker": exc.code}
        if exc.facts:
            report["facts"] = exc.facts
        _print_result(report)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
