# Plan 101 DeepSeek V4 Flash thinking × output-expression comparison

This is a measurement report, not a qualification or route decision. No pass/fail terminal is attached.

- complete: `True`
- observations: `810/810`
- thinking_off repeats: `5`
- thinking_on repeats: `5`
- freeze SHA-256: `33545a0c1a9c4a4dd2892925a94fe880fc71151129cd3785fb837d8c20c5aa5e`

## Six units, single call (primary)

The product issues one call per candidate, so each repeat is scored on its own and the
repeats are then summarised. This is the deployable number.

| unit | BA mean | BA min | BA max | BA sd | repeats |
|---|---:|---:|---:|---:|---:|
| thinking_off:A | 0.626667 | 0.600000 | 0.633333 | 0.013333 | 5 |
| thinking_off:B | 0.625000 | 0.591667 | 0.633333 | 0.016667 | 5 |
| thinking_off:C | 0.746667 | 0.733333 | 0.766667 | 0.016330 | 5 |
| thinking_on:A | 0.653333 | 0.550000 | 0.733333 | 0.070040 | 5 |
| thinking_on:B | 0.666667 | 0.658333 | 0.691667 | 0.012910 | 5 |
| thinking_on:C | 0.656667 | 0.583333 | 0.725000 | 0.044845 | 5 |

## Six units, majority vote over repeats (secondary)

A k-times-more-expensive ensemble, not what a single product call delivers. The band is
the endpoint average of the two per-class Wilson recall intervals, which errs wide.

| unit | balanced accuracy | band | False PASS | False REWRITE | pairs closed | consistency |
|---|---:|---|---:|---:|---:|---:|
| thinking_off:A | 0.633333 | [0.4332, 0.7598] | 11 | 0 | 4 | 0.6296 |
| thinking_off:B | 0.633333 | [0.4200, 0.7988] | 1 | 8 | 4 | 0.9630 |
| thinking_off:C | 0.733333 | [0.5028, 0.8494] | 8 | 0 | 7 | 0.7778 |
| thinking_on:A | 0.600000 | [0.4140, 0.7259] | 12 | 0 | 4 | 0.5556 |
| thinking_on:B | 0.616667 | [0.3751, 0.7978] | 9 | 2 | 5 | 0.8148 |
| thinking_on:C | 0.625000 | [0.3989, 0.7840] | 10 | 1 | 4 | 0.4815 |

## Arm A operating point

Arms B and C emit a verdict with no free parameter. A threshold fitted to these same 27
gold rows would give A an advantage they never get, so the cross-arm table uses the
pre-committed threshold and the fitted one is reported only as an upper bound.

AUC is the threshold-free reading of how well A ranks candidates, so it is the fairest
single number for the thinking comparison on this arm: it does not depend on where the
operating point happens to sit.

| unit | AUC | BA @ fixed 0.5 | BA @ oracle | oracle threshold |
|---|---:|---:|---:|---:|
| thinking_off:A | 0.838889 | 0.633333 | 0.816667 | 0.5800000000000001 |
| thinking_on:A | 0.727778 | 0.600000 | 0.725000 | 0.8 |


## Known limitations

- **Per-arm prompt asymmetry.** Each arm carries the instruction its output channel needs,
  but arm A also carries a calibration sentence ("choose a boundary only when every
  applicable hard requirement clearly fails or clearly holds") that B and C have no
  equivalent of. It was added during commissioning to satisfy a self-check that has since
  been retired. A's spread of values is therefore partly induced by that instruction, and it
  pushes against the confident boundary output a well-calibrated judge would give. This
  affects the output-expression axis; the thinking axis is unaffected because both sides of
  it share one prompt.
- **Cohort size.** n=27 with 12 PASS and 15 REWRITE. Differences of a few points are inside
  the noise; only the direction and the larger gaps are worth reading.
- **One provider, one model revision.** `deepseek-v4-flash` serving is provider-managed and
  not independently verifiable across the run.


## thinking_on − thinking_off

Δ single call is the deployable comparison. Δ majority is the k-call ensemble and can
disagree in sign when an arm is unstable across repeats.

| arm | Δ single call | Δ majority | Δ False PASS | Δ False REWRITE | Δ pairs |
|---|---:|---:|---:|---:|---:|
| A | 0.026667 | -0.033333 | 1 | 0 | 0 |
| B | 0.041667 | -0.016667 | 8 | -6 | 1 |
| C | -0.090000 | -0.108333 | 2 | 1 | -3 |

## Output-expression differences

### thinking_off

| contrast | Δ single call | Δ majority | Δ False PASS | Δ False REWRITE |
|---|---:|---:|---:|---:|
| C_minus_B | 0.121667 | 0.100000 | 7 | -8 |
| C_minus_A | 0.120000 | 0.100000 | -3 | 0 |
| B_minus_A | -0.001667 | 0.000000 | -10 | 8 |

### thinking_on

| contrast | Δ single call | Δ majority | Δ False PASS | Δ False REWRITE |
|---|---:|---:|---:|---:|
| C_minus_B | -0.010000 | 0.008333 | 1 | -1 |
| C_minus_A | 0.003333 | 0.025000 | -2 | 1 |
| B_minus_A | 0.013333 | 0.016667 | -3 | 2 |

## Preregistered observations

Commissioning ran three packets. On those three, `thinking_off:B` returned the same
verdict every time, including a PASS on the most blatant REWRITE in the triple (a
candidate whose handoff is `null` and whose summary is one line saying the work is
done). That looked like a dead 1-bit channel, and it was registered as a prediction
before the formal matrix opened so it could be tested rather than assumed.

It did not survive contact with 27 candidates. The lesson is about method, not about
this arm: a three-packet preview cannot distinguish "no discrimination" from "a mild
class bias", and a self-check that treats constancy on n=3 as a plumbing failure will
block the very measurement that settles the question. The check was corrected to test
packet reachability across arms instead.

- id: `thinking_off_B_constant_pass_on_commissioning_triplet`
- validation-27 constant: `False`
- distinct majority verdicts: `['PASS', 'REWRITE']`
- qminus majority: `REWRITE`
- matches commissioning prediction: `False`

## thinking_on versus thinking_off

Direction is taken from the single-call mean, which is what one product call
delivers. n=27 signal, not a causal conclusion.

| arm | single-call off | single-call on | Δ on−off | direction | Δ majority |
|---|---:|---:|---:|---|---:|
| A | 0.626667 | 0.653333 | 0.026667 | on_higher | -0.033333 |
| B | 0.625000 | 0.666667 | 0.041667 | on_higher | -0.016667 |
| C | 0.746667 | 0.656667 | -0.090000 | on_lower | -0.108333 |

## Supplement rounds (budget-only decision)

- looked at unit metrics: `False`
- decision: `proceed`
- extend repeats to: `5`
- two-round cost: `1.952747509311740890688259109 RMB`
- remaining unreserved at decision: `15.5335927 RMB`

## Disclosed live rounds

| run_id | status | calls | reason |
|---|---|---:|---|
| plan101-commissioning-20260831T125902Z-b1 | discarded | 12 | reservation_envelope_did_not_cover_missing_usage_retry_settlement |
| plan101-commissioning-20260831T130653Z-b1r2 | discarded | 19 | b1_outputs_non_degenerate_failed_constant_A_off_and_B_outputs |
| plan101-commissioning-20260831T134136Z-b1r3 | discarded | 18 | b1_outputs_non_degenerate_failed_constant_B_verdicts |
| plan101-commissioning-20260831T134732Z-b1r4 | accepted_as_b1_pass_under_corrected_gate | 18 | reviewer_corrected_s5_1_item3_graded_non_degeneration; r4_prompt_frozen |
| plan101-commissioning-20260831T135213Z-b1r5 | discarded | 18 | b1_outputs_non_degenerate_failed_B_and_thinking_on_A_constant; prompt_reverted_to_r4 |

## Cost

- attempts: `812`
- prompt tokens: `786435`
- completion tokens: `644516`
- settled (this result): `3.2400577 RMB`
- task-wide settled: `6.6787625 RMB`
- remaining unreserved: `13.3212375 RMB`

Raw receipts, response text and the budget ledger remain in the ignored
`eval-data/publication-critic/plan101/` namespace.
