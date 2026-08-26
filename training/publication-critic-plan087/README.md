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

Actual parameter names are resolved from the exact model inventory. Each new
exact-base route may select score/final modules, any available terminal depth,
explicit module prefixes or all original parameters. Scope phases inside that
route must still strictly expand the actual resolved parameter set, preserving
optimizer and checkpoint history. Each update is followed by the frozen
validation cohort and a checkpoint. A complete observation/checkpoint may close
a weak route early without a candidate-level recovery; a selected candidate
must be that exact checkpoint proven reusable in a separate process.

The paid entrypoints bind every write to `RONDO_PLAN087_TASK_ROOT`, require an
actual decimal-GB capacity preflight before checkpoint-producing segments,
advance one hash-linked cumulative cost ledger, reconcile stop/delete outcomes
by exact identity, and copy back only a manifest allowlist of small
SHA-256-verified files. When stock is tight, the repository-wide
`scripts/create-runpod-when-ready.py` owns only polling, creation and exact-name
duplicate reconciliation. Its status output is not a qualification receipt.
After creation, the executor independently checks the actual price, GPU, data
center and network-volume mount through existing RunPod MCP/CLI observations;
a mismatch is immediately released through the retained terminal helper.

`runbook.md` is the only operational entry. Stage A ends before any command in
its paid section. The task never reads unseen, uses a third GPU type, publishes
to Hugging Face, or deletes a network volume.
