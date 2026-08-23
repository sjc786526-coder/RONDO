# Publication Critic model input contract v1

This contract freezes the Plan 054 evaluator input. Its product wire is the existing typed `PublicationPacket` named `rondo-publication-packet@v1`, qualified by `rondo-publication-qualification@v1`. The evaluator does not accept a raw publish request and does not implement title, summary, handoff, history, freshness, role, or evidence canonicalization.

## Model-visible allowlist

The model receives exactly two ordered messages and no system message.

1. The user message contains the fixed qualification rubric followed by typed public packet context: qualification identity, authoritative `root` or `member`, `new_event` or `existing_event`, canonical local-scope title, typed continuity, and Evidence V1.
2. The assistant message contains the complete canonical candidate summary and optional handoff. The candidate title is the canonical local-scope title already present in the user message.

`new_event` has `not_applicable` continuity. `existing_event` exposes only its typed `available` or `unavailable` envelope: coverage, freshness, source revision or last-known revision, at most four oldest-to-newest public prior publications, and body-free evidence counts. `product-packet-limits-v1.json` records the Rust-parity product caps; the focused Rust test owns parity with the product constants.

The renderer uses explicit component markers, JSON string escaping with UTF-8 text preserved, deterministic field order, and the exact tokenizer's frozen `chat_template.jinja` with `add_generation_prompt=false`. The tokenizer adds no second special-token pass. Exact token IDs are authoritative.

## Content that never enters the renderer

The following are evaluation-only or private and forbidden from model-visible input: expected verdict, completion state, hard-defect and slice labels, pair identity/direction, calibration/measurement role, sample/source/generator/reviewer identity, rationale anchor, Event or Version identity, Fact identity, producer, locator, category, tool, observation body, raw trace/evidence, transcript, reasoning, private context, participant/lifecycle/route state, and the rest of Team State.

Packet rows and annotation rows are physically separate tracked JSONL files. The renderer accepts only the packet mapping and fixed rubric; it has no annotation argument.

## Window, padding, batching, and overflow

The model config declares 40,960 positions and the tokenizer metadata declares 131,072, while the model card describes 16,384-token preference training and recommends inference within that length. Plan 054 adopts 16,384 only after exact-tokenizer census and a real mechanical forward at that length.

The fixed policy, qualification structure, canonical title, complete summary, optional handoff, and Evidence V1 are mandatory. Tokenizer truncation is disabled. If an input exceeds the adopted window, the renderer removes one whole oldest prior publication, increments the render-only `model_window_additional_oldest_omitted` count, then renders and tokenizes again. Product coverage omission and render-window omission remain distinct. If mandatory content still does not fit, the input is a typed failure and receives no score.

Unpadded inputs use an all-one attention mask. Batches use tokenizer pad ID 151654 and frozen right padding. Left padding is smoke-tested only as a parity counterfactual. A score is usable only when single, repeated, right-padded batch, and left/right counterfactual results agree within the scoring identity's absolute tolerance.

## Scalar contract

The exact checkpoint is `Qwen3ForSequenceClassification` with one label. The selected output is `logits[:, 0]`, pooled at the last non-pad token by the model implementation, shape `[batch, 1]`. The raw reward logit is unbounded and higher is better under the exact reward-model contract. Plan 054 applies the monotone stable sigmoid projection to the complete finite domain `[0, 1]`; it never infers direction or domain from observed measurement extrema.

The temporary evaluation threshold is calibration-only, selected by `temporary-threshold-rule-v1.json`, and is not a production threshold. A projected score at or above it maps to `PASS`. Model, tokenizer, input template, adopted window, overflow encoding, padding, scalar projection/domain, temporary threshold, and pass rule all participate in the frozen measurement identity.
