# Plan 090 Route O clean confirmation — terminal v1

**Terminal: `ROUTE_O_CONFIRMATION_PASS`.** Two independent clean BF16 executions
from the exact 1.7B base passed the complete frozen rubric. The second retained
candidate also passed fresh-process no-update recovery. This confirms numerical and
execution repeatability on the same frozen validation cohort; it does not test random
seed sensitivity, independent-cohort generalization, unseen quality, or product
readiness.

The machine-readable projection is
[`plan090-route-o-confirmation-v1.json`](plan090-route-o-confirmation-v1.json).

| | |
|---|---|
| Source | clean `214f1379be44e066028f3166856b48098bbf695c`; archive `9f9685e9…` |
| Model | `Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc` |
| Data | v8 train 128 candidates / 58 pairs; validation 55 / 26; physically zero unseen rows |
| Recipe | one full-cohort update of the nine Route O Layer 27 tensors; 33,558,784 original parameters |
| Runtime | one secure US-TX-3 NVIDIA L40S; Torch 2.8.0+cu128; Transformers 4.52.3 |

## BF16 confirmation

Both `bf16-seed-20260901` and `bf16-seed-20260902` produced the same complete
validation signature and passed every frozen check:

| validation delta | each clean BF16 run |
|---|---:|
| Raw boundary mean pair margin | `+0.00390625` |
| Projected boundary mean pair margin | `+0.0008611325` |
| Raw within-PASS mean pair margin | `-0.0033482143` |
| Projected within-PASS mean pair margin | `+0.0001389426` |
| ROC AUC | `+0.0014005602` |
| Weighted validation objective | `+0.0002800829` |
| Balanced / best balanced / false-PASS / strict rates | unchanged |

The distinct seeds are metadata only: the frozen path has no shuffle, active dropout,
or other bound seed-sensitive consumer. Therefore
`seed_sensitive_stability_tested=false`; the result must not be described as random
seed stability.

The retained second BF16 checkpoint is 3,591,369,941 bytes with content SHA-256
`8b4b88b66a88cc50fa10d5f20c575b9a67c6f254f6e26350d38ce4896b949a69`.
A different OS process loaded it without an update and verified model, optimizer,
scheduler, RNG, data, and checkpoint identity. It remains only on network volume
`mwemzrn33y`; the superseded first BF16 checkpoint was removed after recovery closure.

## FP32 condition control

The conditional FP32 branch ran from the exact base with float32 model parameters,
forward outputs, selected gradients, optimizer state, and saved parameters; autocast
and TF32 were disabled. It did not pass the same rubric: raw boundary moved
`-0.0065941466`, while projected boundary moved `+0.0062063820`; projected
within-PASS improved `+0.0029911204` and ROC AUC was unchanged. This supports a
precision-path sensitivity diagnosis and raw/projected divergence, not a strict
update-only causal claim. The diagnostic FP32 result does not automatically veto the
two valid BF16 clean repetitions. Its checkpoint was removed after the small result
was finalized.

## Resource, cost, and retained evidence

The conservative Plan 090 cost is `$0.71`, below the `$6` hard cap. The task Pod was
stopped and deleted; the terminal live observation at `2026-08-27T03:45:47Z` showed
zero Pods and compute `$0/h`. Existing 57GB volume `mwemzrn33y` remains in `US-TX-3`
at its separate `$0.006/h` retained-volume rate and was not resized or deleted.

The exact-tree-verified final ignored handoff contains 27 small files totaling
2,116,244 bytes with manifest content SHA-256
`94c41dcd77742bfce29924cbebc027861eb5c65793209c57890045b8bb151bd9`.
The separate commissioning handoff contains four files totaling 1,233,696 bytes with
manifest content SHA-256
`bb24469329580a660a6303f7da7a6610509947d82ebbd5eb1e2cf7643e5f5497`.

No local model, Cargo, or Docker ran. No Judge, real API, unseen row, HF upload,
publication, quantization, multi-GPU run, alternate GPU, region change, or network
volume mutation occurred.
