# Plan 094 operator runbook

Sections 2-6 are paid Stage B.  They must not run until the reviewer replies
exactly: `Plan 094 阶段 A 验收通过，批准进入付费阶段`.

## 1. Stage A freeze and clean bundles

Validate the tracked freeze and, after the Stage A commit, create a source tar
from that exact clean commit.  Reuse the canonical Plan 082 physical
train+validation projection only after both verification and extraction report
content SHA-256
`2247dd09c168900a47d37a50ecd6511d66d62d3f2ec8056ea3bc829c93de8b46`
and physical unseen count zero.  Inspect tar members.  Rebuild the source tar
after any tracked code change.

```bash
PYTHONPATH=eval python3 -B -m \
  rondo_eval.publication_critic.full_model_training.plan094_cli \
  validate-freeze \
  --freeze training/publication-critic-plan094/continuous-freeze-v1.json
PYTHONPATH=eval python3 -B -m \
  rondo_eval.publication_critic.full_model_training.plan094_cli \
  create-source-archive --repo "$PLAN094_REPO" --commit "$PLAN094_COMMIT" \
  --output "$PLAN094_SOURCE_TAR" --receipt-output "$PLAN094_SOURCE_RECEIPT"
```

## 2. Live budget, inventory, and one-Pod gate

After approval, refresh balance, known unsettled billing, secure L40S price and
inventory, account Pod list, and volume `mwemzrn33y`.  Require zero pre-existing
Pods.  Every action consumes a validated snapshot with one fixed Stage B
baseline, monotonic conservative task cost, a closure reserve, and the cost of
the proposed segment plus checkpoint/result transfer/termination.  The action
headroom is the smaller of remaining 5 USD task headroom and live account
headroom after reserve.  Write the fresh snapshot inside the Plan 094 task root
and set `RONDO_PLAN094_BUDGET_SNAPSHOT`, the independently verified aggregate
compute and storage rates, and a finite `RONDO_PLAN094_MAX_SECONDS`.  The
bootstrap/launch seam rejects a snapshot older than five minutes or a timeout
whose full rate-bound cost plus closure reserve does not fit.  Do not recharge.

If no US-TX-3 L40S is immediately available, use only:

```bash
python3 scripts/create-runpod-when-ready.py \
  --pod-name "$PLAN094_POD_NAME" --image "$PLAN094_IMAGE" \
  --gpu-id "$PLAN094_GPU_ID" --gpu-count 1 --cloud-type SECURE \
  --data-center-id US-TX-3 --network-volume-id mwemzrn33y \
  --container-disk-gb "$PLAN094_CONTAINER_GB" \
  --volume-mount-path /workspace --port 22/tcp
```

The helper only polls, creates, and reconciles an uncertain response by exact
name.  Independently verify actual GPU, count, secure cloud, US-TX-3, price,
image/container disk and mounted volume immediately after creation.  Release a
mismatch with the retained Plan 087 terminal helper using prefix
`rondo-plan094-`, then confirm account-level zero Pods.  Never create a second
volume/Pod, change region/GPU, or expose unseen.

## 3. Bootstrap and asset boundaries

Create one new `/workspace/rondo-plan094-<run>/incoming`, upload only verified
source and physical train+validation archives, set the `RONDO_PLAN094_*`
variables including `RONDO_PLAN094_STAGE_B_APPROVED=1`, then run
`runpod-bootstrap.sh` with no arguments.  Its internal timeout covers the whole
bootstrap segment and its fresh budget authorization is recorded before pip,
snapshot reuse/download, or model work.  It exact-tree verifies both inputs,
uses a task-local venv, preserves image Torch, and reuses a verified exact
snapshot read-only.  Only if no exact snapshot exists may it download the
frozen public revision; all Hub token variables are unconditionally unset
before either snapshot branch and there is no upload path.

Plan 082/087/090 roots are read-only.  Plan 094 writes only its new root.  Check
actual free bytes before each complete checkpoint.  Prune only evaluated,
unselected Plan 094 checkpoints; pending checkpoints and candidate/latest/
turning/recovery roles are protected.  Expand the same volume only if actually
needed, and never beyond 80 GB.

## 4. Commissioning then clean formal start

Load the exact model, produce the 311-tensor inventory, and materialize an
immutable commissioning run spec.  Primary continuation is the exact retained
Plan 090 checkpoint:

`/workspace/rondo-plan090-20260827-confirm01/formal/bf16-seed-20260902/artifacts/recovery-checkpoints/checkpoint-attempt-000-step-000001`

The controller accepts it only at exact content SHA-256
`8b4b88b66a88cc50fa10d5f20c575b9a67c6f254f6e26350d38ce4896b949a69`
and 3,591,369,941 bytes, validates the complete Plan 090 controller state,
restores model/optimizer/scheduler/RNG/data cursor, matches a same-run exact
base, and re-scores it.  If that guarded import fails, discard the commissioning
namespace and use the pre-frozen exact-base rebuild mode; never stitch partial
state.

Commissioning must prove: effective Route O update, atomic full checkpoint,
deep readback, checkpoint-backed train/validation evaluation, small-overlay
retry, new-process restore, and continued next update.  Preserve valid progress
while fixing ordinary seams.  Once the whole chain works, freeze an empty
formal namespace and a clean source/environment identity; debug evidence is
not a formal result.

## 5. Checkpoint-first formal trajectory

For every process, refresh and validate the budget snapshot.  Set artifact root
exactly to `$RONDO_PLAN094_TASK_ROOT/<artifact_namespace>/artifacts`.
`start` either imports Plan 090 step 1 or rebuilds step 1 from exact base.
`resume` consumes a task-owned Plan 094 checkpoint in a different OS process.
Run inventory, commissioning, start/resume and post-check commands only through
`runpod-launch.sh`; each unique launch consumes its own fresh budget snapshot
and writes an authorization receipt before starting its bounded worker.  Use
`--stop-after` to advance only to the next intended observation point.

The controller order is fixed: update, full atomic checkpoint, manifest/tree
readback and independent restore qualification, then validation/train
evaluation and an atomic small overlay.  A failed evaluation replays the same
checkpoint without another update.  At least one formal checkpoint must be
restored in a new process and continue to the next effective update; terminal
model status is deferred until this is true.  Establish that proof before the
maximum point.

After each overlay, read the pre-frozen material/stop decision.  Stop on the
first complete material candidate.  Otherwise stop at the pre-frozen three-new-
checkpoint plateau or global step 6.  A valid negative is final and must not be
rerun, tuned, or hidden as infrastructure failure.  Validation is selection
data only; unseen remains absent.

## 6. Small handoff and zero-compute closure

Retain permanent small overlays/receipts and at most six role-deduplicated full
checkpoints, the complete trajectory's hard upper bound.  Large weights remain
on the network volume.  Return only the
small controller/result, budget/resource receipts, and concise logs.  Once no
GPU-dependent check remains, immediately release every Plan 094 Pod with the
Plan 087 terminal helper and live-query until Pod count is zero and compute
rate is 0 USD/hour.  Keep the volume and record its ID, US-TX-3, size (57-80 GB)
and rate.

Only after zero-compute closure run `finalize-terminal`.  Its positive/negative
branches require a formal run, replayed overlay history, a fresh-process
restore-and-continue proof, monotonic budget state, and the zero-Pod resource
receipt.  `INCONCLUSIVE` cannot override an already valid material or negative
model decision.  Local documentation and review never justify restarting a
Pod.
