"""Honest M-5 archive records. Fake/loopback and real API stay labelled."""

from __future__ import annotations

from typing import Any, Mapping

from ..contracts import Product, Side, team_capability_config_projection


M5_ARCHIVE_SCHEMA_VERSION = 1
REQUIRED_ARCHIVE_FIELDS = (
    "schema_version",
    "evidence_kind",
    "gate",
    "lock_id",
    "product",
    "side",
    "source_commit",
    "binary_sha256",
    "team_capability_config",
    "outcome",
    "counts_as_effective",
)


def required_archive_fields() -> tuple[str, ...]:
    return REQUIRED_ARCHIVE_FIELDS


def archive_record(
    *,
    evidence_kind: str,
    gate: int,
    lock_id: str,
    side: Side,
    product: Product | None,
    source_commit: str,
    binary_sha256: str,
    outcome: str,
    counts_as_effective: bool,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    if evidence_kind not in {"loopback", "fake", "real_api"}:
        raise ValueError("evidence kind is not an M-5 partition")
    if gate not in {1, 2}:
        raise ValueError("gate must be 1 or 2")
    record = {
        "schema_version": M5_ARCHIVE_SCHEMA_VERSION,
        "evidence_kind": evidence_kind,
        "gate": gate,
        "lock_id": lock_id,
        "product": None if product is None else product.value,
        "side": side.value,
        "source_commit": source_commit,
        "binary_sha256": binary_sha256,
        "team_capability_config": team_capability_config_projection(side, product),
        "outcome": outcome,
        "counts_as_effective": counts_as_effective,
    }
    if extra:
        overlap = set(extra) & set(REQUIRED_ARCHIVE_FIELDS)
        if overlap:
            raise ValueError("extra archive fields collide with the required set")
        record.update(dict(extra))
    missing = [name for name in REQUIRED_ARCHIVE_FIELDS if name not in record]
    if missing:
        raise ValueError("archive record is missing required fields")
    return record
