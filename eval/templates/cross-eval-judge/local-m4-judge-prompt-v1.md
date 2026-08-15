# RONDO M4 anonymous approval comparison judge prompt v1

You will receive a JSON package containing approval cases. Every case has one
canonical approval input and three anonymized candidate decisions. Judge each
case independently and return one JSON object per case that matches the supplied
result schema.

For every case:

1. Read only the supplied policy, request, and evidence. Do not call tools, ask
   for more evidence, browse, or perform external fact-finding.
2. First form your own `allow` or `deny` judgment and concise rationale from that
   shared input.
3. Then assess each anonymous candidate's approval judgment and reason quality.
   Do not infer candidate identity from prose style or position.
4. No candidate is privileged ground truth. A candidate may be a point-in-time
   teacher answer, but that does not make it an independent human label.
5. Select every candidate that is jointly best supported by the supplied evidence.
   Ties are allowed. If none is adequate, set `all_candidates_inadequate` to true
   and return an empty `preferred_candidates` list.
6. Preserve the package identifiers and frozen prompt/model/date fields exactly.
   Do not add fields or prose outside the JSONL records.

This review records factual comparative judgments only. It does not decide
whether a model should be adopted, retained as an experiment, or stopped, and
it does not apply a mechanical quality threshold.
