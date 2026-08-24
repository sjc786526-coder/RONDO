# Plan 059 Publication Critic generator prompt v1

Role: directly author product-shaped Publication Critic Scenario blueprints and candidates for Plan 059. The generator is the active GPT-5.6-sol implementation session; no external API or model is called.

Use only `rondo-publication-packet@v1`, `rondo-publication-qualification@v1`, the five hard requirements in `qualification-rubric-v1.md`, and the public source allowlist in `training-data-design-lock-v1.json`. Never include supervision, source, generator, reviewer, split, defect, or pair metadata inside a packet.

For each boundary Scenario, author two independently judgeable candidates over exactly the same non-candidate packet context. Q+ is `PASS`, Q- is `REWRITE`, and only the declared hard dimension may change semantically. Preserve final continuity omission equality. For selected Scenarios, author one additional `PASS` candidate with the same core state but a modest soft-preference disadvantage; the preferred and dispreferred endpoints must both satisfy all hard requirements. Author a small number of natural mixed Binary Scenarios that are not forced into a pair.

Vary publication class, authoritative role, length, formal/conversational style, Unicode, continuity availability/freshness/coverage, and body-free Evidence V1 appearance without turning those features into labels. Completed work may omit handoff. Incomplete work must remain actionable. Evidence presence never proves a claim, and missing/stale/omitted context is not itself a defect.

Output only the versioned structured Scenario, Candidate, Binary, and Pair records requested by the Plan 059 authoring facility. Do not copy Plan 054 cohort candidates or the product-contract examples. Do not use private transcripts, reasoning, raw trace/tool/evidence bodies, Fact IDs, secrets, or Plan 058 material.
