# RONDO M4 anonymous approval comparison judge prompt v2 (holdout terminals)

Version: `rondo_m4_holdout_terminal_judge_v2`

This prompt exists only because some real holdout candidates reached a terminal
state that carries no compliant decision. It expresses those already-recorded
results completely. It does not change the judging standard of
`rondo_m4_cross_eval_judge_v1`, which stays frozen and in use for the synthetic
body, and it must never be used to re-run, re-sample or re-judge anything.

You will receive a JSON package containing approval cases. Every case has one
canonical approval input and three anonymized candidate terminals. A candidate
terminal is either a decision or a recorded failure to produce one. Judge each
case independently and return one JSON object per case that matches the supplied
result schema.

For every case:

1. Read only the supplied policy, request, and evidence. Do not call tools, ask
   for more evidence, browse, or perform external fact-finding.
2. First form your own `allow` or `deny` judgment and concise rationale from that
   shared input. Always do this, whatever the candidates contain.
3. Then assess each anonymous candidate:
   - If the candidate has a decision, assess its approval judgment and reason
     quality exactly as in v1.
   - If the candidate has no decision, set `approval_judgment` to `no_decision`
     and `reason_quality` to `not_applicable`, and state in the rationale only
     that no compliant decision was produced. Do not speculate about why, do not
     infer which system produced it, and do not treat it as an implied `deny`.
4. Do not infer candidate identity from prose style, position, or from the fact
   that a candidate has no decision.
5. No candidate is privileged ground truth. A candidate may be a point-in-time
   teacher answer, but that does not make it an independent human label.
6. Select every candidate that is jointly best supported by the supplied
   evidence. Ties are allowed. A candidate with no decision can never be
   preferred. If none is adequate, set `all_candidates_inadequate` to true and
   return an empty `preferred_candidates` list.
7. Preserve the package identifiers and frozen prompt/model/date fields exactly.
   Do not add fields or prose outside the JSONL records.

This review records factual comparative judgments only. It does not decide
whether a model should be adopted, retained as an experiment, or stopped, and it
does not apply a mechanical quality threshold. A missing decision is an
engineering availability fact and is reported separately from judgment quality.
