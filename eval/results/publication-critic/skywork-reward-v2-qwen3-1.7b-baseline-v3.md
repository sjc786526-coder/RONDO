# Skywork Reward V2 Qwen3 1.7B Publication Critic baseline v3

Plan 054 measured immutable `Skywork/Skywork-Reward-V2-Qwen3-1.7B` revision
`e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc` on the frozen M3-A2 representative/boundary cohort. This
cohort is not the future unseen M3-B1a test set. The authoritative machine-readable result is
[`skywork-reward-v2-qwen3-1.7b-baseline-v3.json`](skywork-reward-v2-qwen3-1.7b-baseline-v3.json).

## Frozen measurement identity

- Code commit: `3206c953bcab506f6bff61297862fd274c5f6a3b`; freeze SHA-256:
  `06fc9e356d98f1f28ee4528c56cbde849bfd5fcacd298c278ab162aa93f18020`.
- Model weight: one 3,441,189,792-byte safetensors file, SHA-256
  `117da8e3a6c3e9c9b9b66e74d69373b8f186e7fe27be2d64e0bb18510c9a07d9`; the twelve locked repository
  files verify offline. The public model card declares Apache-2.0.
- Qualification: PublicationPacket v1 and model-visible `rondo-publication-qualification@v1`. Render v2
  preserves the exact two-message bytes while correctly declaring the title in the user packet and accounting
  its semantic tokens to the candidate bucket; summary and handoff remain in the assistant candidate.
- Runtime: `Qwen3ForSequenceClassification.logits[:, 0]`, output shape `[batch, 1]`, last non-pad pooling,
  higher raw reward is better, stable sigmoid to `[0, 1]`, CPU FP32, four threads, batch size four, right-padding
  production path, eval/inference mode. Every scored row must pass single, repeated single, standard right/left
  batch and alternate right-batch composition parity at absolute tolerance `1e-4`.
- Window: 16,384 tokens. Required candidate content is never silently truncated; only whole oldest continuity
  items may be dropped, followed by explicit additional-omission encoding. A required-content overflow is a
  typed input failure.
- Temporary threshold: `0.9350569011196121`, derived only from eight calibration rows by the frozen rule.
  Calibration result SHA-256 `ffc4e10dd03dd56980c1c1e3e91e22f42b594a463345bbfb4ac716a120d7d456`
  is checked by the formal runner; measurement labels were not used.
- Declared error slices: `new_event`, `existing_event`, `completed`, `incomplete`, `continuity_available`,
  `continuity_unavailable`, `freshness_known_stale`, `evidence_count_omitted`, `handoff_empty` and `unicode`.
  The runner requires every declared key in both the frozen measurement cohort and final `quality.by_slice`.
  Atomic pair ranking remains a separate frozen metric rather than a nonexistent annotation slice.

The completed calibration run `plan054-20260823T040900Z-calibration-v2` covered all eight scored rows across
the five parity modes. Its maximum projected delta was `1.5709748450998262e-06`. The independent 16,384-token
mechanical forward was finite with output shape `[1, 1]` and took 196.64 seconds. The two product-cap probes are
token-census-only rows, not threshold/quality rows; they remain in the exact tokenizer census rather than being
misrepresented as scored examples.

## Formal result

Run `plan054-20260823T051600Z-measurement-v3` produced 16 valid scores and zero typed failures. Its raw result
SHA-256 is `6fbee12edb217a599a7995488d7208d4fe628df759c31f3c8b56d46229561bd1`.

| Metric | Result |
|---|---:|
| Accuracy | 0.6875 |
| Balanced accuracy | 0.6875 |
| ROC AUC | 0.765625 |
| True pass / true rewrite | 6 / 5 |
| False pass / false rewrite | 3 / 2 |
| Atomic boundary pair wins | 7 / 8 (0.875) |
| Measurement parity maximum projected delta | 0.0000045237 |
| Raw logit min / p50 / p95 / max | 1.2723 / 3.0003 / 6.4733 / 6.4733 |
| Projected score min / median / max | 0.7811 / 0.9524 / 0.9985 |

All ten declared slices were present in the formal result. Their accuracies were: new event 0.50, existing event
0.875, completed 0.625, incomplete 0.75, continuity available 0.75, continuity unavailable 1.00, known-stale
freshness 1.00, evidence-count omitted 0.50, empty handoff 0.00 and Unicode 0.75.

Class accuracy was 1.00 for existing/completed, 0.75 for existing/incomplete, 0.75 for new/incomplete and
0.25 for new/completed. The false passes were `pc-v1-meas-ei-b-rewrite`, `pc-v1-meas-nc-a-rewrite` and
`pc-v1-meas-ni-a-rewrite`; all three carry the `internal_consistency` slice. The false rewrites were the two
new/completed PASS rows `pc-v1-meas-nc-a-pass` and `pc-v1-meas-nc-b-pass`. Seven of eight atomic PASS/REWRITE
pairs ranked correctly. The ordering signal is useful, but the thresholded hard-error rate is too high for
direct product use.

The exact tokenizer census covered 24 quality rows plus two census-only cap rows. Counts ranged from 564 to
13,417 tokens (median 589.5); quality rows required at most 865 tokens. The max Unicode/byte/history cap row
dropped four oldest publications as whole units and retained the complete candidate at 13,417 tokens. Render v2
changed only semantic bucket ownership: aggregate candidate tokens are 14,516 and packet-framing tokens 1,482;
model-visible bytes and total token counts did not change.

Formal measurement wall time including model load and all parity forwards was 416.82 seconds; model load took
7.32 seconds. Standard right-batch forward latency attributed per sample was p50 4.73 seconds and p95 6.35
seconds. Process lifetime peak RSS was 10,658,586,624 bytes; watchdog sampled peak memory was 9,842,864,128
bytes. Swap peak was 14,467,072 bytes, far below the watchdog stop thresholds, and `stop_reason=none`. No GPU,
Docker, paid API, training or external write was used.

## Decision and M3-B1a handoff

- **Engineering GO**: exact model/tokenizer loading, the product-shaped render, scalar projection, 16k context
  and the frozen CPU FP32 batch path are locally usable and reproducible under the project watchdog.
- **Direct-product NO-GO**: the unfinetuned base model must not be wired into the product as a qualified
  Publication Critic. Three of eight REWRITE rows passed, and new/completed qualification remains weak.
- **Training-data GO**: M3-B1a may reuse this input/evaluation contract and baseline while creating its own
  formal train/validation/unseen-test split. Highest-value additions are polished `internal_consistency` hard
  negatives, new/completed useful-state versus process-dump/scope boundaries, threshold-near handoff variants,
  and balanced continuity/evidence-omission contrasts without length, role or template shortcuts.

M3-C1 remains unopened and continues to wait for M3-B1c to produce at least one trained candidate.
