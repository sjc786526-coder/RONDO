"""Census-only legal boundary packets derived from the typed product limits.

These probes never participate in calibration or quality measurement.  They
start from already validated PublicationPacket fixtures and replace only
canonical text with exact legal boundary values.  The limit document is tied
back to the Rust constants by a focused product-side test; this module neither
clamps raw publish requests nor derives role, freshness, history, or evidence.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


class BoundaryError(ValueError):
    """Raised when the Rust-parity packet limit document cannot define a probe."""


@dataclass(frozen=True)
class TokenBoundaryPacket:
    sample_id: str
    packet: Mapping[str, Any]


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _plain(nested) for key, nested in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain(nested) for nested in value]
    return value


def _text_at_scalar_limit(limit: Mapping[str, Any], unit: str) -> str:
    scalars = limit["max_scalars"]
    maximum_bytes = limit["max_bytes"]
    if type(scalars) is not int or type(maximum_bytes) is not int or scalars <= 0:
        raise BoundaryError("packet text limit is invalid")
    pattern = f"{unit}-state-transfer-"
    value = (pattern * (scalars // len(pattern) + 1))[:scalars]
    if len(value.encode("utf-8")) > maximum_bytes:
        raise BoundaryError("scalar boundary exceeds its paired byte limit")
    return value


def _text_at_byte_limit(limit: Mapping[str, Any]) -> str:
    scalars = limit["max_scalars"]
    maximum_bytes = limit["max_bytes"]
    if type(scalars) is not int or type(maximum_bytes) is not int:
        raise BoundaryError("packet text limit is invalid")
    # This assigned CJK Extension G scalar is four UTF-8 bytes and follows the
    # exact tokenizer's byte-fallback path.  It exercises the product byte cap
    # without using malformed text or exceeding the paired scalar limit.
    boundary_scalar = "\U0003134a"
    scalar_count, ascii_count = divmod(
        maximum_bytes, len(boundary_scalar.encode("utf-8"))
    )
    value = boundary_scalar * scalar_count + "x" * ascii_count
    if len(value) > scalars or len(value.encode("utf-8")) != maximum_bytes:
        raise BoundaryError("cannot construct the exact Unicode byte boundary")
    return value


def build_token_boundary_packets(
    packets: Sequence[Mapping[str, Any]],
    limits: Mapping[str, Any],
) -> tuple[TokenBoundaryPacket, ...]:
    new_base = next(packet for packet in packets if packet["target_kind"] == "new_event")
    existing_base = next(
        packet
        for packet in packets
        if packet["target_kind"] == "existing_event"
        and packet["continuity"]["state"] == "available"
    )

    scalar = copy.deepcopy(_plain(new_base))
    scalar["local_scope"]["title"] = _text_at_scalar_limit(limits["title"], "title")
    scalar["candidate"]["summary"] = _text_at_scalar_limit(limits["summary"], "summary")
    scalar["candidate"]["handoff"] = _text_at_scalar_limit(limits["handoff"], "handoff")

    byte = copy.deepcopy(_plain(existing_base))
    byte["local_scope"]["title"] = _text_at_byte_limit(limits["title"])
    byte["candidate"]["summary"] = _text_at_byte_limit(limits["summary"])
    byte["candidate"]["handoff"] = _text_at_byte_limit(limits["handoff"])
    maximum_prior = limits["max_prior_publications"]
    if type(maximum_prior) is not int or maximum_prior <= 0:
        raise BoundaryError("prior publication limit is invalid")
    prior = byte["continuity"]["prior_publications"][0]
    prior["summary"] = _text_at_byte_limit(limits["summary"])
    prior["handoff"] = _text_at_byte_limit(limits["handoff"])
    byte["continuity"]["prior_publications"] = [
        copy.deepcopy(prior) for _ in range(maximum_prior)
    ]

    return (
        TokenBoundaryPacket("pc-v1-census-scalar-boundary", scalar),
        TokenBoundaryPacket("pc-v1-census-unicode-byte-history-boundary", byte),
    )
