# Publication Critic qualification rubric v2

This rubric is a model-input projection of `rondo-publication-critic-task@v2`; the authoritative semantics live in `doc/rondo-multi-publication-critic-task-contract-v2.md`.

Judge only the submitted candidate and bounded public packet. Return five absolute hard decisions:

- `useful_state_transfer`: `PASS` when the local scope contains a concrete result, state, decision, artifact, blocker, or starting point that another worker can rely on; `FAIL` for vague activity or progress with no reusable state.
- `honest_uncertainty`: `PASS` when visible observations, inference, suspicion, unknowns, stale context, and missing context keep their stated certainty; `FAIL` when a visible limit, guess, or unverified mechanism is presented as established fact.
- `conditional_continuity`: `N/A` only when the model-visible candidate clearly and consistently says the work is complete. Otherwise it is applicable: `PASS` when unfinished work gives usable progress, blockage, or the next starting point, and `FAIL` when it cannot be continued. Conflicting completion claims are never `N/A`.
- `scope_and_signal`: `PASS` when the core public state is easy to identify inside the local scope; `FAIL` when process dumps, repetition, or off-scope material overwhelms that state.
- `internal_consistency`: `PASS` when title, summary, handoff, and supplied continuity agree on key completion, verification, and next-action state; `FAIL` when those visible claims conflict.

The first, second, fourth, and fifth decisions are always `PASS` or `FAIL`. Completed work may omit a handoff. A candidate qualifies only when every applicable decision is `PASS`; one applicable `FAIL` requires `REWRITE`. Style, brevity, formality, preferred wording, or any other soft quality cannot compensate for a hard failure and cannot create a PASS-internal qualification ranking.

Use only public packet facts. Do not infer completion or quality from hidden `completion_state`, scenario state, candidate briefs, labels, defects, split, source, generator, reviewer, rationale, or pair direction. Do not verify external truth or claim-to-Fact entailment. A completion claim contradicted by visible packet content remains subject to `internal_consistency` and, when it overstates visible support, `honest_uncertainty`; hidden private truth never changes applicability. Treat stale, partial, unavailable, and omitted context as visible limits, not proof for or against the candidate.
