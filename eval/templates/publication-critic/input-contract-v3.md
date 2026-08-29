# Publication Critic successor input contract v3

This file is a serialization projection of the authoritative `rondo-publication-critic-task@v2` contract. It does not redefine task semantics.

The successor renderer accepts only a strictly validated `rondo-publication-packet@v1` whose rubric identity is `rondo-publication-qualification@v2`, plus the fixed bytes of `qualification-rubric-v2.md`. `rondo-publication-critic-render@v4` reuses the bounded two-message, no-system, control-token-safe mechanics of v3 while binding the new authority and rubric: public qualification/role/target/title, bounded continuity and Evidence V1 appear in the user message; the complete canonical summary and optional handoff appear in the assistant message.

Continuity applicability is inferred only from model-visible candidate text under the authority contract. The renderer has no argument for labels, completion state, public state, candidate brief, defect, pair, split, source, generator, reviewer, or rationale. Those fields never enter model input.

The data-side continuity basis is not a renderer input. It records a bounded exact quote from `candidate.summary` or `candidate.handoff` so validation and blind review can trace applicability to text the model actually receives; its type and quote are never rendered.

Candidate text is never truncated. Overflow may remove whole oldest public continuity items and must record the render-only omission count. Mandatory-content overflow is a typed input failure.
