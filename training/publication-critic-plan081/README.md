# Plan 081 local training readiness contracts

This directory binds the next Publication Critic research route to the exact
`Skywork/Skywork-Reward-V2-Qwen3-1.7B@e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`
base, the frozen v8 train/validation projection, direct non-PEFT parameter
updates, and the continuous observation/checkpoint lifecycle implemented by
Plan 081.

`route-contract-v1.json` intentionally does not choose concrete trainable
layers, learning rate, batch size, update count, optimizer, scheduler, or scope
expansion rule. Those are runtime records and inputs to a later authorized
commissioning task. `cloud-handoff-v1.json` limits that later task to one A40
48GB (preferred) or L40S 48GB, at most 12 hours and 15 USD total external cost.

The local Plan 081 tests use only fixture/fake adapters. They prove controller,
same-cohort validation, retention, archive, and recovery behavior; they do not
load or train a model, prove GPU feasibility or quality, create a research
candidate, authorize cloud work, unlock M3-D, or establish product GO. Current
stage and subsequent work are defined only by `doc/WBS.md` and
`doc/WBS/multi-agent-trusted-evidence.md`.

An adapter must bind validation results to the typed validation dataset and
declare one explicit writer/reader codec for complete optimizer, scheduler,
RNG, and data-cursor state. A failed post-update step is not retried in place:
the controller enters `recovery_required`. When a verified complete checkpoint
exists, continuation uses a fresh adapter restored from it. A failure before
the first checkpoint can return through `restart_from_exact_base()` while the
failed controller remains available, or through the class/store-level
`restart_store_from_exact_base()` after a process restart. Both paths require a
fresh adapter to assert the complete exact-base state, reproduce the write-once
base observation exactly, and continue in a newly reserved attempt. Any live,
byte-tree-verified checkpoint requires an explicit resume attempt first; stale
completion markers for already pruned checkpoints do not block base restart.

A newly written checkpoint is eligible to replace an older recovery point only
after a disposable adapter supplied by `checkpoint_recovery_probe()` proves a
fresh exact-base starting state, decodes the artifact with its own bound reader,
loads the model payload and proves the adapter's model-load postcondition before
any scope/state restore, restores all optimizer/scheduler/RNG/data state, and
captures four state sections exactly equal to the decoded checkpoint.
The live training adapter is not used as its own recovery proof. Byte-tree
integrity, decodability, or a successful restore return alone is not recovery
qualification.
If qualification fails, the newly published but never-qualified checkpoint is
atomically hidden and removed. An earlier qualified recovery point remains
untouched, and a failed first checkpoint therefore cannot block an exact-base
restart in a new process.

Checkpoint retention is complete only after its write-once completion artifact
has been atomically published. Resume may repair an absent marker only for the
newest physical checkpoint, and only after that checkpoint passes the same
adapter-level recovery qualification; a marked older best or turning-point
checkpoint never reapplies its historical prune.
Each verified discard is first atomically renamed to a strict task-owned prune
tombstone, so an interrupted tree deletion can be resumed without treating a
partial tree as a live artifact. Superseded checkpoints are hidden from newest
to oldest before their companion snapshots, preventing any interrupted prune
from exposing a stale checkpoint whose controller state depends on an already
deleted recovery point or snapshot.
