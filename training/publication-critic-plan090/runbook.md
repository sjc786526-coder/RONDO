# Plan 090 operator runbook

Sections 2-7 are paid Stage B.  They must not run until the reviewer replies
exactly: `阶段 A 验收通过，批准进入付费阶段`.

## 1. Stage A freeze and bundles

Validate the tracked freeze, then from the clean committed Plan 090 worktree
build the narrow source archive.  Reuse the already verified physical
train+validation-only Plan 087 data archive only after `verify-data` and archive
extraction both report content SHA-256
`2247dd09c168900a47d37a50ecd6511d66d62d3f2ec8056ea3bc829c93de8b46`
and unseen rows `0`.  Inspect the tar member lists.  No Stage A command creates,
queries or changes a cloud resource, downloads a model, uploads data or trains.

```bash
PYTHONPATH=eval python3 -B -m \
  rondo_eval.publication_critic.full_model_training.plan090_cli \
  validate-freeze \
  --freeze training/publication-critic-plan090/confirmation-freeze-v1.json
PYTHONPATH=eval python3 -B -m \
  rondo_eval.publication_critic.full_model_training.plan090_cli \
  create-source-archive --repo "$PLAN090_REPO" --commit "$PLAN090_COMMIT" \
  --output "$PLAN090_SOURCE_TAR" \
  --receipt-output "$PLAN090_SOURCE_RECEIPT"
```

The source archive must come from the Stage A clean commit; a later code change
invalidates and replaces it.  The old Plan 087 source archive is history only.

## 2. Live gate and Pod acquisition

After approval, capture live balance, known unsettled billing, Pod list, L40S
inventory/price, network-volume state and actual volume free bytes.  Require
account-level zero Pods.  For each proposed action validate a snapshot shaped
as follows; `projected_complete_branch_usd` covers the whole branch plus small
handoff and termination, not merely its next command.

```json
{
  "schema": "rondo-publication-critic-plan090-budget-snapshot-v1",
  "captured_at": "<RFC3339>",
  "live_balance_usd": 0.0,
  "known_unsettled_usd": 0.0,
  "stage_b_baseline_balance_usd": 0.0,
  "stage_b_baseline_known_unsettled_usd": 0.0,
  "conservative_task_cost_usd": 0.0,
  "closure_reserve_usd": 0.0,
  "projected_complete_branch_usd": 0.0
}
```

```bash
PYTHONPATH=eval python3 -B -m \
  rondo_eval.publication_critic.full_model_training.plan090_cli \
  validate-budget --snapshot "$PLAN090_BUDGET_RAW" > "$PLAN090_BUDGET"
```

The conservative task cost never decreases and must remain at or below 6 USD.
Every snapshot retains the same Stage B baseline balance/unsettled pair; the
validator floors task cost by the decline in effective account balance, and
formal results retain their launch snapshot so later starts and terminal
finalization reject baseline drift or a decreasing cumulative cost.
Do not begin the first BF16 unless the safe headroom can close both BF16 runs,
small result transfer and Pod termination.  Do not begin FP32 unless its whole
closure fits the refreshed gate.  Keep one task Pod maximum and never create,
resize or delete a volume.

If US-TX-3 L40S stock is tight, use only the repository helper:

```bash
python3 scripts/create-runpod-when-ready.py \
  --pod-name "$PLAN090_POD_NAME" --image "$PLAN090_IMAGE" \
  --gpu-id "$PLAN090_GPU_ID" --gpu-count 1 --cloud-type SECURE \
  --data-center-id US-TX-3 --network-volume-id mwemzrn33y \
  --container-disk-gb "$PLAN090_CONTAINER_GB" \
  --volume-mount-path /workspace --port 22/tcp
```

The helper only polls, creates and exact-name reconciles an uncertain response.
Immediately query the exact Pod independently through the existing RunPod
MCP/CLI and confirm the actual hourly price, exactly one NVIDIA L40S, Secure
Cloud, US-TX-3, exact image/container disk, and a network mount with volume ID
`mwemzrn33y` at `/workspace`.  If any field is wrong or cannot be confirmed,
run the retained `training/publication-critic-plan087/runpod-terminal.py` with
`--task-pod-name-prefix rondo-plan090-`, then confirm account-level zero Pods.
Do not connect or upload before these checks pass.
Export the independently observed exact values as
`RONDO_PLAN090_PROVIDER_POD_ID` and `RONDO_PLAN090_PROVIDER_POD_NAME`; the
runtime/result boundary binds both values and the container hostname across
the formal sequence.

## 3. Upload and bootstrap

Create one fresh `/workspace/rondo-plan090-<run>/incoming` and upload only the
verified source and data tar files.  Set the `RONDO_PLAN090_*` variables and run
`runpod-bootstrap.sh`.  It extracts and exact-tree verifies source and physical
train+validation data, preserves image Torch, installs the pinned small
dependencies, and uses `hf download` only for the exact public revision if the
existing exact snapshot cannot be reused.  Token variables are removed and no
Hub upload exists.  Plan 082/087 roots remain read-only.

Set `RONDO_PLAN090_EXISTING_MODEL_ROOT` to the verified Plan 082/087 exact
snapshot to reuse it read-only.  Leave it unset only when that snapshot is
absent or fails exact verification; the bootstrap then downloads and verifies
the frozen revision inside the Plan 090 task root.

Before any checkpoint-producing segment, record provider volume size plus
`df`, `du -s -B1 --one-file-system /workspace`, Plan 090 task-root use and the
expected checkpoint staging demand.  If existing 57GB space cannot safely hold
the next complete branch after deleting only superseded Plan 090 intermediates,
stop and ask the reviewer; volume expansion is not authorized.

## 4. Commissioning and pre-result diagnostics

In a disposable `debug/` namespace, create the BF16 primary inventory and
materialized run spec.  The inventory must bind the exact nine names and
33,558,784 elements.  Run the same no-update `diagnose` command once against
exact base and once against the verified Plan 087 Route O checkpoint.  The
legacy path is diagnostic only and is never training initialization.

```bash
python -B -P -m rondo_eval.publication_critic.full_model_training.plan090_cli \
  parameter-inventory --snapshot "$PLAN090_MODEL_ROOT" \
  --model-lock "$PLAN090_MODEL_LOCK" --freeze "$PLAN090_FREEZE" \
  --run-id bf16-seed-20260901 > "$PLAN090_BF16_INVENTORY"
env RONDO_PLAN090_TASK_ROOT="$PLAN090_TASK_ROOT" \
  python -B -P -m rondo_eval.publication_critic.full_model_training.plan090_cli \
  materialize-run-spec --freeze "$PLAN090_FREEZE" \
  --run-id bf16-seed-20260901 --inventory "$PLAN090_BF16_INVENTORY" \
  --output "$PLAN090_BF16_PRIMARY_SPEC"
```

Use a throwaway exact-base run to prove model load, train/validation no-grad
diagnostics, one update, checkpoint qualification, different-process no-update
restore, result finalization, handoff and terminal command.  Debug evidence is
never a formal result.  Once this chain works, bind the clean source, exact Pod,
environment and empty formal namespaces; do not splice debug progress into
formal evidence.

Record the independently verified provider Pod ID/name beside its observed
container hostname.  All formal run results and the different-process recovery
must retain that same hostname; the terminal finalizer rejects mixed-host
results.  The provider ID/name remains an operator resource-log fact rather
than a new creation receipt.

## 5. Fixed formal sequence

Formal order is fixed:

1. `bf16-seed-20260901` from exact base;
2. if it passes the frozen whole rubric, `bf16-seed-20260902` from exact base;
3. if both pass and the refreshed full-closure budget authorizes it,
   `fp32-seed-20260901` from exact base.

The two BF16 entries are independent clean executions with distinct seed
metadata.  The frozen path has no shuffle, active dropout, or other bound
seed-sensitive consumer, so they test execution/numerical repeatability rather
than random-seed stability.  Runtime and results must retain
`seed_sensitive_stability_tested=false`; do not add randomization to manufacture
a seed effect.

For every run, regenerate the inventory in its declared model dtype and
materialize its independent run spec.  Use the same exact Pod and an empty
`formal/<run-id>/artifacts` root.  `start` performs exactly one full-cohort
update.  It writes a process receipt before the update so an already qualified
checkpoint can be recovered after a later failure.  It records train and
validation before/after, the parameter/gradient/optimizer/forward dtype receipt,
and a qualified full checkpoint.

A failure before the first qualified checkpoint restarts from exact base in a
new empty task-owned attempt namespace; it never reuses an orphaned partial
namespace.  A failure after checkpoint qualification resumes only that exact
checkpoint through `verify-recovery`.

```bash
env RONDO_PLAN090_TASK_ROOT="$PLAN090_TASK_ROOT" \
  python -B -P -m rondo_eval.publication_critic.full_model_training.plan090_cli \
  start --source-archive "$PLAN090_SOURCE_ARCHIVE" \
  --source-root "$PLAN090_SOURCE_ROOT" --source-receipt "$PLAN090_SOURCE_RECEIPT" \
  --freeze "$PLAN090_FREEZE" --route "$PLAN090_ROUTE_CONTRACT" \
  --data-bundle "$PLAN090_DATA_ROOT" --snapshot "$PLAN090_MODEL_ROOT" \
  --model-lock "$PLAN090_MODEL_LOCK" --run-spec "$PLAN090_RUN_SPEC" \
  --budget-snapshot "$PLAN090_BUDGET" \
  --artifact-root "$PLAN090_ARTIFACT_ROOT" --state-output "$PLAN090_STATE" \
  --process-receipt-output "$PLAN090_PROCESS"
```

For the second BF16 and FP32 starts, pass each already finalized predecessor
with `--prior-run-result` in frozen order.  The CLI rejects a run ID that is not
the exact next conditional branch.  Set `PLAN090_ARTIFACT_ROOT` exactly to
`$PLAN090_TASK_ROOT/<artifact_namespace>/artifacts`; arbitrary task-owned
directories are rejected.

Finalize each valid run immediately and call `next-action`.  A valid negative
BF16 result is terminal NO-GO: do not rerun it, change seed, tune a threshold or
change the rubric.  FP32 is an entire-model FP32 parameter-training condition
control and never automatically vetoes two passing BF16 clean runs.

## 6. Recovery and retention

Before publishing PASS, recover the final second-seed BF16 checkpoint in a
different OS process.  `verify-recovery` restores model, optimizer/scheduler,
RNG and data cursor, performs zero updates, records the exact checkpoint role,
and returns the state to completed so `finalize-run` can bind the recovery
receipt.  It also requires a refreshed positive complete-closure
`--budget-snapshot`.  Negative intermediates do not need this candidate-level
recovery.

If both BF16 clean results are valid and positive but this mandatory
fresh-process recovery or its infrastructure closure cannot complete, publish
`INCONCLUSIVE_INFRASTRUCTURE`.  Never use that outcome to override any valid
negative BF16 result.

Retain only exact-base references, complete small observations/results/pair
margins, budget/resource snapshots, the final effective candidate checkpoint
and its recovery receipt for PASS, or the decisive negative checkpoint/result
for NO-GO.  All weights and checkpoints remain on the network volume.

## 7. Handoff and zero-compute terminal

Use the existing reviewed Plan 087 handoff envelope through the Plan 090 CLI to
stage only JSON/JSONL/log/text artifacts under its allowed result, receipt,
cost, resource and log prefixes.  Verify the exact tree before copying it back.
This legacy schema name is deliberate mechanism reuse, not Plan 087 provenance.

After the small handoff exists locally, immediately invoke the retained terminal
helper against the exact Plan 090 Pod ID/name and prefix.  Re-query live account
state until it shows zero Pods and compute rate 0.  Do not delete the 57GB
network volume.  Only then write the terminal result and complete local WBS,
WBS-COMPLETED and log updates; ordinary final review never reopens a Pod.
