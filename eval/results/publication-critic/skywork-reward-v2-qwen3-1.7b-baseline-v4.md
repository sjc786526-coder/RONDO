# Skywork Reward V2 Qwen3 1.7B Publication Critic baseline v4

Plan 054 measured immutable `Skywork/Skywork-Reward-V2-Qwen3-1.7B` revision
`e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc` on the frozen M3-A2 representative/boundary cohort. This
cohort is not the future unseen M3-B1a test set. The authoritative machine-readable result is
[`skywork-reward-v2-qwen3-1.7b-baseline-v4.json`](skywork-reward-v2-qwen3-1.7b-baseline-v4.json). V1 through
v3 remain superseded historical attempts; their valid scalar observations are not the final input-contract evidence.

## Frozen measurement identity

- Implementation commit: `ea5463cf28cc0389f73c3d5b4d1b7d81f12a8fe2`; measurement freeze commit:
  `667a69d9c9d2bc109341ee34834d3f3ad717be84`; freeze SHA-256:
  `2a8081d3700f4209f5ac3cd7dabb7f6d31d0cb0b0ea0e9e8c639c8f10dbebfeb`.
- Model weight: one 3,441,189,792-byte safetensors file, SHA-256
  `117da8e3a6c3e9c9b9b66e74d69373b8f186e7fe27be2d64e0bb18510c9a07d9`; all twelve locked repository
  files verify offline. The public model card declares Apache-2.0.
- Product input: the Python strict loader enforces the same PublicationPacket v1 mechanical text, integer,
  prior-publication, omission and visible-evidence limits as the Rust product validator. Packet and supervision
  rows remain physically separate.
- Render v3 emits exactly one user and one assistant message. Literal `<` in every dynamic product string is
  reversibly encoded as JSON `\u003c`, so legal text cannot become a Qwen control token. The exact tokenizer must
  observe registered IDs `151644,151645,151644,151667,151668,151645`; the four message-envelope IDs are the only
  special-token bucket entries. Input-template revision
  `v3-sha256-dc3209af0d284dfe4be57403873717ba5f2790e2257cd4a39a2376de5696044c` binds the render contract,
  renderer, rubric, immutable chat template and added-token vocabulary.
- Scalar identity remains `e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc-fp32-v1`: one
  `Qwen3ForSequenceClassification.logits[:, 0]` reward logit, last-non-pad pooling, higher-is-better and stable
  sigmoid projection to `[0, 1]`. Result-schema changes do not rename this unchanged scalar.
- Runtime is CPU FP32, four threads, batch size four, right padding, eval/inference mode. Every scored row must
  pass single, repeated single, standard right/left batch and alternate right-batch composition parity at absolute
  tolerance `1e-4`.
- The adopted window is 16,384 tokens. Required candidate content is never silently truncated; only whole oldest
  continuity items may be dropped, with explicit additional omission. Required-content overflow is a typed failure.
- Threshold `0.9350569011196121` was derived only from eight calibration rows by the frozen rule; measurement
  labels were not used.

Calibration run `plan054-20260823T062100Z-calibration-v4` came from the clean implementation commit. Its artifact
SHA-256 is `14062beac6d8eee3d48665a76e9b9dcbf73182abbe999ef5aa08bc69412e58d1`. All eight rows passed the five
parity modes with maximum projected delta `1.5709748450998262e-06`. The independent 16,384-token mechanical
forward returned one finite scalar in 189.62 seconds. The tracked result contains the eight compact calibration
row projections, threshold derivation, context smoke, FP32 identity and successful watchdog projection.

## Formal result

Run `plan054-20260823T064300Z-measurement-v4` produced 16 valid scores and zero typed failures from the committed
freeze. Raw result SHA-256 is `a70cbdf0bf24f5fccb94be1b5711922cfbd375cb9d5437db93796dc579254ca1`; the tracked
JSON SHA-256 is `26534ab028dc951acd18251926dfdeaa61dd4674b477b074618a7eb891e97340`. The tracked JSON equals the raw
artifact plus its SHA and the post-run measurement watchdog projection, and its quality block was independently
recomputed from the 16 rows.

| Metric | Result |
|---|---:|
| Accuracy / balanced accuracy | 0.6875 / 0.6875 |
| ROC AUC | 0.765625 |
| True pass / true rewrite | 6 / 5 |
| False pass / false rewrite | 3 / 2 |
| Atomic boundary pair wins | 7 / 8 (0.875) |
| Measurement parity maximum projected delta | 0.0000045237 |
| Raw logit min / p50 / p95 / max | 1.2723 / 3.0003 / 6.4733 / 6.4733 |
| Projected score min / median / max | 0.7811 / 0.9524 / 0.9985 |

All ten declared slices are present. Accuracy is 0.50 for new event, 0.875 for existing event, 0.625 for
completed, 0.75 for incomplete, 0.75 for continuity available, 1.00 for continuity unavailable, 1.00 for
known-stale freshness, 0.50 for evidence-count omitted, 0.00 for empty handoff and 0.75 for Unicode. Class
accuracy is 1.00 for existing/completed, 0.75 for existing/incomplete, 0.75 for new/incomplete and 0.25 for
new/completed.

The false passes are `pc-v1-meas-ei-b-rewrite`, `pc-v1-meas-nc-a-rewrite` and
`pc-v1-meas-ni-a-rewrite`; all three carry `internal_consistency`. The false rewrites are the two new/completed
PASS rows `pc-v1-meas-nc-a-pass` and `pc-v1-meas-nc-b-pass`. Seven of eight atomic pairs rank correctly. The
ordering signal is useful, but the thresholded hard-error rate remains too high for direct product use.

The exact tokenizer census covers 24 quality rows plus two census-only product-cap rows. Counts range from 564
to 13,417 tokens (median 589.5). One cap row drops four oldest publications as whole units and retains the complete
candidate. Aggregate buckets reconcile to 29,478 tokens: candidate 14,516; policy 8,450; cross-segment framing
2,912; continuity 1,546; packet framing 1,482; Evidence V1 468; and special tokens 104 (exactly four per row).

Formal measurement wall time including model load and all parity forwards is 407.35 seconds; model load is 3.97
seconds. The four actual standard right-batch wall times range from 16.32 to 25.15 seconds, with P50 18.60 and P95
25.15 seconds. Amortized batch compute per sample has P50 4.65 and P95 6.29 seconds; it is not presented as
single-request latency. Aggregate standard-batch throughput is 0.2034 samples/second.

Calibration process peak RSS is 10,706,890,752 bytes and watchdog sampled peak memory is 10,550,005,760 bytes.
Measurement process peak RSS is 10,692,800,512 bytes and watchdog sampled peak memory is 8,496,590,848 bytes.
Both runs have zero sampled swap, `run_rc=0`, `stop_reason=none` and `cleanup_reason=none`. Measurement ended with
190,517,198,848 bytes available on Windows C:. No GPU, Docker, paid API, training or external write was used.

## Decision and M3-B1a handoff

- **Engineering GO**: the exact model/tokenizer, control-token-safe PublicationPacket render, scalar projection,
  16k context and frozen CPU FP32 batch path are locally usable and reproducible under the project watchdog.
- **Direct-product NO-GO**: the unfinetuned base model must not be wired into the product as a qualified
  Publication Critic. Three of eight REWRITE rows passed, and new/completed qualification remains weak.
- **Training-data GO**: M3-B1a may reuse the v4 input/evaluation contract and baseline while creating its own
  formal train/validation/unseen-test split. Highest-value additions remain polished `internal_consistency` hard
  negatives, new/completed useful-state versus process-dump/scope boundaries, threshold-near handoff variants,
  and balanced continuity/evidence-omission contrasts without length, role or template shortcuts.

M3-C1 remains unopened and continues to wait for M3-B1c to produce at least one trained candidate.
