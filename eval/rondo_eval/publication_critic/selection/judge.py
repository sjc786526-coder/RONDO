"""The blinded Opus 5 exchange: package out, structured verdicts back.

The Judge sees exactly the model-visible rendering of each publication and the
frozen product rubric, in a deterministically shuffled order under opaque item
identifiers.  It never sees the GPT reference label, the pair direction, the
split name, which model produced which score, or any score at all.  De-blinding
happens only after every batch has passed identity, completeness and uniqueness
checks, so selection can never observe a partial aggregate.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
from typing import Any

from ..identity import canonical_json_bytes, sha256_bytes
from ..render import build_messages
from .contract import (
    SelectionError,
    require_count,
    require_exact_keys,
    require_object,
    require_sha256,
)


PACKAGE_SCHEMA = "rondo-publication-critic-plan073-judge-package-v1"
MAPPING_SCHEMA = "rondo-publication-critic-plan073-judge-mapping-v1"
BATCH_SCHEMA = "rondo-publication-critic-plan073-judge-batch-v1"
AGGREGATE_SCHEMA = "rondo-publication-critic-plan073-judge-aggregate-v1"

VERDICTS = ("PASS", "REWRITE")
CONFIDENCES = ("high", "medium", "low")
MAX_REASON_CHARS = 400
DEFAULT_BATCH_SIZE = 8
_SPLIT_TOKENS = ("validation", "unseen", "holdout", "train", "test")

JUDGE_TASK = (
    "You are an independent reviewer of one team publication at a time. For each item, "
    "decide whether the publication meets the qualification policy quoted inside the item. "
    "Judge only the publication content shown against that policy. Items are unrelated to "
    "each other and are presented in arbitrary order; do not look for pairs, do not balance "
    "your verdicts across the batch, and do not assume any particular ratio of outcomes."
)


def package_sha256(package: Mapping[str, Any]) -> str:
    return sha256_bytes(canonical_json_bytes(dict(package)))


def _blinded_order(candidate_ids: Sequence[str], salt: str) -> list[str]:
    return sorted(
        candidate_ids,
        key=lambda candidate_id: hashlib.sha256(
            f"{salt}\x00{candidate_id}".encode("utf-8")
        ).hexdigest(),
    )


def build_judge_package(
    release: Mapping[str, Any],
    rubric: str,
    *,
    salt: str,
    package_id: str,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the blinded package plus the private mapping kept out of it."""

    if not isinstance(salt, str) or len(salt) < 16:
        raise SelectionError("Plan 073 judge salt is too short to blind identities")
    if not isinstance(package_id, str) or not package_id.strip():
        raise SelectionError("Plan 073 judge package identity is invalid")
    # Batch identifiers travel with every Judge context, so the package id is
    # part of the blinding surface and must not name the split being judged.
    lowered = package_id.lower()
    if any(token in lowered for token in _SPLIT_TOKENS):
        raise SelectionError("Plan 073 judge package identity must not name a split")
    if type(batch_size) is not int or not 1 <= batch_size <= 32:
        raise SelectionError("Plan 073 judge batch size is invalid")

    packets = {
        str(item["candidate_id"]): item for item in release["items"]
    }
    ordered = _blinded_order(sorted(packets), salt)
    width = max(4, len(str(len(ordered))))
    mapping: dict[str, str] = {}
    items: list[dict[str, Any]] = []
    for index, candidate_id in enumerate(ordered):
        item_id = f"j-{index:0{width}d}"
        mapping[item_id] = candidate_id
        source = packets[candidate_id]
        messages = build_messages(
            source["packet"],
            rubric,
            dropped_oldest_publications=int(source["dropped_oldest_publications"]),
        )
        items.append(
            {
                "item_id": item_id,
                "context": messages[0]["content"],
                "publication": messages[1]["content"],
            }
        )

    batches = [
        {
            "batch_id": f"{package_id}-b{number:02d}",
            "items": items[start : start + batch_size],
        }
        for number, start in enumerate(range(0, len(items), batch_size), start=1)
    ]
    package = {
        "schema": PACKAGE_SCHEMA,
        "package_id": package_id,
        "task": JUDGE_TASK,
        "verdicts": list(VERDICTS),
        "confidences": list(CONFIDENCES),
        "max_reason_chars": MAX_REASON_CHARS,
        "item_count": len(items),
        "batches": batches,
    }
    private_mapping = {
        "schema": MAPPING_SCHEMA,
        "package_id": package_id,
        "salt_sha256": hashlib.sha256(salt.encode("utf-8")).hexdigest(),
        "package_sha256": package_sha256(package),
        "mapping": mapping,
    }
    return validate_package(package), private_mapping


def batch_documents(package: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Split a package into self-contained per-batch requests.

    Each Judge context then receives only its own blinded items plus the shared
    instructions, never the rest of the package.
    """

    shared = {
        name: package[name]
        for name in ("package_id", "task", "verdicts", "confidences", "max_reason_chars")
    }
    return {
        batch["batch_id"]: {
            **shared,
            "batch_id": batch["batch_id"],
            "items": list(batch["items"]),
        }
        for batch in package["batches"]
    }


def validate_package(value: Any) -> dict[str, Any]:
    package = require_object(value, "Plan 073 judge package")
    require_exact_keys(
        package,
        {
            "schema",
            "package_id",
            "task",
            "verdicts",
            "confidences",
            "max_reason_chars",
            "item_count",
            "batches",
        },
        "Plan 073 judge package",
    )
    if (
        package["schema"] != PACKAGE_SCHEMA
        or not isinstance(package["package_id"], str)
        or not package["package_id"].strip()
        or list(package["verdicts"]) != list(VERDICTS)
        or list(package["confidences"]) != list(CONFIDENCES)
        or package["max_reason_chars"] != MAX_REASON_CHARS
        or package["task"] != JUDGE_TASK
    ):
        raise SelectionError("Plan 073 judge package identity is invalid")
    batches = package["batches"]
    if not isinstance(batches, list) or not batches:
        raise SelectionError("Plan 073 judge package has no batch")
    seen_items: list[str] = []
    batch_ids: list[str] = []
    for batch_value in batches:
        batch = require_object(batch_value, "Plan 073 judge batch")
        require_exact_keys(batch, {"batch_id", "items"}, "Plan 073 judge batch")
        batch_id = batch["batch_id"]
        if not isinstance(batch_id, str) or not batch_id.startswith(
            f"{package['package_id']}-b"
        ):
            raise SelectionError("Plan 073 judge batch identity is invalid")
        batch_ids.append(batch_id)
        if not isinstance(batch["items"], list) or not batch["items"]:
            raise SelectionError("Plan 073 judge batch is empty")
        for item_value in batch["items"]:
            item = require_object(item_value, "Plan 073 judge item")
            require_exact_keys(
                item, {"item_id", "context", "publication"}, "Plan 073 judge item"
            )
            item_id = item["item_id"]
            if (
                not isinstance(item_id, str)
                or not item_id.startswith("j-")
                or not isinstance(item["context"], str)
                or not item["context"]
                or not isinstance(item["publication"], str)
                or not item["publication"]
            ):
                raise SelectionError("Plan 073 judge item is invalid")
            seen_items.append(item_id)
    if len(set(batch_ids)) != len(batch_ids):
        raise SelectionError("Plan 073 judge batch identity is duplicated")
    if len(set(seen_items)) != len(seen_items) or len(seen_items) != package[
        "item_count"
    ]:
        raise SelectionError("Plan 073 judge package item identity is invalid")
    return dict(package)


def validate_mapping(value: Any, package: Mapping[str, Any]) -> dict[str, str]:
    private = require_object(value, "Plan 073 judge mapping")
    require_exact_keys(
        private,
        {"schema", "package_id", "salt_sha256", "package_sha256", "mapping"},
        "Plan 073 judge mapping",
    )
    if (
        private["schema"] != MAPPING_SCHEMA
        or private["package_id"] != package["package_id"]
        or private["package_sha256"] != package_sha256(package)
    ):
        raise SelectionError("Plan 073 judge mapping identity is invalid")
    require_sha256(private["salt_sha256"], "Plan 073 judge salt")
    mapping = require_object(private["mapping"], "Plan 073 judge mapping table")
    expected = {
        item["item_id"] for batch in package["batches"] for item in batch["items"]
    }
    if set(mapping) != expected:
        raise SelectionError("Plan 073 judge mapping does not cover the package")
    values = list(mapping.values())
    if any(not isinstance(item, str) or not item for item in values) or len(
        set(values)
    ) != len(values):
        raise SelectionError("Plan 073 judge mapping targets are invalid")
    return {str(key): str(value) for key, value in mapping.items()}


def validate_batch_response(
    value: Any,
    package: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate one returned batch against the frozen package."""

    response = require_object(value, "Plan 073 judge response")
    require_exact_keys(
        response,
        {"schema", "package_id", "batch_id", "model_identity", "judged_at", "verdicts"},
        "Plan 073 judge response",
    )
    batches = {batch["batch_id"]: batch for batch in package["batches"]}
    if (
        response["schema"] != BATCH_SCHEMA
        or response["package_id"] != package["package_id"]
        or response["batch_id"] not in batches
    ):
        raise SelectionError("Plan 073 judge response identity is invalid")
    for name in ("model_identity", "judged_at"):
        if not isinstance(response[name], str) or not response[name].strip():
            raise SelectionError(f"Plan 073 judge response {name} is invalid")
    expected = [item["item_id"] for item in batches[response["batch_id"]]["items"]]
    verdicts = response["verdicts"]
    if not isinstance(verdicts, list) or len(verdicts) != len(expected):
        raise SelectionError("Plan 073 judge response does not cover its batch")
    seen: list[str] = []
    for row_value in verdicts:
        row = require_object(row_value, "Plan 073 judge verdict")
        require_exact_keys(
            row, {"item_id", "verdict", "confidence", "reason"}, "Plan 073 judge verdict"
        )
        if (
            row["item_id"] not in expected
            or row["verdict"] not in VERDICTS
            or row["confidence"] not in CONFIDENCES
            or not isinstance(row["reason"], str)
            or not row["reason"].strip()
            or len(row["reason"]) > MAX_REASON_CHARS
        ):
            raise SelectionError("Plan 073 judge verdict is invalid")
        seen.append(str(row["item_id"]))
    if sorted(seen) != sorted(expected):
        raise SelectionError("Plan 073 judge response item identity is invalid")
    return dict(response)


def aggregate_batches(
    package: Mapping[str, Any],
    private_mapping: Any,
    responses: Sequence[Any],
) -> dict[str, Any]:
    """De-blind only after every batch is present, unique and consistent."""

    mapping = validate_mapping(private_mapping, package)
    validated = [validate_batch_response(item, package) for item in responses]
    batch_ids = [item["batch_id"] for item in validated]
    expected_batches = [batch["batch_id"] for batch in package["batches"]]
    if sorted(batch_ids) != sorted(expected_batches):
        raise SelectionError("Plan 073 judge aggregate is missing or duplicating a batch")
    identities = {item["model_identity"] for item in validated}
    if len(identities) != 1:
        raise SelectionError(
            "Plan 073 judge aggregate must not mix judging model identities"
        )
    verdicts: dict[str, dict[str, str]] = {}
    for response in validated:
        for row in response["verdicts"]:
            candidate_id = mapping[str(row["item_id"])]
            if candidate_id in verdicts:
                raise SelectionError("Plan 073 judge aggregate item is duplicated")
            verdicts[candidate_id] = {
                "verdict": str(row["verdict"]),
                "confidence": str(row["confidence"]),
                "reason": str(row["reason"]),
            }
    if len(verdicts) != package["item_count"]:
        raise SelectionError("Plan 073 judge aggregate does not cover the package")
    return {
        "schema": AGGREGATE_SCHEMA,
        "package_id": package["package_id"],
        "package_sha256": package_sha256(package),
        "model_identity": identities.pop(),
        "judged_dates": sorted({item["judged_at"] for item in validated}),
        "batch_count": len(validated),
        "item_count": package["item_count"],
        "verdicts": dict(sorted(verdicts.items())),
    }


def validate_aggregate(value: Any) -> dict[str, Any]:
    aggregate = require_object(value, "Plan 073 judge aggregate")
    require_exact_keys(
        aggregate,
        {
            "schema",
            "package_id",
            "package_sha256",
            "model_identity",
            "judged_dates",
            "batch_count",
            "item_count",
            "verdicts",
        },
        "Plan 073 judge aggregate",
    )
    if aggregate["schema"] != AGGREGATE_SCHEMA:
        raise SelectionError("Plan 073 judge aggregate identity is invalid")
    require_sha256(aggregate["package_sha256"], "Plan 073 judge aggregate package")
    require_count(aggregate["batch_count"], "Plan 073 judge batch count")
    require_count(aggregate["item_count"], "Plan 073 judge item count")
    verdicts = require_object(aggregate["verdicts"], "Plan 073 judge verdict table")
    if len(verdicts) != aggregate["item_count"]:
        raise SelectionError("Plan 073 judge aggregate coverage is invalid")
    for row_value in verdicts.values():
        row = require_object(row_value, "Plan 073 judge verdict")
        require_exact_keys(
            row, {"verdict", "confidence", "reason"}, "Plan 073 judge verdict"
        )
        if row["verdict"] not in VERDICTS or row["confidence"] not in CONFIDENCES:
            raise SelectionError("Plan 073 judge verdict is invalid")
    return dict(aggregate)


def reference_agreement(
    release: Mapping[str, Any],
    aggregate: Mapping[str, Any],
) -> dict[str, Any]:
    """How the blinded Judge relates to the frozen GPT reference labels."""

    labels = {
        str(row["candidate_id"]): str(row["binary_label"])
        for row in release["supervision"]
    }
    verdicts = aggregate["verdicts"]
    if set(verdicts) != set(labels):
        raise SelectionError("Plan 073 judge aggregate does not match the release")
    disagreements = sorted(
        candidate_id
        for candidate_id, row in verdicts.items()
        if row["verdict"] != labels[candidate_id]
    )
    agreements = len(labels) - len(disagreements)
    return {
        "count": len(labels),
        "agreements": agreements,
        "agreement_rate": agreements / len(labels) if labels else None,
        "judge_pass_count": sum(
            row["verdict"] == "PASS" for row in verdicts.values()
        ),
        "reference_pass_count": sum(value == "PASS" for value in labels.values()),
        "disagreement_candidate_ids": disagreements,
    }


def model_agreement(
    aggregate: Mapping[str, Any],
    predictions: Mapping[str, str],
) -> dict[str, Any]:
    """How one candidate model's verdicts relate to the blinded Judge."""

    verdicts = aggregate["verdicts"]
    if set(predictions) != set(verdicts):
        raise SelectionError("Plan 073 model predictions do not match the judge cohort")
    disagreements = sorted(
        candidate_id
        for candidate_id, predicted in predictions.items()
        if predicted != verdicts[candidate_id]["verdict"]
    )
    agreements = len(predictions) - len(disagreements)
    return {
        "count": len(predictions),
        "agreements": agreements,
        "agreement_rate": agreements / len(predictions) if predictions else None,
        "disagreement_candidate_ids": disagreements,
    }
