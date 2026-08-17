"""Materialize the Plan 032 frozen real holdout as a private M4 anchor cohort.

This module never calls a model.  It re-derives the whole Plan 032 batch from
the real production archive, requires byte identity with the frozen private
files, re-runs the Plan 032 verifier, and only then projects the frozen
``holdout`` partition into the private holdout bundle contract that
``cross_eval`` already defines.  The samples are neither selected, filtered nor
re-partitioned here: the set is exactly the frozen label representatives whose
partition is ``holdout``.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..config import ConfigError, RepoPaths
from . import cross_eval, teacher_labels


MATERIALIZATION_SCHEMA_VERSION = 1
MATERIALIZATION_CONTRACT_VERSION = "rondo_m4_holdout_materialization_v1"
SOURCE_FILE_NAME = "holdout-source.jsonl"
RECEIPT_FILE_NAME = "holdout-materialization-receipt.json"
SOURCE_GROUP_PREFIX = "holdout-task-"

_HOLDOUT_BATCH_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,95}\Z")


class HoldoutAnchorError(RuntimeError):
    """Body-free, stable failure from the holdout materialization boundary."""

    def __init__(self, code: str, facts: Mapping[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.facts = dict(facts or {})


def _source_group_id(task_id: str) -> str:
    """Derive a stable, body-free source group from the real task identity."""

    digest = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:32]
    return f"{SOURCE_GROUP_PREFIX}{digest}"


def reverify_frozen_batch(
    *, worktree_root: Path, source_root: Path, teacher_private_dir: Path
) -> dict[str, Any]:
    """Re-derive the frozen Plan 032 batch and require byte identity.

    ``build_batch_artifacts`` re-reads every real ``E_final``/``meta.json``,
    rebuilds each canonical static payload, and recomputes the semantic
    identity, partition and representative choice.  Any drift between that
    recomputation and the frozen private files fails closed.
    """

    teacher_labels._require_private_directory(teacher_private_dir)
    manifest, manifest_raw = teacher_labels._load_json(
        teacher_private_dir / "manifest.json", private=True
    )
    metadata, _metadata_raw = teacher_labels._load_json(
        teacher_private_dir / "import-metadata.json", private=True
    )
    if (
        not isinstance(manifest, dict)
        or not isinstance(metadata, dict)
        or not isinstance(manifest.get("batch_id"), str)
        or manifest.get("batch_id") != metadata.get("batch_id")
        or not isinstance(manifest.get("created_date"), str)
        or not isinstance(metadata.get("generated_dates"), list)
        or len(metadata["generated_dates"]) != 1
        or not isinstance(metadata.get("teacher_model"), str)
    ):
        raise HoldoutAnchorError("frozen_batch_binding_invalid")

    try:
        artifacts = teacher_labels.build_batch_artifacts(
            worktree_root=worktree_root,
            source_root=source_root,
            batch_id=manifest["batch_id"],
            created_date=manifest["created_date"],
        )
    except teacher_labels.TeacherLabelsError as exc:
        raise HoldoutAnchorError("frozen_batch_recompute_failed", exc.facts) from exc

    outbound_raw = teacher_labels._safe_read(
        teacher_private_dir / "outbound.jsonl",
        limit=teacher_labels._MAX_PRIVATE_FILE_BYTES,
        private=True,
    )
    receipt_raw = teacher_labels._safe_read(
        teacher_private_dir / "prepare-receipt.json",
        limit=teacher_labels._MAX_PRIVATE_FILE_BYTES,
        private=True,
    )
    if (
        artifacts["manifest_raw"] != manifest_raw
        or artifacts["outbound_raw"] != outbound_raw
        or artifacts["prepare_receipt_raw"] != receipt_raw
    ):
        raise HoldoutAnchorError("frozen_batch_source_drift")

    try:
        verified = teacher_labels.verify_batch(
            worktree_root=worktree_root,
            private_dir=teacher_private_dir,
            teacher_model=metadata["teacher_model"],
            generated_date=metadata["generated_dates"][0],
        )
    except teacher_labels.TeacherLabelsError as exc:
        raise HoldoutAnchorError("frozen_batch_verify_failed", exc.facts) from exc
    if not verified.get("ready_for_l3"):
        raise HoldoutAnchorError("frozen_batch_not_ready")

    labels, _labels_raw = teacher_labels._load_jsonl(
        teacher_private_dir / "labels.jsonl", private=True
    )
    return {
        "manifest": artifacts["manifest"],
        "manifest_sha256": verified["manifest_sha256"],
        "outbound": artifacts["outbound"],
        "labels": labels,
        "labels_sha256": verified["labels_sha256"],
        "teacher_model": metadata["teacher_model"],
        "generated_date": metadata["generated_dates"][0],
    }


def build_holdout_records(
    verified: Mapping[str, Any], *, holdout_batch_id: str
) -> list[dict[str, Any]]:
    """Project the frozen ``holdout`` partition without adding or dropping rows."""

    if (
        not isinstance(holdout_batch_id, str)
        or _HOLDOUT_BATCH_ID.fullmatch(holdout_batch_id) is None
    ):
        raise HoldoutAnchorError("holdout_batch_id_invalid")
    manifest = verified["manifest"]
    payload_by_semantic = {}
    for item in verified["outbound"]:
        if not isinstance(item, dict) or not isinstance(item.get("semantic_id"), str):
            raise HoldoutAnchorError("frozen_outbound_invalid")
        if item["semantic_id"] in payload_by_semantic:
            raise HoldoutAnchorError("frozen_outbound_duplicate")
        payload_by_semantic[item["semantic_id"]] = item
    label_by_semantic = {}
    for item in verified["labels"]:
        if not isinstance(item, dict) or not isinstance(item.get("semantic_id"), str):
            raise HoldoutAnchorError("frozen_label_invalid")
        if item["semantic_id"] in label_by_semantic:
            raise HoldoutAnchorError("frozen_label_duplicate")
        label_by_semantic[item["semantic_id"]] = item

    records: list[dict[str, Any]] = []
    for instance in manifest["instances"]:
        if not instance.get("selected") or instance.get("partition") != "holdout":
            continue
        semantic_id = instance["semantic_id"]
        outbound = payload_by_semantic.get(semantic_id)
        label = label_by_semantic.get(semantic_id)
        if outbound is None or label is None:
            raise HoldoutAnchorError("holdout_sample_source_missing")
        if (
            instance.get("usage") != "holdout_evaluation_only"
            or outbound.get("partition") != "holdout"
            or label.get("partition") != "holdout"
            or outbound.get("static_payload_sha256")
            != instance["static_payload_sha256"]
            or label.get("static_payload_sha256") != instance["static_payload_sha256"]
            or label.get("representative_e_final_sha256")
            != instance["e_final_sha256"]
            or label.get("teacher_model") != verified["teacher_model"]
            or label.get("generated_date") != verified["generated_date"]
            or label.get("prompt_version") != manifest["prompt_version"]
            or label.get("prompt_sha256") != manifest["prompt_sha256"]
        ):
            raise HoldoutAnchorError("holdout_sample_identity_drift")
        records.append(
            {
                "schema_version": 1,
                "contract_version": cross_eval.HOLDOUT_PRIVATE_CONTRACT_VERSION,
                "holdout_batch_id": holdout_batch_id,
                "sample_id": semantic_id,
                "source_group_id": _source_group_id(instance["task_id"]),
                "split_group_id": semantic_id,
                "approval_input": copy.deepcopy(outbound["canonical_payload"]),
                "payload_sha256": instance["static_payload_sha256"],
                "sol_target": copy.deepcopy(label["decision"]),
                "teacher_model": verified["teacher_model"],
                "generated_date": verified["generated_date"],
                "teacher_prompt_version": manifest["prompt_version"],
                "teacher_prompt_sha256": manifest["prompt_sha256"],
            }
        )
    declared = manifest["counts"]["selected_partitions"]["holdout"]
    if not records or len(records) != declared:
        raise HoldoutAnchorError(
            "holdout_set_incomplete",
            {"declared": declared, "materialized": len(records)},
        )
    return sorted(records, key=lambda item: item["sample_id"])


def _require_execution_directory(worktree_root: Path, private_dir: Path) -> Path:
    return cross_eval._require_execution_private_directory(worktree_root, private_dir)


def materialize_holdout_source(
    *,
    worktree_root: Path,
    teacher_private_dir: Path,
    private_dir: Path,
    holdout_batch_id: str,
) -> dict[str, Any]:
    """Write the private holdout source and its body-free receipt exactly once."""

    resolved_private = _require_execution_directory(worktree_root, private_dir)
    source_root = RepoPaths.discover(worktree_root).common_root
    verified = reverify_frozen_batch(
        worktree_root=worktree_root,
        source_root=source_root,
        teacher_private_dir=teacher_private_dir,
    )
    records = build_holdout_records(verified, holdout_batch_id=holdout_batch_id)
    bundle = cross_eval.build_private_holdout_bundle(
        records, holdout_batch_id=holdout_batch_id
    )
    source_raw = cross_eval._jsonl_bytes(records)
    receipt = {
        "schema_version": MATERIALIZATION_SCHEMA_VERSION,
        "contract_version": MATERIALIZATION_CONTRACT_VERSION,
        "holdout_batch_id": holdout_batch_id,
        "cohort_id": bundle.manifest["cohort_id"],
        "cohort_manifest_sha256": bundle.manifest_sha256,
        "private_source_sha256": bundle.manifest["source"]["private_source_sha256"],
        "sample_count": len(records),
        "source_file_sha256": cross_eval._sha256(source_raw),
        "teacher_batch_id": verified["manifest"]["batch_id"],
        "teacher_manifest_sha256": verified["manifest_sha256"],
        "teacher_labels_sha256": verified["labels_sha256"],
        "teacher_model": verified["teacher_model"],
        "teacher_generated_date": verified["generated_date"],
        "teacher_prompt_version": verified["manifest"]["prompt_version"],
        "teacher_prompt_sha256": verified["manifest"]["prompt_sha256"],
        "batches": {
            item["batch_id"]: item["sample_count"]
            for item in bundle.manifest["batching"]["batches"]
        },
        "source_group_count": len(
            {item["source_group_sha256"] for item in bundle.manifest["items"]}
        ),
        "models_called": 0,
        "samples_added_or_dropped": 0,
        "boundaries": {
            "body_free": True,
            "holdout_used_for_evaluation_only": True,
            "tracked_item_projection_allowed": False,
        },
    }
    source_path = resolved_private / SOURCE_FILE_NAME
    receipt_path = resolved_private / RECEIPT_FILE_NAME
    receipt_raw = cross_eval._json_file_bytes(receipt)
    for path, raw in ((source_path, source_raw), (receipt_path, receipt_raw)):
        if path.exists() or path.is_symlink():
            if cross_eval._safe_read(path, private=True) != raw:
                raise HoldoutAnchorError("holdout_materialization_drift")
        else:
            cross_eval._write_exclusive(path, raw, mode=0o600)
    return {
        "status": "materialized",
        "holdout_batch_id": holdout_batch_id,
        "cohort_id": receipt["cohort_id"],
        "cohort_manifest_sha256": receipt["cohort_manifest_sha256"],
        "sample_count": receipt["sample_count"],
        "batches": receipt["batches"],
        "teacher_model": receipt["teacher_model"],
        "teacher_generated_date": receipt["teacher_generated_date"],
        "models_called": 0,
    }


def load_holdout_bundle(private_dir: Path) -> cross_eval.CohortBundle:
    """Rebuild the private holdout cohort from its materialized source file."""

    cross_eval._require_private_directory(private_dir)
    records, _raw = cross_eval._load_jsonl(private_dir / SOURCE_FILE_NAME, private=True)
    batch_ids = {
        record.get("holdout_batch_id")
        for record in records
        if isinstance(record, Mapping)
    }
    if len(batch_ids) != 1:
        raise HoldoutAnchorError("holdout_source_batch_mixed")
    holdout_batch_id = next(iter(batch_ids))
    if (
        not isinstance(holdout_batch_id, str)
        or _HOLDOUT_BATCH_ID.fullmatch(holdout_batch_id) is None
    ):
        raise HoldoutAnchorError("holdout_batch_id_invalid")
    bundle = cross_eval.build_private_holdout_bundle(
        records, holdout_batch_id=holdout_batch_id
    )
    receipt, _receipt_raw = cross_eval._load_json(
        private_dir / RECEIPT_FILE_NAME, private=True
    )
    if (
        not isinstance(receipt, dict)
        or receipt.get("contract_version") != MATERIALIZATION_CONTRACT_VERSION
        or receipt.get("holdout_batch_id") != holdout_batch_id
        or receipt.get("cohort_manifest_sha256") != bundle.manifest_sha256
        or receipt.get("sample_count") != len(bundle.manifest["items"])
        or receipt.get("private_source_sha256")
        != bundle.manifest["source"]["private_source_sha256"]
    ):
        raise HoldoutAnchorError("holdout_receipt_binding_invalid")
    return bundle


def _print_result(value: Mapping[str, Any]) -> None:
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m rondo_eval.local_approval.holdout_anchor"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    materialize = commands.add_parser("materialize")
    materialize.add_argument("--worktree-root", type=Path, required=True)
    materialize.add_argument("--teacher-private-dir", type=Path, required=True)
    materialize.add_argument("--private-dir", type=Path, required=True)
    materialize.add_argument("--holdout-batch-id", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("--private-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "materialize":
            result = materialize_holdout_source(
                worktree_root=args.worktree_root,
                teacher_private_dir=args.teacher_private_dir,
                private_dir=args.private_dir,
                holdout_batch_id=args.holdout_batch_id,
            )
        else:
            bundle = load_holdout_bundle(args.private_dir)
            result = {
                "status": "ready",
                "partition": bundle.partition,
                "cohort_id": bundle.manifest["cohort_id"],
                "cohort_manifest_sha256": bundle.manifest_sha256,
                "sample_count": len(bundle.manifest["items"]),
                "batches": {
                    item["batch_id"]: item["sample_count"]
                    for item in bundle.manifest["batching"]["batches"]
                },
            }
        _print_result(result)
        return 0
    except HoldoutAnchorError as exc:
        report: dict[str, Any] = {"status": "not_ready", "blocker": exc.code}
        if exc.facts:
            report["facts"] = exc.facts
        _print_result(report)
        return 2
    except cross_eval.CrossEvalError as exc:
        _print_result({"status": "not_ready", "blocker": exc.code})
        return 2
    except teacher_labels.TeacherLabelsError as exc:
        _print_result({"status": "not_ready", "blocker": exc.code})
        return 2
    except (ConfigError, OSError):
        _print_result({"status": "not_ready", "blocker": "filesystem_error"})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
