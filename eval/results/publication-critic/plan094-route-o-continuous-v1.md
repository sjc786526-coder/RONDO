# Plan 094 Route O continuous training — terminal v1

**Terminal: `ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT`.** The clean formal
trajectory reached the pre-frozen step-4 no-material plateau. It is a valid
negative completion of the research trajectory, not an infrastructure failure.
The exact task Pod has been stopped and deleted, account-wide zero Pods and
compute `$0/h` are confirmed, and the zero-Pod finalizer has completed.
Final independent review accepted the implementation and task outcome with no
remaining High/Medium correctness or functionality finding.

The machine-readable projection is
[`plan094-route-o-continuous-v1.json`](plan094-route-o-continuous-v1.json).

| | |
|---|---|
| Formal source | clean `c6b50690a68a1891154888ef0c253a9c9bb89751`; archive `61dfbce1…` |
| Model | exact `Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc` |
| Data | v8 train 128 candidates / 58 pairs; validation 55 / 26; physically zero unseen rows |
| Recipe | one full-cohort update per step of the nine Route O Layer 27 tensors; 33,558,784 original parameters |
| Runtime | one Secure US-TX-3 NVIDIA L40S; Torch 2.8.0+cu128; Transformers 4.52.3 |

## Formal trajectory

The guarded Plan 090 import correctly rejected an incompatible historical cursor,
so the formal run used the pre-frozen exact-base step-1 rebuild fallback in a clean
namespace. No partial state was stitched into the formal trajectory.

| step | raw Boundary | projected Boundary | raw Within-PASS | projected Within-PASS | ROC AUC | material event |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | `+0.00390625` | `+0.0008611325` | `-0.0033482143` | `+0.0001389426` | `+0.0014005602` | 0 |
| 2 | `-0.0051398026` | `+0.0009140888` | `-0.0111607143` | `-0.0000381899` | `+0.0007002801` | 0 |
| 3 | `-0.0100740132` | `+0.0013165490` | `-0.0100446429` | `+0.0001825811` | `+0.0014005602` | 0 |
| 4 | `-0.0106907895` | `+0.0014192417` | `-0.0066964286` | `+0.0004798015` | `+0.0007002801` | 0 |

Balanced accuracy, best-balanced accuracy, false-PASS rate, and both strict win
rates were unchanged at every observation. Projected margins drifted upward, but
raw margins reversed after step 1 and no ranking, strict, or operating event fired.
The frozen rule therefore stopped at step 4 with
`prefrozen_three_checkpoint_no_material_plateau`; the valid negative is final and
will not be rerun to seek a positive result.

## Recovery and retained evidence

Distinct OS processes restored step 2 and step 3 and continued to the next effective
update. The retained recovery role is step 3, which process
`0ee15753a7b1495491b90a9bfecce008` restored before producing step 4.

The mounted-volume qualification deep-read all three retained Plan 094 checkpoints
(steps 1, 3, and 4) and bound recovery/latest roles to controller state
`58558c50…`. Its receipt content SHA-256 is `0f0d9133…`. Large weights remain under
`/workspace/rondo-plan094-20260827-stageb01` on network volume `mwemzrn33y`; the
task root is about 13.22GB. The returned 2,017,280-byte small handoff contains 181
members, has SHA-256 `a0b227bd…9ea4`, and contains no checkpoint weights or
source/data tar.

## Budget and resource closure

The `2026-08-27T09:27:44Z` terminal snapshot gives a conservative Plan 094 cost of
`$1.69`, below the `$5` hard cap. The `$0.82` closure reserve includes a conservative
`$0.06` for at least six hours of post-completion volume retention. The existing
volume was expanded only when needed from 57GB to 70GB; the later authorization up
to 120GB was not needed.

Pre-release review accepted all Pod-dependent work at commit `a517820`. The exact
terminal helper then stopped and deleted Pod `0bsry5tbei7p4o`; both its sanitized
receipt and an independent live query observed an empty account Pod list. Account
spend fell from `$1.00/h` to the retained 70GB volume rate of `$0.007/h`, so compute
is `$0/h`. The volume remains in US-TX-3 and was not deleted or further resized.

The local finalizer consumed only the returned small handoff, the checkpoint
qualification receipt, the zero-Pod resource state, and the terminal budget. It
replayed the four formal overlays and produced content SHA-256
`7dead9d3c180fae468fa1e0bf2bd19b069158f3016a232d446ced1ecf6447ce6`, with
`all_task_pods_released=true`, `fresh_process_restore_and_continue=true`, and the
same valid-negative outcome. No Pod was rebuilt and no qualification or training
was rerun.

No local model, Cargo, or Docker ran. No Judge, real API, unseen row, HF upload,
publication, product action, quantization, multi-GPU run, alternate GPU, region
change, second volume, or volume deletion occurred.
