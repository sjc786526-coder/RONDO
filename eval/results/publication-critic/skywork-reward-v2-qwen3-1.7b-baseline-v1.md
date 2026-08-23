# Skywork Reward V2 Qwen3 1.7B Publication Critic baseline v1

> **Superseded historical attempt.** Independent review found that this v1 freeze did not correctly bind the
> model-visible rubric revision/output shape, did not exercise every scored row across alternate batch
> compositions, and described the title's message placement incorrectly. Its finite scalars and resource facts
> are retained, but it is not formal Plan 054 acceptance evidence. The corrected v2 result will be the authority.

Plan 054 measured the immutable `Skywork/Skywork-Reward-V2-Qwen3-1.7B` revision
`e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc` on a frozen, product-shaped M3-A2 cohort. The cohort is
representative and boundary-oriented; it is not the future unseen M3-B1a test set. The historical
machine-readable result is
[`skywork-reward-v2-qwen3-1.7b-baseline-v1.json`](skywork-reward-v2-qwen3-1.7b-baseline-v1.json).

## Frozen measurement

- Freeze commit: `4de338384f4d9303b56e9aba9a674a3f5cd59776`; freeze SHA-256:
  `87f71aca9d2233129e7b63e934daf614c0b3a8ebfedd1cfdec3939e961c6fd85`.
- Model weight: one 3,441,189,792-byte safetensors file, SHA-256
  `117da8e3a6c3e9c9b9b66e74d69373b8f186e7fe27be2d64e0bb18510c9a07d9`; Apache-2.0 model card;
  local cache verified against all locked repository files.
- Input: PublicationPacket v1 parity fixture, qualification rubric v1, deterministic two-message render,
  immutable tokenizer chat template, complete candidate, no supervision or private state.
- Window: 16,384 tokens. Only complete oldest continuity items may be dropped, with explicit additional
  omission; required content overflow is a typed failure and tokenizer truncation is disabled.
- Scalar: `Qwen3ForSequenceClassification.logits[:, 0]`, last-non-padding-token pooling, higher is better,
  stable sigmoid to `[0, 1]`, `score >= threshold` means `PASS`.
- Runtime: CPU FP32, four threads, batch size four, right padding, eval/inference mode. FP32 passed repeated,
  single-vs-batch and left-vs-right parity at absolute tolerance `1e-4`. CPU BF16 returned finite scalars but
  failed that frozen batch-parity tolerance and was excluded before measurement.
- Temporary evaluation threshold: `0.9350569011196121`, derived from eight calibration samples by the frozen
  rule; measurement labels were not used.

## Result

The formal run `plan054-20260823T021754Z-measurement-fp32` produced 16 valid scores and zero typed failures.

| Metric | Result |
|---|---:|
| Accuracy | 0.6875 |
| Balanced accuracy | 0.6875 |
| ROC AUC | 0.765625 |
| True pass / true rewrite | 6 / 5 |
| False pass / false rewrite | 3 / 2 |
| Atomic boundary pair wins | 7 / 8 (0.875) |
| Raw logit min / p50 / p95 / max | 1.2723 / 3.0003 / 6.4733 / 6.4733 |
| Projected score min / median / max | 0.7811 / 0.9524 / 0.9985 |

Class accuracy was 1.00 for existing/completed, 0.75 for existing/incomplete, 0.75 for new/incomplete, and
0.25 for new/completed. All three false passes carried the `internal_consistency` defect slice. Both false
rewrites were new/completed PASS samples. Existing-event accuracy was 0.875; new-event accuracy was 0.50.
The strong 7/8 atomic ranking and 0.765625 AUC show useful ordering signal, but the thresholded hard-error rate
is too high for direct product use.

The exact tokenizer census covered 24 quality samples plus two census-only cap cases. Counts ranged from 564
to 13,417 tokens (median 589.5). Quality samples required at most 865 tokens and no quality sample overflowed.
The maximum Unicode/byte/history cap case dropped all four oldest history items as whole units and kept the
complete candidate at 13,417 tokens; the scalar-cap case used 1,012 tokens.

CPU model load took 3.45 seconds. Formal measurement wall time including load was 83.95 seconds. Batched
forward latency attributed per sample was p50 4.73 seconds and p95 6.40 seconds. Process lifetime peak RSS was
10,711,810,048 bytes; watchdog sampled peak memory was 7,673,860,096 bytes, swap peak was zero, and no resource
stop occurred. The 16,384-token mechanical smoke was finite and took 204.74 seconds. No GPU or Docker path was
used.

## Decision and M3-B1a handoff

- **Engineering GO**: the exact checkpoint, tokenizer, render, scalar, 16k context and FP32 batch path are
  locally usable and reproducible under the project watchdog.
- **Direct-product NO-GO**: the unfinetuned base model must not be wired into the product as a qualified
  Publication Critic. Three of eight REWRITE examples passed, and new/completed qualification was especially
  weak.
- **Training-data GO**: M3-B1a can use this frozen input/eval contract and baseline to build its own formal
  train/validation/unseen-test split. Highest-value additions are polished hard negatives for internal
  consistency; new/completed useful-state versus process-dump and scope failures; threshold-near handoff
  empty/null/present pairs; and balanced continuity/evidence omission cases that avoid verbosity, length,
  role, or template shortcuts.

M3-C1 remains unopened and continues to wait for M3-B1c to produce at least one trained candidate.
