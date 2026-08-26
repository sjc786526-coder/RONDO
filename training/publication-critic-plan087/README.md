# Publication Critic Plan 087

Plan 087 is a budget-bounded adaptive search over direct original parameters of
the exact Skywork 1.7B reward-model revision. It reuses the Plan 081/082 model,
data, validation, artifact and recovery mechanics while keeping Plan 082's
fixed formal recipe and finalizer unchanged.

The two tracked route candidates are starting hypotheses, not a frozen sweep:

- `route-a-terminal-pair-v1.json` starts with the score head, final norm and
  last backbone block, emphasizes boundary pairs and uses a constant rate;
- `route-b-wider-decay-v1.json` starts two blocks wide, uses warmup/decay and a
  different Binary/Pair balance.

Actual parameter names are resolved from the exact model inventory. A route
can expand only by appending older terminal blocks, so checkpoint scope history
remains deterministic. Each update is followed by the frozen validation cohort
and a qualified checkpoint. Promising status remains an operator judgment over
the complete metric and pair-margin record; the code does not freeze a narrow
numeric product gate. A selected candidate must be the exact checkpoint proven
reusable in a separate process.

The paid entrypoints bind every write to `RONDO_PLAN087_TASK_ROOT`, require an
actual decimal-GB capacity preflight before checkpoint-producing segments,
advance one hash-linked cumulative cost ledger, reconcile ambiguous Pod create/
stop/delete outcomes by exact identity, and copy back only a manifest allowlist
of small SHA-256-verified files.

`runbook.md` is the only operational entry. Stage A ends before any command in
its paid section. The task never reads unseen, uses a third GPU type, publishes
to Hugging Face, or deletes a network volume.
