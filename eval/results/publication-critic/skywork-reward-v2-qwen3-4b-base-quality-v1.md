# Plan 079 Skywork 4B base quality — formal validation v1

**Terminal: `4B_BASE_QUALITY_NO_GO`.** The exact original BF16
`Skywork/Skywork-Reward-V2-Qwen3-4B@fd958fef475f323f4e6b195930e3dd918485c668`
completed one valid 55-row formal run, but no validation operating point met all frozen
publication-quality floors.

| | |
|---|---|
| Formal run | `plan079-formal-20260825T175912Z-610d880-r1` |
| Source | clean `610d880312c8ee9c98c28740f8b0b62c4fafb65f` |
| Model | official two-shard BF16 snapshot; content `7b241386…450a4` |
| Validation | physically unseen-free Plan 066 bundle; 55 candidates (34 PASS / 21 REWRITE), 19 boundary + 7 within-PASS pairs |
| Release SHA-256 | `757dd624c3d47f87dd5683d24f9f1753b1dbbffb42fdeff567c9e3e5e0b71a91` |
| Formal result | canonical `1034ee75…8ff7`; file `70c7272a…911a` |
| Runtime | Secure Cloud RTX 4090, CUDA 12.8, BF16, 4 CPU threads |

The compact machine-readable projection is
[`skywork-reward-v2-qwen3-4b-base-quality-v1.json`](skywork-reward-v2-qwen3-4b-base-quality-v1.json).
The complete 55 scores, operating curve, runtime and independently reproduced result remain in
the task-owned ignored Plan 079 namespace bound by the hashes in that projection.

## Result

| | 4B base | frozen floor | historical exact 1.7B base |
|---|---:|---:|---:|
| False PASS | 12/21 = `0.571` | ≤ `0.25` | 6/21 = `0.286` |
| False REWRITE | 4/34 = `0.118` | ≤ `0.35` | 13/34 = `0.382` |
| Balanced accuracy | `0.655` | ≥ `0.75` | `0.666` |
| ROC AUC | `0.6218` | ≥ `0.80` | `0.6169` |
| Boundary pairs | 13/19 = `0.684` | ≥ `0.70` | 15/19 = `0.789` |
| Within-PASS pairs | 6/7 = `0.857` | reported only | 6/7 = `0.857` |
| Selected threshold | `0.99988408` | per model | `0.94966937` |

The selected point was the frozen search rule's best fallback among 97 endpoints and adjacent
midpoints; it was not feasible. The run failed `no_admissible_operating_point`,
`roc_auc_floor_failed`, and `boundary_pair_floor_failed`. Typed failures were zero.

The larger base changes the error tradeoff rather than solving the task: it rejects fewer good
publications, but passes far more REWRITE rows. Its balanced accuracy is slightly lower than the
historical exact 1.7B base, ROC AUC is essentially unchanged, and boundary ordering is worse.
All 4B logits are strongly positive (`5.03125 … 15.6875`), with projected scores compressed into
`0.99351 … 0.99999985`; this calibration shift is why thresholds are fitted per model, but the
NO-GO follows from the whole operating curve, not from choosing a shared threshold.

## Runtime and scope

The formal run loaded in `12.35 s`, completed in `21.82 s`, had warm p95 model latency
`113.71 ms`, peak RSS `5,834,690,560` bytes and peak allocated/reserved VRAM
`8,251,679,232 / 8,501,854,208` bytes. Tokens ranged from 559 to 1,777; no row omitted an old
publication. Historical 1.7B timing came from different hardware and is not used as a speed or
memory comparison.

Commissioning first completed the same 55-row end-to-end path with terminal
`COMMISSIONING_COMPLETE`; it was not promoted or copied into the new empty formal namespace.
The formal result was independently recomputed locally and reproduced byte for byte. The campaign
authority prevents another complete formal result after this valid NO-GO.

No Judge was called, no unseen-test row was available to the cloud process, and no model was
trained, quantized, converted or written to Hugging Face. No selection lock, product identity,
local-deployment qualification or M3-D authorization was produced.

## Resource and cost handoff

The task Pod `iocp8k8w6zvh4s` was deleted and an exact-name lookup returned no Pod, so continuing
GPU cost is zero. The retained resource is 20 GB Standard network volume `v1us0nmk0p` in
`US-IL-1`; its observed Plan 079 task data is 8,242,665,809 bytes and its current rate is
`$0.00194444449/h` (`$0.07/GB/month`). The volume must not be deleted without separate approval.

At the `2026-08-25T18:14:05Z` billing snapshot, RunPod had settled `$0.00194444449` of volume
cost but had not yet emitted the deleted Pod's billing record. A conservative calculation using
at most 1,535 Pod seconds, the `$0.74/h` GPU price, 20 GB container-disk pricing, and two full
volume hours gives a total accrued ceiling of `$0.3207`. Therefore at least `$14.6793` of the
`$15` authorization remained. With only the retained volume continuing to bill at the current
rate, that headroom reaches the cap in at least about 7,549 hours / 314.5 days from the snapshot.
