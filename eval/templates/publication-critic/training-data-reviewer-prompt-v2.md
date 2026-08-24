# Plan 064 Publication Critic independent reviewer prompt v2

Review only the declared Plan 064 batch and the frozen Plan 054 qualification contract. Do not infer the intended label from ID, filename, proposed split, hard-focus metadata or generator notes. Judge the model-visible packet first, then compare the proposed supervision.

For each candidate, independently decide PASS or REWRITE, list any failed hard dimensions and accept, revise or exclude with a concise public rationale. For each pair, separately verify direction, non-candidate context equality, whole-continuity omission equality and atomic hard change or soft-only equivalence. Reject a pair if any other hard qualification changes.

Treat holdout, Boundary, Within-PASS, mixed, near-duplicate, long, Unicode and conditional-continuity rows as high risk. Check for stock surface cues, label-bearing language, implausible product state, repeated templates, internal conflicts, evidence fabrication, and hidden/private-source leakage. A confident verified conclusion is not uncertainty failure; a missing optional handoff is not continuity failure; detail alone is neither usefulness nor scope quality.

Return strict review JSONL using the declared schema. Review never edits source rows. A systemic finding must name the complete affected batch, slice or pattern so the execution pipeline can repair, replace or exclude the entire affected set before re-review.
