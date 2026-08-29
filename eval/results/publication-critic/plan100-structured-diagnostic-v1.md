# Plan 100 DeepSeek V4 Flash structured diagnostic

Plan 100 completed one authoritative 81-observation development-validation formal comparing the
same `deepseek-v4-flash`, public packet bytes, rubric and request conditions across scalar (A),
direct gate (B) and five-dimension hard decisions (C). The frozen terminal is:

`TASK_EXECUTABILITY_INSUFFICIENT`

All three arms produced 27/27 strict outputs with zero parse failure, but none reached its
pre-frozen basic/gate requirements. Under the frozen route mapping this is a complete valid negative
quality result, not a technical `INCONCLUSIVE`: it does not support further paid unfreezing or
training, and it does not unlock qualification or product enablement.

| arm | balanced accuracy | False PASS | False REWRITE | pair result | gate |
|---|---:|---:|---:|---:|---|
| A / scalar selected point | 0.625000 | 10/15 | 1/12 | Boundary strict 2/9 | fail |
| B / direct gate | 0.583333 | 5/15 | 6/12 | closed 4/12 | fail |
| C / five dimensions | 0.700000 | 9/15 | 0/12 | closed 5/12; target 3/9 | fail |

A has ROC AUC `0.652778` and no acceptable operating point. C has the highest candidate balanced
accuracy and perfect PASS recall, but only `0.4` REWRITE recall. Its dimension failure recalls are
`0.0` conditional continuity, `0.166667` scope and signal, `0.333333` useful state transfer, `0.4`
honest uncertainty and `0.5` internal consistency; this is broad insufficiency rather than a
frozen concentrated-blocker route.

Formal integrity:

- source commit: `e71e9ee3406127bb14488137d9ef513d229d7f4b`
- successful B1 run: `plan100-commissioning-20260829T191337Z-b1-v2`; 9/9 strict success and 9/9 exact usage recount calibration
- formal run: `plan100-formal-20260829T191451Z-b2-v1`
- formal freeze SHA-256: `934c8dbf4103169532147d132196a10b65cf541da793d30ec7344303ca15c943`
- authority canonical result SHA-256: `74d4b720b0df62ed11568489cb815184146f0467368298d3cfd9569c234ec2dd`
- detailed projection SHA-256: `e77c4b8ea66d52816bce43ecb40d1a9cc95b1e80783af465fe358b5921f587f6`
- completeness: 81/81 terminal observations; A/B/C parse failures `0/0/0`
- formal API attempts/cost: 81 / `0.0307772 RMB`; no retry and all attempts settled from provider usage
- task-wide API attempts/cost: 99 / `0.0396094 RMB`, including both commissioning runs; outstanding reservation `0`

The companion JSON is the body-free tracked aggregate. Authority-bound independent recomputation
also yields a bounded detailed projection with A's full four-point curve and selected 11 candidate
errors, B's 11 candidate errors, C's 9 candidate errors, all 12 pair rows per arm and all five C
dimension tables. Raw write-once receipts, exact provider response text, budget ledger, freeze,
binding, result and authority remain only in the task-owned ignored
`eval-data/publication-critic/plan100/` namespace; neither tracked result contains packet or response
body, credential or private endpoint data.
