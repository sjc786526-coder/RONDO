"""Exact-tokenizer census over arbitrary accepted Plan 059 packet rows."""

from collections import Counter
from collections.abc import Mapping, Sequence
import hashlib
from pathlib import Path
from typing import Any

from ..contract import REPO_ROOT
from ..tokenization import ExactTokenizer
from .contract import TrainingDataError, validate_packet_row


def census_packets(
    packet_rows: Sequence[Mapping[str, Any]],
    tokenizer: ExactTokenizer,
    rubric: str,
    *,
    repo_root: Path | str = REPO_ROOT,
) -> tuple[tuple[dict[str, Any], ...], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for packet_row in packet_rows:
        validate_packet_row(packet_row, repo_root=repo_root)
        candidate_id = str(packet_row["candidate_id"])
        if candidate_id in seen:
            raise TrainingDataError(f"duplicate candidate in token census: {candidate_id}")
        seen.add(candidate_id)
        tokenized = tokenizer.fit_packet(packet_row["packet"], rubric)
        rows.append(
            {
                "schema_version": 1,
                "candidate_id": candidate_id,
                "token_count": len(tokenized.input_ids),
                "dropped_oldest_publications": tokenized.plan.dropped_oldest_publications,
                "buckets": dict(tokenized.buckets),
                "rendered_chat_sha256": hashlib.sha256(
                    tokenized.rendered_chat.encode("utf-8")
                ).hexdigest(),
            }
        )
    bucket_totals: Counter[str] = Counter()
    for row in rows:
        bucket_totals.update(row["buckets"])
    token_total = sum(int(row["token_count"]) for row in rows)
    if sum(bucket_totals.values()) != token_total:
        raise ValueError("census bucket totals do not reconcile")
    summary = {
        "schema_version": 1,
        "candidate_count": len(rows),
        "token_total": token_total,
        "token_min": min((row["token_count"] for row in rows), default=0),
        "token_max": max((row["token_count"] for row in rows), default=0),
        "dropped_oldest_publications_total": sum(
            int(row["dropped_oldest_publications"]) for row in rows
        ),
        "bucket_totals": dict(sorted(bucket_totals.items())),
    }
    return tuple(rows), summary
