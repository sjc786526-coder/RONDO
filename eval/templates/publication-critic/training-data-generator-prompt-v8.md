# Plan 064 Publication Critic expansion generator prompt v8

Author one declared Plan 064 scenario pack at a time. Produce public `Scenario`, `PublicationPacket v1`, Binary supervision and optional Boundary or Within-PASS pair rows that satisfy the frozen Plan 054 input contract and `training-data-design-lock-v8.json`.

Use only request context, developer/user instructions, public prior publications and the public candidate. Never invent or expose private reasoning, hidden transcript, raw tool/evidence bodies, credentials, labels, split names, defect names, pair direction, generator identity or reviewer identity inside model-visible packet text.

Every Boundary pair is an atomic PASS-over-REWRITE change in exactly one declared hard dimension while non-candidate context and final continuity omission remain identical. Every Within-PASS pair is PASS-over-PASS, hard-equivalent and differs only by one truthful soft preference. A mixed singleton may combine naturally interacting properties, but its label must remain defensible without relying on a template cue.

Deliberately diversify surface form. In particular:

- useful-state failures need not be vague; they may be detailed yet omit the decision-relevant state, blocker or result;
- honest PASS examples may state verified facts confidently, while REWRITE examples may overreach implicitly without using stock certainty words;
- continuity PASS examples must not rely on the phrase “事项未完成”, while REWRITE examples may contain a plausible handoff that still loses the real blocker or next starting point;
- scope PASS examples may be long and detailed, while REWRITE examples may be short but include locally irrelevant state;
- consistency defects should include implicit cross-field conflicts, not only explicit self-contradiction;
- use natural Chinese, English, mixed-language, numbers, emoji and non-Latin characters where product-shaped; do not signal labels with decorative Unicode.

`length_bucket` is scenario-scoped. Short and long cases must occur in every hard dimension without letting candidate length predict Binary label. Long cases contain distinct useful prior publications, not repeated filler, and must meet the exact-token contract after rendering. Conditional continuity changes only the whole optional handoff/continuity segment under the Plan 054 omission rule; absence of a handoff alone is never a defect.

Use globally unique `pc064-*` candidate IDs, `p064-*` scenario/source/group IDs and `pc064-pair-*` pair IDs within the declared batch. Keep one truthful group for any shared source or template. Assign the declared proposed split at scenario-group level; generation does not move v7 rows or override fixed-split reconciliation.

Return strict JSONL rows only. Generation is not review: use the pending review state and leave the independent reviewer identity unset. Stop the pack when its declared coverage cells are filled; do not add examples merely for count.
