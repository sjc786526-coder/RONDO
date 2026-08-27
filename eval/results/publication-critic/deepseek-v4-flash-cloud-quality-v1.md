# DeepSeek V4 Flash Publication Critic validation quality

Plan 096 completed one authoritative 55-row validation run with the frozen
`deepseek-v4-flash` cloud scorer. The result is complete but does not qualify:

`CLOUD_SCORER_NOT_QUALIFIED_HEADROOM_HIGH`

There is no operating point satisfying all existing publication-quality floors. The selected
fallback threshold is `0.9`: False PASS is `8/21 = 0.380952` (floor `<= 0.25`), False REWRITE is
`0/34`, and balanced accuracy is `0.809524`. Threshold-free discrimination is high: ROC AUC is
`0.840336` and Boundary strict win is `15/19 = 0.789474`, both above their frozen floors. Thus the
stack has strong task separation but is not an admissible release scorer under the existing error
trade-off. Plan 097 is not unlocked by this terminal.

| scorer | False PASS | False REWRITE | balanced accuracy | ROC AUC | Boundary | Within-PASS | feasible |
|---|---:|---:|---:|---:|---:|---:|---|
| DeepSeek V4 Flash cloud | 8/21 | 0/34 | 0.809524 | 0.840336 | 15/19 | 3/7 | no |
| exact Skywork 1.7B base | 6/21 | 13/34 | 0.665966 | 0.616947 | 15/19 | 6/7 | no |
| exact Skywork 4B base | 12/21 | 4/34 | 0.655462 | 0.621849 | 13/19 | 6/7 | no |

The comparison is limited to the same frozen validation cohort, labels, pairs, curve, and gates.
Raw logits, absolute thresholds/calibration, tokenizer/window, cloud versus local templates,
latency, and resources are not treated as equivalent.

Formal integrity:

- source commit: `7bdcad9196d4e7a2de39f6618e0d193476b0d6e6`
- freeze SHA-256: `4497883159a2d278ca6611b6b6ce4101efec09d56f319e357c9214fbfd31836b`
- validation release SHA-256: `757dd624c3d47f87dd5683d24f9f1753b1dbbffb42fdeff567c9e3e5e0b71a91`
- formal namespace: `plan096-formal-20260827T201304Z-validation-55`
- completeness: 55/55 scalar rows, zero duplicate/missing/typed failure
- provider attempts: 56; one transient attempt lacked usage and was conservatively charged `1 RMB`
- formal conservative cost: `1.3855704 RMB`
- total Plan 096 real-API cost, including both commissioning configurations: `2.1391799 RMB`
- remaining authorized budget: `27.8608201 RMB`

The companion JSON contains the full freeze, 55 score/label rows, complete operating curve,
aggregates, eight disagreement IDs, usage, and exact historical projections. Body-free raw call
records, freeze, authority, and independent recomputation inputs remain in the task-owned ignored
`eval-data/publication-critic/plan096/` namespace.
