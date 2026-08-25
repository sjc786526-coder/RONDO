# M3-C2 Publication Critic joint selection — formal validation v1

**Terminal: `NO-GO`.** No candidate reached the frozen publication quality floors on the
v8 validation split, so no selection lock was produced and unseen-test remains sealed.

| | |
|---|---|
| Run | `plan073-formal-20260825T084317Z-selection-v1` |
| Selection freeze SHA-256 | `6740e4a4b663813d07f147240680a07f137b6154e8453943397916db09869600` |
| Validation release SHA-256 | `757dd624c3d47f87dd5683d24f9f1753b1dbbffb42fdeff567c9e3e5e0b71a91` |
| Validation result SHA-256 | `2b36eb4b408ff9a1a6a9830429fb806e9e2df1e54b6374755b98febb3cc98915` |
| Source | clean `65932d69fcdfe9cdb6099f5b0478667f0ca72cfc` |
| Cohort | frozen `publication-critic-v8` validation: 55 candidates (34 PASS / 21 REWRITE), 19 boundary + 7 within-PASS pairs |
| Runtime | original safetensors, CUDA BF16, 4 CPU threads, one model loaded at a time — unchanged from Plan 071 |
| Judge | `claude-opus-5` via the Claude Code subscription, 7 blinded batches, 2026-08-25 |

Numbers, per-item scores and slice tables are in
[`m3-c2-joint-selection-v1.json`](m3-c2-joint-selection-v1.json).

## Result

| | base | C1 | C3 | floor |
|---|---|---|---|---|
| False PASS | 6/21 = `0.286` | 20/21 = `0.952` | 5/21 = `0.238` | ≤ `0.25` |
| False REWRITE | 13/34 = `0.382` | 0/34 = `0.000` | 18/34 = `0.529` | ≤ `0.35` |
| Balanced accuracy | `0.666` | `0.524` | `0.616` | ≥ `0.75` |
| ROC AUC | `0.6169` | `0.3894` | `0.5567` | ≥ `0.80` |
| Boundary pairs | 15/19 = `0.789` | 5/19 = `0.263` | 10/19 = `0.526` | ≥ `0.70` |
| Within-PASS pairs | 6/7 | 2/7 | 1/7 | reported only |
| Selected threshold | `0.94966937` | `0.00000001` | `0.13846179` | per candidate |
| Admissible | no | no | no | |

Each candidate got its own threshold from the same frozen search over every operating point
(all endpoints plus adjacent midpoints of its own scores), because fine-tuning changed score
calibration and one shared number would report calibration drift as quality. The choice of
threshold is not what caused the `NO-GO`: **no point anywhere on any candidate's curve reaches
the balanced-accuracy floor**. The best balanced accuracy available is `0.666` for base,
`0.524` for C1 and `0.616` for C3, across 105, 21 and 43 operating points respectively.

Typed failures were zero for all three, and all three passed every runtime gate identically
(load `2.9–3.2 s`, warm p95 `219–222 ms`, peak RSS `4.30 GB`, peak VRAM `3.64 GB`). Runtime
could not separate them — they are the same architecture and size — so it was used only as a
usability gate, never as a ranking key.

## What the blinded Judge showed

Opus 5 judged all 55 publications blind: no reference labels, no pair direction, no split name,
no model identity and no model scores, under opaque item ids in a salted deterministic order.

- **Opus 5 agreed with the frozen GPT-5.6-sol labels on 53/55 = `0.964`** (disagreeing only on
  `pc064-consistency-014-binary` and `pc064-useful-09-qminus`).
- The three models agreed with Opus 5 on `0.655` (base), `0.600` (C1) and `0.582` (C3).

Two independent quality views — the frozen teacher labels and a heterogeneous judge that never
saw them — converge almost completely, and all three candidate models diverge from both by
roughly the same large margin. The evidence points at the models, not at the labels. The Judge's
gate was therefore active but never reached: the run had already ended in `NO-GO` with no
leading candidate to sanity-check.

## Why the fine-tuned candidates are worse than base

The training run collapsed the reward head's output range:

| | raw logit range on validation |
|---|---|
| base | `-2.3438 … 7.2188` (span `9.56`) |
| C1 | `-19.2500 … -18.0000` (span `1.25`) |
| C3 | `-2.0781 … -1.7812` (span `0.30`) |

C1's ROC AUC of `0.3894` is *below* chance — its ordering is anti-correlated with publication
quality — and it passes essentially everything (20 of 21 REWRITE rows). C3 is closer to base in
scale but near chance at `0.5567`, and it over-blocks: 18 of 34 good publications rejected.

Plan 068/071 qualified C1 and C3 because those were deployment-comparability gates: they asked
whether the deployed artifact reproduces its own CPU FP32 reference, its own fresh worker and its
own service verdict. A model collapsed to a near-constant output satisfies all of that
trivially. M3-C2 is the first gate that asks whether the model is *right*, and that is where the
collapse becomes visible.

Where base does have signal it is on scope and evidence handling (`scope_and_signal` `0.786`,
`evidence_none` `0.750`, `continuity_available` `0.741`); it is weakest on
`internal_consistency` (`0.545`, n=11) and `useful_state_transfer` (`0.556`, n=9). C3 inverts
this: it collapses on continuity- and evidence-bearing publications (`continuity_available`
`0.407`, n=27) almost entirely through false REWRITE. All slice denominators are in the JSON;
none of them is a gate, because validation slices go down to a single row.

## Scope

This report covers the offline joint comparison only. Because validation produced no admissible
candidate:

- no selection lock exists, so **unseen-test was never released, rendered, scored or judged**;
- no model, threshold or runtime configuration is frozen for the product;
- the Plan 055 service descriptor was not updated and no service parity run was performed;
- Publication Critic remains default-off and M3-D remains locked.

The thresholds above are selection-search artifacts on validation, not product thresholds.
Validation numbers are also optimistic by construction, since the threshold was fitted on the
same rows — the blind confirmation that would have removed that optimism was correctly never run.

The result is exactly recomputable: `evaluate_validation` rebuilt from the archived freeze,
release, per-candidate scores and Judge aggregate reproduces the archived result byte for byte.
