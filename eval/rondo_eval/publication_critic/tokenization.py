"""Exact tokenizer use, window fitting and strictly reconciled token buckets."""

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .render import ADOPTED_CONTEXT_WINDOW, RenderPlan, component_spans, fit_to_window


class TokenizationError(ValueError):
    """Raised when the exact tokenizer violates the frozen input contract."""


@dataclass(frozen=True)
class TokenizedInput:
    plan: RenderPlan
    rendered_chat: str
    input_ids: tuple[int, ...]
    buckets: dict[str, int]


class ExactTokenizer:
    def __init__(self, tokenizer: Any) -> None:
        self.tokenizer = tokenizer
        if tokenizer.pad_token_id != 151654:
            raise TokenizationError("exact tokenizer pad token drifted")
        if tokenizer.bos_token_id is not None:
            raise TokenizationError("exact tokenizer unexpectedly defines BOS")
        if tokenizer.eos_token_id != 151645:
            raise TokenizationError("exact tokenizer EOS drifted")
        tokenizer.padding_side = "right"

    def render_chat(self, messages: Sequence[Mapping[str, str]]) -> str:
        rendered = self.tokenizer.apply_chat_template(
            list(messages),
            tokenize=False,
            add_generation_prompt=False,
        )
        if not isinstance(rendered, str) or not rendered:
            raise TokenizationError("chat template did not return text")
        return rendered

    def token_count(self, messages: Sequence[Mapping[str, str]]) -> int:
        return len(self._encode_chat(self.render_chat(messages))["input_ids"])

    def fit_packet(
        self,
        packet: Mapping[str, Any],
        rubric: str,
        *,
        adopted_window: int = ADOPTED_CONTEXT_WINDOW,
    ) -> TokenizedInput:
        plan = fit_to_window(
            packet,
            rubric,
            self.token_count,
            adopted_window=adopted_window,
        )
        rendered = self.render_chat(plan.messages)
        encoded = self._encode_chat(rendered)
        ids = tuple(int(value) for value in encoded["input_ids"])
        if len(ids) > adopted_window:
            raise TokenizationError("window fitting and authoritative tokenization disagree")
        buckets = self._buckets(rendered, ids, encoded["offset_mapping"])
        if sum(buckets.values()) != len(ids):
            raise TokenizationError("token buckets do not reconcile to input_ids")
        return TokenizedInput(
            plan=plan,
            rendered_chat=rendered,
            input_ids=ids,
            buckets=buckets,
        )

    def _encode_chat(self, rendered: str) -> Mapping[str, Any]:
        encoded = self.tokenizer(
            rendered,
            add_special_tokens=False,
            truncation=False,
            return_attention_mask=True,
            return_offsets_mapping=True,
        )
        if len(encoded["input_ids"]) != len(encoded["attention_mask"]):
            raise TokenizationError("input ids and attention mask differ")
        if any(value != 1 for value in encoded["attention_mask"]):
            raise TokenizationError("unpadded input has an invalid attention mask")
        return encoded

    def _buckets(
        self,
        rendered: str,
        ids: tuple[int, ...],
        offsets: Sequence[Sequence[int]],
    ) -> dict[str, int]:
        if len(ids) != len(offsets):
            raise TokenizationError("offset mapping does not match input ids")
        spans = component_spans(rendered)
        buckets = {
            "policy": 0,
            "packet_framing": 0,
            "candidate": 0,
            "continuity": 0,
            "evidence_v1": 0,
            "special_tokens": 0,
            "cross_segment_framing": 0,
        }
        component_bucket = {
            "policy": "policy",
            "packet": "packet_framing",
            "candidate": "candidate",
            "continuity": "continuity",
            "evidence_v1": "evidence_v1",
        }
        special_ids = set(self.tokenizer.all_special_ids)
        for token_id, offset in zip(ids, offsets):
            if token_id in special_ids or tuple(offset) == (0, 0):
                buckets["special_tokens"] += 1
                continue
            start, end = int(offset[0]), int(offset[1])
            matches = [
                component_bucket[name]
                for name, (left, right) in spans.items()
                if left <= start and end <= right
            ]
            if len(matches) == 1:
                buckets[matches[0]] += 1
            else:
                buckets["cross_segment_framing"] += 1
        return buckets
