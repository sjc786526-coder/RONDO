"""Deterministic no-system reward-model rendering and overflow handling."""

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Sequence


ADOPTED_CONTEXT_WINDOW = 16_384
COMPONENTS = ("policy", "packet", "continuity", "evidence_v1", "candidate")


class RenderError(ValueError):
    """Raised when a packet cannot be rendered without changing its candidate."""


class InputOverflowError(RenderError):
    """The complete required candidate does not fit the adopted model window."""


@dataclass(frozen=True)
class RenderPlan:
    messages: tuple[dict[str, str], ...]
    dropped_oldest_publications: int


def _json_string(value: object) -> str:
    return json.dumps(
        _plain(value),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    )


def _plain(value: object) -> object:
    """Copy a read-only loaded packet into ordinary JSON containers."""

    if isinstance(value, Mapping):
        return {key: _plain(nested) for key, nested in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_plain(nested) for nested in value]
    return value


def _component(name: str, body: str) -> str:
    if name not in COMPONENTS:
        raise RenderError("unknown render component")
    return f"[[RONDO_COMPONENT:{name}:BEGIN]]\n{body}\n[[RONDO_COMPONENT:{name}:END]]"


def _qualification(packet: Mapping[str, Any]) -> str:
    qualification = packet["qualification"]
    return "\n".join(
        (
            "input_contract: "
            + _json_string(
                {
                    "packet_schema": qualification["packet_schema"],
                    "rubric": qualification["rubric"],
                }
            ),
            f"authoritative_actor_role: {_json_string(packet['actor_role'])}",
            f"target_kind: {_json_string(packet['target_kind'])}",
            f"local_scope_title: {_json_string(packet['local_scope']['title'])}",
        )
    )


def _continuity(packet: Mapping[str, Any], dropped: int) -> str:
    continuity = packet["continuity"]
    state = continuity["state"]
    lines = [f"state: {_json_string(state)}"]
    if state == "not_applicable":
        lines.append("new_event_has_no_prior_continuity: true")
    elif state == "unavailable":
        lines.extend(
            (
                f"last_known_revision: {_json_string(continuity['last_known_revision'])}",
                f"freshness: {_json_string(continuity['freshness'])}",
            )
        )
    elif state == "available":
        lines.extend(
            (
                f"source_team_revision: {continuity['source_team_revision']}",
                f"freshness: {_json_string(continuity['freshness'])}",
                "source_coverage: " + _json_string(continuity["coverage"]),
                f"model_window_additional_oldest_omitted: {dropped}",
                "prior_publications_oldest_to_newest:",
            )
        )
        publications: Sequence[Mapping[str, Any]] = continuity["prior_publications"]
        if not publications:
            lines.append("- <none provided>")
        for index, prior in enumerate(publications, start=1):
            lines.append(
                "- "
                + _json_string(
                    {
                        "position": index,
                        "summary": prior["summary"],
                        "handoff": prior["handoff"],
                        "evidence": prior["evidence"],
                    }
                )
            )
    else:
        raise RenderError("continuity state is unknown")
    return "\n".join(lines)


def build_messages(
    packet: Mapping[str, Any],
    rubric: str,
    *,
    dropped_oldest_publications: int = 0,
) -> tuple[dict[str, str], ...]:
    """Render only the typed packet plus the fixed rubric.

    Evaluation labels, data roles, pair direction and rationales are not
    accepted by this API and therefore cannot enter model-visible input.
    """

    candidate = packet["candidate"]
    user = "\n\n".join(
        (
            _component("policy", rubric.rstrip()),
            _component("packet", _qualification(packet)),
            _component("continuity", _continuity(packet, dropped_oldest_publications)),
            _component("evidence_v1", _json_string(packet["evidence_v1"])),
        )
    )
    assistant = _component(
        "candidate",
        "\n".join(
            (
                f"summary: {_json_string(candidate['summary'])}",
                f"handoff: {_json_string(candidate['handoff'])}",
            )
        ),
    )
    return (
        {"role": "user", "content": user},
        {"role": "assistant", "content": assistant},
    )


def fit_to_window(
    packet: Mapping[str, Any],
    rubric: str,
    token_count: Callable[[Sequence[Mapping[str, str]]], int],
    *,
    adopted_window: int = ADOPTED_CONTEXT_WINDOW,
) -> RenderPlan:
    """Drop whole oldest continuity entries until the complete input fits."""

    if adopted_window <= 0:
        raise RenderError("adopted window must be positive")
    plain = _plain(packet)
    if not isinstance(plain, dict):
        raise RenderError("packet must be a mapping")
    working = plain
    dropped = 0
    while True:
        messages = build_messages(
            working,
            rubric,
            dropped_oldest_publications=dropped,
        )
        count = token_count(messages)
        if count <= adopted_window:
            return RenderPlan(messages=messages, dropped_oldest_publications=dropped)
        continuity = working["continuity"]
        if continuity["state"] != "available" or not continuity["prior_publications"]:
            raise InputOverflowError(
                "required policy, packet structure and complete candidate exceed the adopted window"
            )
        continuity["prior_publications"].pop(0)
        dropped += 1


def component_spans(rendered_chat: str) -> dict[str, tuple[int, int]]:
    """Locate semantic bodies; all tags and cross-boundary tokens are framing."""

    spans: dict[str, tuple[int, int]] = {}
    for name in COMPONENTS:
        begin = f"[[RONDO_COMPONENT:{name}:BEGIN]]\n"
        end = f"\n[[RONDO_COMPONENT:{name}:END]]"
        begin_at = rendered_chat.find(begin)
        if begin_at < 0:
            raise RenderError(f"rendered chat is missing {name} begin marker")
        body_start = begin_at + len(begin)
        end_at = rendered_chat.find(end, body_start)
        if end_at < 0 or rendered_chat.find(begin, body_start) >= 0:
            raise RenderError(f"rendered chat has ambiguous {name} markers")
        spans[name] = (body_start, end_at)
    return spans
