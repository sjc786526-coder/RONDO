# Publication Critic qualification rubric v2

This rubric is a model-input projection of `rondo-publication-critic-task@v2`; the authoritative semantics live in `doc/rondo-multi-publication-critic-task-contract-v2.md`.

Judge only the submitted candidate and bounded public packet. Classify five hard decisions: `useful_state_transfer`, `honest_uncertainty`, `conditional_continuity`, `scope_and_signal`, and `internal_consistency`.

The first, second, fourth, and fifth decisions are always `PASS` or `FAIL`. `conditional_continuity` is `N/A` only when the model-visible candidate clearly and consistently says the work is complete. It remains applicable when work is unfinished or completion is not clearly closed. Conflicting completion claims are never `N/A`.

A candidate qualifies only when every applicable decision is `PASS`. One applicable `FAIL` requires `REWRITE`; no other strength, style, brevity, formality, or soft preference can compensate. Completed work may omit a handoff. Unfinished work must preserve enough progress, blockage, or next starting point to continue.

Use only public packet facts. Do not infer completion or quality from hidden `completion_state`, scenario state, candidate briefs, defects, split, source, generator, reviewer, or pair direction. Do not verify factual truth or claim-to-Fact entailment. Treat stale, partial, unavailable, and omitted context as visible limits, not proof for or against the candidate.
