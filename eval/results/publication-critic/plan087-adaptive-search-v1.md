# Plan 087 adaptive original-parameter search — terminal v1

**Terminal: `PROMISING_CANDIDATE_RETAINED`.** A budget-bounded search over the exact
original BF16 `Skywork/Skywork-Reward-V2-Qwen3-1.7B` revision retained Route O as a
small but distributed research improvement. This is not a product GO, unseen result,
M3-C2 result, or clean formal reproduction.

| | |
|---|---|
| Search | `plan087-formal-20260826-01`; 15 exact-base routes A–O |
| Source | clean `6dd27d8cd7cc6447c2f6762a3054c55d64dc3237` |
| Model | `e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`; 1,720,577,024 BF16 parameters |
| Data | v8 train 128 candidates / 58 pairs; validation 55 candidates / 26 pairs; physically zero unseen rows |
| Runtime | one secure-cloud NVIDIA L40S; Torch 2.8.0+cu128; Transformers 4.52.3 |
| Candidate | `route-o-internal-transformations`; one full-cohort update; 33,558,784 trainable original parameters |

The machine-readable projection, including every route disposition, is
[`plan087-adaptive-search-v1.json`](plan087-adaptive-search-v1.json).

## Result

| validation measure | exact base | Route O | delta |
|---|---:|---:|---:|
| Raw boundary mean pair margin | `0.810444` | `0.814350` | `+0.003906` |
| Projected boundary mean pair margin | `0.083556` | `0.084417` | `+0.000861` |
| Raw within-PASS mean pair margin | `0.375000` | `0.371652` | `-0.003348` |
| Projected within-PASS mean pair margin | `0.015237` | `0.015376` | `+0.000139` |
| ROC AUC | `0.620448` | `0.621849` | `+0.001401` |
| Boundary / within-PASS strict wins | `15/19`, `6/7` | `15/19`, `6/7` | unchanged |
| Report-threshold balanced accuracy / false-PASS | `0.571429`, `0.857143` | `0.571429`, `0.857143` | unchanged |
| Best operating balanced accuracy | `0.665966` | `0.665966` | unchanged |

The raw boundary improvement was spread across 7 improved, 9 unchanged and 3 worse
pairs; projected boundary changed across 13 improved, 1 unchanged and 5 worse pairs.
Projected within-PASS and ROC also rose. The small raw within-PASS regression did not
change its strict wins, report-threshold errors, or the best operating point. This
combination supports retaining a research candidate, but the signal is too small and
the calibration metrics too weak to imply product readiness.

## Candidate and recovery

Route O reused the Route F seed and objective: AdamW at `5e-6`, constant scheduler,
BF16, one full v8 train cohort, and binary / boundary / within-PASS weights of
`0.05 / 0.25 / 0.70`. Its nine-tensor scope is the final block's attention Q/K/V
input projections, Q/K norms, MLP gate/up projections, and the two internal layer
norms. Failed output projections were excluded.

The selected 3,591,448,949-byte checkpoint
`checkpoint-attempt-000-step-000001` has content SHA-256
`d08ff2566d719b3aef4dd58158e86b1c374faf2021cc96a140d878b79857c923`.
A fresh OS process restored the exact model, optimizer, scheduler, RNG, data and route
state without performing another update. The retained remote paths are under
`/workspace/rondo-plan087-20260826-search01/formal-search/route-o-artifacts/` on
volume `mwemzrn33y`; the checkpoint and model snapshot remain remote only.

Routes A–N closed as non-promising after complete observations. They covered terminal
block depth, head/norm, output-projection ablations, lower rates, pair-heavy objectives
and a four-block scope. Search stopped immediately after Route O qualified; it did not
spend the remaining authorization on a redundant clean replay.

## Resource, cost and handoff

The live baseline balance was `$9.1252646939`, fixing the task budget at
`$8.9852646939`. The terminal balance was `$6.2192572691`; provider task-window Pod
billing observed by terminalization was `$1.9811751181`. The balance delta was
`$2.9060074248`, while the independently accumulated wall-clock ledger was the largest
measure at a conservative `$3.009`, leaving `$5.9762646939` of task authorization.

The exact task Pod was stopped and deleted. The terminal account observation has zero
Pods and `$0/h` compute. Existing volume `mwemzrn33y` remains in `US-TX-3`, was expanded
only to 57 GB, and continues at `$0.006/h`; it was not deleted. Plan 082 roots remain
read-only and the only retained large Plan 087 artifacts are the recovery-qualified
candidate under the independent task root.

The local ignored handoff contains 18 exact-tree-verified small files totaling 573,701
bytes at
`/home/sjc/desktop/RONDO/eval-data/publication-critic/plan087/stage-b/live-20260826/handoff`.
Its manifest content SHA-256 is
`35b06de1729c7f845630d7c8bf727ea0d3f83723ea3115569b2c17f6bd9a2a39`.
The final terminal result content SHA-256 is
`b88aef24d004789ea836305b151df8c4276aa56ca8ca281426327776fa74587c`.

No local model, Cargo or Docker ran; no Judge, real API, unseen row, HF upload,
publication, quantization, multi-GPU run or third GPU type was used.
