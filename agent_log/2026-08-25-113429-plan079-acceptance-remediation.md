# Plan 079 acceptance remediation

Initial independent acceptance at `c705777` correctly found that every prior formal namespace with
`final-evidence.json` blocked a new formal run, including a legitimate incomplete `INCONCLUSIVE`.
That contradicted the frozen allowance to repair an infrastructure/runtime failure and retry from a
new empty namespace. The accepted NO-GO and cloud evidence were unaffected and were not rerun.

The focused fix keeps filesystem discovery in `BaseQualityArchive` and delegates semantic
classification to the existing runner contracts. A prior namespace is retryable only after its own
run spec, validation release, scores, runtime and result all validate together and the result is
exactly `INCONCLUSIVE` with `valid_full_quality_run=false`. Complete GO/NO-GO evidence, malformed
documents, missing identities and ambiguous evidence remain fail-closed.

Regression coverage constructs a valid 54-score/one-typed-failure formal INCONCLUSIVE and confirms
that a new namespace is allowed, then confirms malformed INCONCLUSIVE-shaped evidence is still
rejected. Plan 079 base-quality plus Pod monitor tests passed `23/23`; the reused Plan 073 threshold,
selection, archive and freeze tests passed `23/23`. Formatting, targeted compilation, Plan 079 shell
syntax, JSON and diff checks passed. No cloud model, Judge, training, quantization, Docker, Cargo or
full-repository suite ran. Pod deletion and retained volume state were unchanged.
