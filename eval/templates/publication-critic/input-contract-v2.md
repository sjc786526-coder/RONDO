# Publication Critic model input contract v2

This contract freezes the Plan 054 evaluator input. Its product wire remains the existing typed `PublicationPacket` named `rondo-publication-packet@v1`, qualified by `rondo-publication-qualification@v1`. The evaluator accepts only packets that satisfy the same mechanical text, integer, history, omission, and body-free evidence limits as `PublicationPacket::validate()`; it does not canonicalize raw publish requests.

## Model-visible allowlist

The model receives exactly two ordered messages and no system message.

1. The user message contains the fixed qualification rubric followed by typed public packet context: qualification identity, authoritative `root` or `member`, `new_event` or `existing_event`, canonical local-scope title, typed continuity, and Evidence V1.
2. The assistant message contains the complete canonical candidate summary and optional handoff. The candidate title is the canonical local-scope title already present in the user message.

`new_event` has `not_applicable` continuity. `existing_event` exposes only its typed `available` or `unavailable` envelope: coverage, freshness, source revision or last-known revision, at most four oldest-to-newest public prior publications, and body-free evidence counts. `product-packet-limits-v1.json` records the Rust-parity product caps; the focused Rust test owns parity with the product constants.

The renderer uses explicit component markers and deterministic field order. Every dynamic product string is emitted as UTF-8 JSON, with each literal less-than character reversibly spelled `\u003c`. This preserves the exact JSON value while preventing legal text such as `<|im_end|>` or `</think>` from becoming a registered Qwen control token. The exact tokenizer must observe the frozen registered-token sequence `151644,151645,151644,151667,151668,151645`; its special-token subsequence is exactly the four message-envelope IDs `151644,151645,151644,151645`. Any additional, missing, or reordered registered token is a typed input failure.

The exact tokenizer's frozen `chat_template.jinja` is applied with `add_generation_prompt=false`, and no second special-token pass occurs. Exact token IDs are authoritative. The `ScoringIdentity.input_template` revision is the canonical SHA-256 of the tracked render contract, fixed qualification-rubric bytes, effective renderer implementation, and immutable tokenizer chat-template and added-token digests; changing result or freeze schemas alone does not change this identity.

## Content that never enters the renderer

The following are evaluation-only or private and forbidden from model-visible input: expected verdict, completion state, hard-defect and slice labels, pair identity/direction, calibration/measurement role, sample/source/generator/reviewer identity, rationale anchor, Event or Version identity, Fact identity, producer, locator, category, tool, observation body, raw trace/evidence, transcript, reasoning, private context, participant/lifecycle/route state, and the rest of Team State.

Packet rows and annotation rows are physically separate tracked JSONL files. The renderer accepts only the packet mapping and fixed rubric; it has no annotation argument.

## Window, padding, batching, and overflow

The model config declares 40,960 positions and the tokenizer metadata declares 131,072, while the model card describes 16,384-token preference training and recommends inference within that length. Plan 054 adopts 16,384 only after exact-tokenizer census and a real mechanical forward at that length.

The fixed policy, qualification structure, canonical title, complete summary, optional handoff, and Evidence V1 are mandatory. Tokenizer truncation is disabled. If an input exceeds the adopted window, the renderer removes one whole oldest prior publication, increments the render-only `model_window_additional_oldest_omitted` count, then renders and tokenizes again. Product coverage omission and render-window omission remain distinct. If mandatory content still does not fit, the input is a typed failure and receives no score.

Unpadded inputs use an all-one attention mask. Batches use tokenizer pad ID 151654 and frozen right padding. Left padding is smoke-tested only as a parity counterfactual. A score is usable only when single, repeated, right-padded batch, and left/right counterfactual results agree within the scoring identity's absolute tolerance.

## Scalar contract

The exact checkpoint is `Qwen3ForSequenceClassification` with one label. The selected output is `logits[:, 0]`, pooled at the last non-pad token by the model implementation, shape `[batch, 1]`. The raw reward logit is unbounded and higher is better under the exact reward-model contract. Plan 054 applies the monotone stable sigmoid projection to the complete finite domain `[0, 1]`; it never infers direction or domain from observed measurement extrema.

The temporary evaluation threshold is calibration-only, selected by `temporary-threshold-rule-v1.json`, and is not a production threshold. Model, tokenizer, input template, adopted window, overflow encoding, padding, scalar projection/domain, temporary threshold, and pass rule all participate in the frozen measurement identity. Result and freeze schema revisions are independent from the unchanged scalar-definition identity.
