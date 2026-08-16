"""Plan 037 paired-output preparation with honest per-sample terminals.

The module is intentionally model-agnostic in stage one.  A later authorized
caller supplies one invocation callback; this runner fixes the side order,
performs no retries, and records exactly one decision/failure/refusal/timeout
terminal for every attempted sample.  Artifact identities are derived from
regular files, frozen locks, or canonical manifests rather than caller-supplied
digest strings.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from . import cross_eval


IDENTITY_SOURCE_SCHEMA_VERSION = 1
IDENTITY_SOURCE_CONTRACT_VERSION = "rondo_l6_pair_identity_sources_v1"
IDENTITY_SOURCE_KINDS = ("regular_file", "frozen_lock", "canonical_manifest")
ARTIFACT_MANIFEST_SCHEMA_VERSION = 1
ARTIFACT_MANIFEST_CONTRACT_VERSION = "rondo_l6_canonical_artifact_manifest_v1"
JOURNAL_SCHEMA_VERSION = 1
JOURNAL_CONTRACT_VERSION = "rondo_l6_paired_output_journal_v1"
LOCAL_SIDE_ORDER = ("local-static", "local-ft-static")

_LOGICAL_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,127}\Z")
_MANIFEST_MAX_BYTES = 8 * 1024 * 1024


class PairedOutputError(RuntimeError):
    """Stable fail-closed error from the paired-output preparation boundary."""


class SampleTerminal(RuntimeError):
    """An explicit non-decision terminal emitted by the invocation adapter."""

    status: str

    def __init__(self, failure_code: str) -> None:
        terminal = _failure_terminal(self.status, failure_code)
        super().__init__(terminal["failure_code"])
        self.failure_code = terminal["failure_code"]


class StructuredOutputFailure(SampleTerminal):
    status = "structured_output_failure"


class ModelRefusal(SampleTerminal):
    status = "refusal"


class SampleTimeout(SampleTerminal):
    status = "timeout"


@dataclass(frozen=True)
class IdentitySource:
    """One actual object used to derive a receipt identity."""

    kind: str
    path: Path
    logical_name: str


@dataclass(frozen=True, init=False)
class BuiltPairReceipt:
    receipt: dict[str, Any]
    source_manifest: dict[str, Any]
    sources: tuple[tuple[str, IdentitySource], ...]

    def __new__(cls) -> BuiltPairReceipt:
        raise TypeError("BuiltPairReceipt must be created by build_pair_receipt")

    @classmethod
    def _from_inspected_sources(
        cls,
        receipt: Mapping[str, Any],
        source_manifest: Mapping[str, Any],
        sources: Mapping[str, IdentitySource],
    ) -> BuiltPairReceipt:
        instance = object.__new__(cls)
        object.__setattr__(instance, "receipt", copy.deepcopy(dict(receipt)))
        object.__setattr__(
            instance, "source_manifest", copy.deepcopy(dict(source_manifest))
        )
        object.__setattr__(instance, "sources", tuple(sources.items()))
        return instance


def _stable_file_identity(info: os.stat_result) -> tuple[int, int, int, int]:
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _component_relative_path(value: Any) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise PairedOutputError("artifact_manifest_component_path_invalid")
    relative = Path(value)
    if (
        relative.is_absolute()
        or relative.parts in {(), (".",)}
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != value
    ):
        raise PairedOutputError("artifact_manifest_component_path_invalid")
    return relative


def _validate_artifact_manifest(
    value: Any, *, manifest_path: Path
) -> list[dict[str, Any]]:
    fields = {"schema_version", "contract_version", "artifact_id", "components"}
    if (
        not isinstance(value, dict)
        or set(value) != fields
        or value.get("schema_version") != ARTIFACT_MANIFEST_SCHEMA_VERSION
        or value.get("contract_version") != ARTIFACT_MANIFEST_CONTRACT_VERSION
        or not isinstance(value.get("artifact_id"), str)
        or _LOGICAL_NAME.fullmatch(value["artifact_id"]) is None
        or not isinstance(value.get("components"), list)
        or not value["components"]
    ):
        raise PairedOutputError("artifact_manifest_invalid")
    accepted: list[dict[str, Any]] = []
    names: set[str] = set()
    paths: set[str] = set()
    for component in value["components"]:
        if not isinstance(component, dict) or set(component) != {
            "logical_name",
            "relative_path",
            "size_bytes",
            "sha256",
        }:
            raise PairedOutputError("artifact_manifest_component_invalid")
        name = component["logical_name"]
        relative = _component_relative_path(component["relative_path"])
        size = component["size_bytes"]
        digest = component["sha256"]
        if (
            not isinstance(name, str)
            or _LOGICAL_NAME.fullmatch(name) is None
            or name in names
            or relative.as_posix() in paths
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size <= 0
            or not isinstance(digest, str)
            or cross_eval._HEX64.fullmatch(digest) is None
        ):
            raise PairedOutputError("artifact_manifest_component_invalid")
        names.add(name)
        paths.add(relative.as_posix())
        actual = inspect_identity_source(
            IdentitySource("regular_file", manifest_path.parent / relative, name)
        )
        if actual["size_bytes"] != size or actual["sha256"] != digest:
            raise PairedOutputError("artifact_manifest_component_drift")
        accepted.append(copy.deepcopy(component))
    if accepted != sorted(accepted, key=lambda item: item["logical_name"]):
        raise PairedOutputError("artifact_manifest_components_not_canonical")
    return accepted


def build_canonical_artifact_manifest(
    *,
    artifact_id: str,
    manifest_path: Path,
    components: Mapping[str, Path],
) -> dict[str, Any]:
    """Build a canonical manifest by hashing every declared actual component."""

    if (
        not isinstance(artifact_id, str)
        or _LOGICAL_NAME.fullmatch(artifact_id) is None
        or not isinstance(manifest_path, Path)
        or not isinstance(components, Mapping)
        or not components
    ):
        raise PairedOutputError("artifact_manifest_invalid")
    entries = []
    for logical_name, component_path in sorted(components.items()):
        if not isinstance(component_path, Path):
            raise PairedOutputError("artifact_manifest_component_invalid")
        try:
            relative = component_path.relative_to(manifest_path.parent)
        except ValueError as exc:
            raise PairedOutputError("artifact_manifest_component_path_invalid") from exc
        relative = _component_relative_path(relative.as_posix())
        inspected = inspect_identity_source(
            IdentitySource("regular_file", component_path, logical_name)
        )
        entries.append(
            {
                "logical_name": logical_name,
                "relative_path": relative.as_posix(),
                "size_bytes": inspected["size_bytes"],
                "sha256": inspected["sha256"],
            }
        )
    return {
        "schema_version": ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "contract_version": ARTIFACT_MANIFEST_CONTRACT_VERSION,
        "artifact_id": artifact_id,
        "components": entries,
    }


def inspect_identity_source(source: IdentitySource) -> dict[str, Any]:
    """Hash one non-symlink regular object and return body-free evidence."""

    if (
        not isinstance(source, IdentitySource)
        or source.kind not in IDENTITY_SOURCE_KINDS
        or not isinstance(source.path, Path)
        or not isinstance(source.logical_name, str)
        or _LOGICAL_NAME.fullmatch(source.logical_name) is None
    ):
        raise PairedOutputError("identity_source_invalid")
    try:
        before = os.lstat(source.path)
    except OSError as exc:
        raise PairedOutputError("identity_source_missing") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or before.st_size <= 0
    ):
        raise PairedOutputError("identity_source_not_regular")
    if source.kind in {"frozen_lock", "canonical_manifest"} and before.st_size > _MANIFEST_MAX_BYTES:
        raise PairedOutputError("identity_source_manifest_too_large")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    digest = hashlib.sha256()
    canonical_raw: bytearray | None = (
        bytearray() if source.kind in {"frozen_lock", "canonical_manifest"} else None
    )
    try:
        descriptor = os.open(source.path, flags)
        try:
            opened = os.fstat(descriptor)
            if _stable_file_identity(opened) != _stable_file_identity(before):
                raise PairedOutputError("identity_source_changed")
            while True:
                chunk = os.read(descriptor, 1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                if canonical_raw is not None:
                    canonical_raw.extend(chunk)
            after_fd = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        after_path = os.lstat(source.path)
    except PairedOutputError:
        raise
    except OSError as exc:
        raise PairedOutputError("identity_source_read_failed") from exc
    identity = _stable_file_identity(before)
    if (
        _stable_file_identity(after_fd) != identity
        or _stable_file_identity(after_path) != identity
    ):
        raise PairedOutputError("identity_source_changed")
    components: list[dict[str, Any]] | None = None
    if canonical_raw is not None:
        try:
            value = json.loads(bytes(canonical_raw).decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PairedOutputError("identity_source_json_invalid") from exc
        if bytes(canonical_raw) != cross_eval._json_file_bytes(value):
            raise PairedOutputError("identity_source_not_canonical")
        if source.kind == "canonical_manifest":
            components = _validate_artifact_manifest(
                value, manifest_path=source.path
            )
            try:
                final_manifest = os.lstat(source.path)
            except OSError as exc:
                raise PairedOutputError("identity_source_changed") from exc
            if _stable_file_identity(final_manifest) != identity:
                raise PairedOutputError("identity_source_changed")
    result = {
        "kind": source.kind,
        "logical_name": source.logical_name,
        "size_bytes": before.st_size,
        "sha256": digest.hexdigest(),
    }
    if components is not None:
        result["components"] = components
    return result


def build_pair_receipt(
    *,
    pair_id: str,
    base_model: IdentitySource,
    local_static: IdentitySource,
    local_ft_static: IdentitySource,
    training_receipt: IdentitySource,
    shared_contract: Mapping[str, Any],
    blind_identity_markers: Sequence[str],
) -> BuiltPairReceipt:
    """Build the v1 canonical receipt exclusively from inspected objects."""

    actual_sources = {
        "base-model": base_model,
        "local-static": local_static,
        "local-ft-static": local_ft_static,
        "training-receipt": training_receipt,
    }
    sources = {
        "base-model": inspect_identity_source(base_model),
        "local-static": inspect_identity_source(local_static),
        "local-ft-static": inspect_identity_source(local_ft_static),
        "training-receipt": inspect_identity_source(training_receipt),
    }
    receipt = {
        "schema_version": cross_eval.LOCAL_PAIR_RECEIPT_SCHEMA_VERSION,
        "contract_version": cross_eval.LOCAL_PAIR_RECEIPT_CONTRACT_VERSION,
        "source_work_package": "L6",
        "pair_id": pair_id,
        "base_model_identity_sha256": sources["base-model"]["sha256"],
        "shared_contract": copy.deepcopy(dict(shared_contract)),
        "artifacts": {
            "local-static": {
                "provenance": "l6_paired_unfinetuned",
                "model_artifact_sha256": sources["local-static"]["sha256"],
                "training_receipt_sha256": None,
            },
            "local-ft-static": {
                "provenance": "l6_paired_finetuned",
                "model_artifact_sha256": sources["local-ft-static"]["sha256"],
                "training_receipt_sha256": sources["training-receipt"]["sha256"],
            },
        },
        "blind_identity_markers": list(blind_identity_markers),
    }
    normalized, receipt_sha256, _contracts = cross_eval.validate_l6_pair_receipt(
        receipt
    )
    source_manifest = {
        "schema_version": IDENTITY_SOURCE_SCHEMA_VERSION,
        "contract_version": IDENTITY_SOURCE_CONTRACT_VERSION,
        "pair_id": pair_id,
        "pair_receipt_sha256": receipt_sha256,
        "sources": sources,
    }
    return BuiltPairReceipt._from_inspected_sources(
        normalized, source_manifest, actual_sources
    )


def _revalidate_built_pair_receipt(
    value: BuiltPairReceipt,
) -> tuple[dict[str, Any], str, dict[str, dict[str, Any]]]:
    if not isinstance(value, BuiltPairReceipt) or not all(
        hasattr(value, field) for field in ("receipt", "source_manifest", "sources")
    ):
        raise PairedOutputError("built_pair_receipt_required")
    actual_sources = dict(value.sources)
    if set(actual_sources) != {
        "base-model",
        "local-static",
        "local-ft-static",
        "training-receipt",
    } or any(not isinstance(source, IdentitySource) for source in actual_sources.values()):
        raise PairedOutputError("built_pair_receipt_sources_invalid")
    inspected = {
        name: inspect_identity_source(source)
        for name, source in actual_sources.items()
    }
    expected_manifest = value.source_manifest
    if (
        not isinstance(expected_manifest, dict)
        or expected_manifest.get("schema_version") != IDENTITY_SOURCE_SCHEMA_VERSION
        or expected_manifest.get("contract_version")
        != IDENTITY_SOURCE_CONTRACT_VERSION
        or expected_manifest.get("pair_id") != value.receipt.get("pair_id")
        or expected_manifest.get("sources") != inspected
    ):
        raise PairedOutputError("pair_receipt_source_manifest_mismatch")
    normalized, receipt_sha256, contracts = cross_eval.validate_l6_pair_receipt(
        value.receipt
    )
    if (
        expected_manifest.get("pair_receipt_sha256") != receipt_sha256
        or normalized["base_model_identity_sha256"]
        != inspected["base-model"]["sha256"]
        or normalized["artifacts"]["local-static"]["model_artifact_sha256"]
        != inspected["local-static"]["sha256"]
        or normalized["artifacts"]["local-ft-static"]["model_artifact_sha256"]
        != inspected["local-ft-static"]["sha256"]
        or normalized["artifacts"]["local-ft-static"]["training_receipt_sha256"]
        != inspected["training-receipt"]["sha256"]
    ):
        raise PairedOutputError("pair_receipt_source_manifest_mismatch")
    return normalized, receipt_sha256, contracts


def _decision_terminal(decision: Mapping[str, Any]) -> dict[str, Any]:
    return cross_eval.validate_output_terminal(
        {
            "schema_version": cross_eval.OUTPUT_TERMINAL_SCHEMA_VERSION,
            "contract_version": cross_eval.OUTPUT_TERMINAL_CONTRACT_VERSION,
            "status": "decision",
            "decision": copy.deepcopy(dict(decision)),
        }
    )


def _failure_terminal(status: str, failure_code: str) -> dict[str, Any]:
    return cross_eval.validate_output_terminal(
        {
            "schema_version": cross_eval.OUTPUT_TERMINAL_SCHEMA_VERSION,
            "contract_version": cross_eval.OUTPUT_TERMINAL_CONTRACT_VERSION,
            "status": status,
            "failure_code": failure_code,
        }
    )


def _local_output_row(
    *,
    bundle: cross_eval.CohortBundle,
    cohort_item: Mapping[str, Any],
    source_row: Mapping[str, Any],
    side: str,
    run_contract: Mapping[str, Any],
    terminal: Mapping[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": cross_eval.TERMINAL_IMPORT_SCHEMA_VERSION,
        "contract_version": cross_eval.TERMINAL_IMPORT_CONTRACT_VERSION,
        "partition": bundle.partition,
        "cohort_id": bundle.manifest["cohort_id"],
        "cohort_manifest_sha256": bundle.manifest_sha256,
        "body_batch_id": cohort_item["body_batch_id"],
        "sample_id": source_row["sample_id"],
        "side": side,
        "approval_input": copy.deepcopy(source_row["input"]),
        "payload_sha256": source_row["payload_sha256"],
        "approval_prompt_sha256": cohort_item["approval_prompt_sha256"],
        "message_sequence_sha256": cohort_item["message_sequence_sha256"],
        "output_schema_sha256": cohort_item["output_schema_sha256"],
        "terminal": copy.deepcopy(dict(terminal)),
        "run_contract": copy.deepcopy(dict(run_contract)),
    }


def _require_run_directory(path: Path) -> None:
    try:
        info = os.lstat(path)
    except OSError as exc:
        raise PairedOutputError("paired_run_directory_missing") from exc
    if (
        stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise PairedOutputError("paired_run_directory_invalid")


def _journal_header(
    bundle: cross_eval.CohortBundle,
    *,
    receipt: Mapping[str, Any],
    receipt_sha256: str,
    source_manifest: Mapping[str, Any],
    expected_keys: Sequence[tuple[str, str]],
) -> dict[str, Any]:
    return {
        "schema_version": JOURNAL_SCHEMA_VERSION,
        "contract_version": JOURNAL_CONTRACT_VERSION,
        "record_type": "run",
        "cohort_id": bundle.manifest["cohort_id"],
        "cohort_manifest_sha256": bundle.manifest_sha256,
        "pair_id": receipt["pair_id"],
        "pair_receipt_sha256": receipt_sha256,
        "pair_source_manifest_sha256": cross_eval._canonical_sha256(
            source_manifest
        ),
        "side_order": list(LOCAL_SIDE_ORDER),
        "sample_order_sha256": cross_eval._canonical_sha256(
            [sample_id for _side, sample_id in expected_keys]
        ),
        "expected_terminal_count": len(expected_keys),
    }


def _append_journal_record(path: Path, value: Mapping[str, Any]) -> None:
    raw = cross_eval._canonical_bytes(dict(value)) + b"\n"
    try:
        before = os.lstat(path)
    except OSError as exc:
        raise PairedOutputError("paired_journal_missing") from exc
    if (
        stat.S_ISLNK(before.st_mode)
        or not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o600
    ):
        raise PairedOutputError("paired_journal_invalid")
    flags = os.O_WRONLY | os.O_APPEND
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if _stable_file_identity(opened) != _stable_file_identity(before):
                raise PairedOutputError("paired_journal_changed")
            written = os.write(descriptor, raw)
            if written != len(raw):
                raise PairedOutputError("paired_journal_partial_write")
            os.fsync(descriptor)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
    except PairedOutputError:
        raise
    except OSError as exc:
        raise PairedOutputError("paired_journal_write_failed") from exc
    if (
        after.st_dev != before.st_dev
        or after.st_ino != before.st_ino
        or after.st_size != before.st_size + len(raw)
    ):
        raise PairedOutputError("paired_journal_changed")


def _load_or_create_journal(
    *,
    run_dir: Path,
    header: Mapping[str, Any],
    bundle: cross_eval.CohortBundle,
    contracts: Mapping[str, Mapping[str, Any]],
    expected_keys: Sequence[tuple[str, str]],
) -> tuple[Path, list[dict[str, Any]]]:
    _require_run_directory(run_dir)
    journal_path = run_dir / "paired-output-journal.jsonl"
    if not journal_path.exists() and not journal_path.is_symlink():
        cross_eval._write_exclusive(
            journal_path,
            cross_eval._canonical_bytes(dict(header)) + b"\n",
            mode=0o600,
        )
    raw = cross_eval._safe_read(journal_path, private=True)
    if not raw.endswith(b"\n"):
        raise PairedOutputError("paired_journal_incomplete_write")
    lines = raw.splitlines()
    if not lines:
        raise PairedOutputError("paired_journal_invalid")
    values = []
    for line in lines:
        try:
            value = json.loads(line.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise PairedOutputError("paired_journal_invalid") from exc
        if not isinstance(value, dict) or line != cross_eval._canonical_bytes(value):
            raise PairedOutputError("paired_journal_not_canonical")
        values.append(value)
    if values[0] != dict(header):
        raise PairedOutputError("paired_journal_binding_mismatch")

    records = values[1:]
    completed: list[dict[str, Any]] = []
    cursor = 0
    while cursor < len(records):
        sequence = len(completed)
        if sequence >= len(expected_keys):
            raise PairedOutputError("paired_journal_record_unexpected")
        side, sample_id = expected_keys[sequence]
        attempt = records[cursor]
        expected_attempt = {
            "schema_version": JOURNAL_SCHEMA_VERSION,
            "contract_version": JOURNAL_CONTRACT_VERSION,
            "record_type": "attempt",
            "sequence": sequence,
            "side": side,
            "sample_id": sample_id,
        }
        if attempt != expected_attempt:
            raise PairedOutputError("paired_journal_attempt_invalid")
        cursor += 1
        if cursor == len(records):
            raise PairedOutputError("paired_journal_attempt_without_terminal")
        terminal_record = records[cursor]
        if (
            not isinstance(terminal_record, dict)
            or set(terminal_record) != {
                "schema_version",
                "contract_version",
                "record_type",
                "sequence",
                "side",
                "sample_id",
                "row",
            }
            or terminal_record.get("schema_version") != JOURNAL_SCHEMA_VERSION
            or terminal_record.get("contract_version") != JOURNAL_CONTRACT_VERSION
            or terminal_record.get("record_type") != "terminal"
            or terminal_record.get("sequence") != sequence
            or terminal_record.get("side") != side
            or terminal_record.get("sample_id") != sample_id
        ):
            raise PairedOutputError("paired_journal_terminal_invalid")
        item = next(
            value
            for value in bundle.manifest["items"]
            if value["sample_id"] == sample_id
        )
        accepted = cross_eval._validate_import_row(
            terminal_record["row"],
            bundle=bundle,
            cohort_item=item,
            source_row=bundle.source_rows[sample_id],
        )
        if (
            accepted != terminal_record["row"]
            or accepted["side"] != side
            or accepted["run_contract"] != contracts[side]
        ):
            raise PairedOutputError("paired_journal_terminal_invalid")
        completed.append(accepted)
        cursor += 1
    return journal_path, completed


def run_paired_outputs(
    bundle: cross_eval.CohortBundle,
    *,
    pair_receipt: BuiltPairReceipt,
    run_dir: Path,
    invoke: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
    max_new_terminals: int | None = None,
) -> list[dict[str, Any]]:
    """Run both local sides serially and record one honest terminal per sample.

    The callback is invoked for all ``local-static`` samples before any
    ``local-ft-static`` sample.  Only explicit ``SampleTerminal`` exceptions
    become sample records; unexpected/infrastructure exceptions abort the run.
    """

    cross_eval.validate_cohort_bundle(bundle)
    receipt, receipt_sha256, contracts = _revalidate_built_pair_receipt(
        pair_receipt
    )
    if not callable(invoke):
        raise PairedOutputError("paired_invoke_invalid")
    if (
        max_new_terminals is not None
        and (
            not isinstance(max_new_terminals, int)
            or isinstance(max_new_terminals, bool)
            or max_new_terminals < 0
        )
    ):
        raise PairedOutputError("paired_terminal_limit_invalid")
    items = {item["sample_id"]: item for item in bundle.manifest["items"]}
    expected_keys = [
        (side, sample_id)
        for side in LOCAL_SIDE_ORDER
        for sample_id in sorted(items)
    ]
    header = _journal_header(
        bundle,
        receipt=receipt,
        receipt_sha256=receipt_sha256,
        source_manifest=pair_receipt.source_manifest,
        expected_keys=expected_keys,
    )
    journal_path, rows = _load_or_create_journal(
        run_dir=run_dir,
        header=header,
        bundle=bundle,
        contracts=contracts,
        expected_keys=expected_keys,
    )
    new_terminals = 0
    for sequence, (side, sample_id) in enumerate(
        expected_keys[len(rows) :], start=len(rows)
    ):
        if max_new_terminals is not None and new_terminals >= max_new_terminals:
            break
        source = bundle.source_rows[sample_id]
        _append_journal_record(
            journal_path,
            {
                "schema_version": JOURNAL_SCHEMA_VERSION,
                "contract_version": JOURNAL_CONTRACT_VERSION,
                "record_type": "attempt",
                "sequence": sequence,
                "side": side,
                "sample_id": sample_id,
            },
        )
        try:
            terminal = _decision_terminal(
                invoke(side, copy.deepcopy(source["input"]))
            )
        except SampleTerminal as exc:
            terminal = _failure_terminal(exc.status, exc.failure_code)
        row = _local_output_row(
            bundle=bundle,
            cohort_item=items[sample_id],
            source_row=source,
            side=side,
            run_contract=contracts[side],
            terminal=terminal,
        )
        _append_journal_record(
            journal_path,
            {
                "schema_version": JOURNAL_SCHEMA_VERSION,
                "contract_version": JOURNAL_CONTRACT_VERSION,
                "record_type": "terminal",
                "sequence": sequence,
                "side": side,
                "sample_id": sample_id,
                "row": row,
            },
        )
        rows.append(row)
        new_terminals += 1
    return rows


def build_frozen_sol_rows(
    bundle: cross_eval.CohortBundle,
) -> list[dict[str, Any]]:
    """Project frozen Sol targets as unchanged v1 decision rows."""

    cross_eval.validate_cohort_bundle(bundle)
    items = {item["sample_id"]: item for item in bundle.manifest["items"]}
    rows = []
    for sample_id in sorted(items):
        source = bundle.source_rows[sample_id]
        item = items[sample_id]
        source_cohort_sha256 = (
            bundle.manifest["source"]["validation_sha256"]
            if bundle.partition == "synthetic"
            else bundle.manifest["source"]["private_source_sha256"]
        )
        rows.append(
            {
                "schema_version": cross_eval.IMPORT_SCHEMA_VERSION,
                "contract_version": cross_eval.IMPORT_CONTRACT_VERSION,
                "partition": bundle.partition,
                "cohort_id": bundle.manifest["cohort_id"],
                "cohort_manifest_sha256": bundle.manifest_sha256,
                "body_batch_id": item["body_batch_id"],
                "sample_id": sample_id,
                "side": "sol-static",
                "approval_input": copy.deepcopy(source["input"]),
                "payload_sha256": source["payload_sha256"],
                "approval_prompt_sha256": item["approval_prompt_sha256"],
                "message_sequence_sha256": item["message_sequence_sha256"],
                "output_schema_sha256": item["output_schema_sha256"],
                "decision": copy.deepcopy(source["target"]),
                "run_contract": {
                    "contract_version": cross_eval.IMPORT_CONTRACT_VERSION,
                    "provenance": "frozen_validation_target",
                    "source_dataset_batch_id": source["batch_id"],
                    "source_generation_model": source["generator_model"],
                    "source_generated_date": source["generated_date"],
                    "source_generation_prompt_version": source["prompt_version"],
                    "source_generation_prompt_sha256": source["prompt_sha256"],
                    "source_cohort_sha256": source_cohort_sha256,
                },
            }
        )
    return rows


def assemble_three_side_outputs(
    bundle: cross_eval.CohortBundle,
    local_rows: Sequence[Mapping[str, Any]],
    *,
    pair_receipt: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Combine frozen Sol v1 rows and local v2 rows through the formal importer."""

    return cross_eval.validate_three_side_rows(
        bundle,
        [*build_frozen_sol_rows(bundle), *copy.deepcopy(list(local_rows))],
        l6_pair_receipt=pair_receipt,
    )
