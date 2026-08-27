# Plan 087 operator runbook

This runbook carries the staged authorization and the few live choices that
cannot be frozen before RunPod inventory is known. Commands in sections 2-8 are
for Stage B only and must not run until the reviewer has replied exactly that
Stage A passed and paid execution is approved.

## 1. Stage A handoff

From the clean committed Plan 087 worktree, create the narrow source archive
and the physical train+validation-only data archive under the ignored local
Plan 087 namespace. Verify both archives and inspect their member lists before
any upload. The source archive is built from its exact commit; the data archive
reuses the Plan 082 projection of the canonical Plan 066 bundle and contains
zero unseen rows and no unseen body.

```bash
PYTHONPATH=eval python -B -m \
  rondo_eval.publication_critic.full_model_training.plan087_cli \
  create-source-archive --repo "$PLAN087_REPO" --commit "$PLAN087_COMMIT" \
  --output "$PLAN087_SOURCE_TAR" > "$PLAN087_SOURCE_RECEIPT"
PYTHONPATH=eval python -B -m \
  rondo_eval.publication_critic.full_model_training.plan087_cli \
  prepare-data --canonical-plan066 "$PLAN066_CANONICAL" \
  --output "$PLAN087_DATA_ROOT"
PYTHONPATH=eval python -B -m \
  rondo_eval.publication_critic.full_model_training.plan087_cli \
  create-data-archive --bundle "$PLAN087_DATA_ROOT" \
  --output "$PLAN087_DATA_TAR" > "$PLAN087_DATA_ARCHIVE_RECEIPT"
```

Do not create, start, query or modify RunPod resources in Stage A. Send the
committed Stage A result to the reviewer queue and stop the session.

## 2. Live baseline, inventory and budget gate

After explicit Stage B approval, write all provider JSON to the ignored Plan
087 local namespace. Query, but do not mutate, the account, Pod list, both
allowed GPU types, billing and network volumes:

```bash
runpodctl user -o json
runpodctl pod list --all -o json
runpodctl gpu list --include-unavailable -o json
runpodctl billing pods -o json
runpodctl billing network-volume -o json
runpodctl network-volume list -o json
```

The first live balance is the immutable task baseline. Compute
`initial_available_usd = min(9, baseline_balance_usd - 0.14)`. Before every
mutation or new training segment, write a raw cost snapshot and validate it
with `plan087_cli validate-cost-snapshot`. Snapshot 0 has a null previous hash;
every later snapshot increments `snapshot_index`, binds the previous validated
`content_sha256`, keeps the original balance baseline, and retains all earlier
cost entries as an exact prefix. Validate later snapshots with
`--previous-cost-snapshot`; do not skip or rewrite a ledger entry.
`provider_task_billing_usd` is the maximum cumulative task billing observed so
far, so a delayed provider correction cannot make the recorded value decrease.

```json
{
  "schema": "rondo-publication-critic-plan087-cost-snapshot-v1",
  "captured_at": "<RFC3339>",
  "snapshot_index": 0,
  "previous_snapshot_content_sha256": null,
  "baseline_balance_usd": 9.14,
  "current_balance_usd": 9.14,
  "provider_task_billing_usd": 0.0,
  "cost_entries": [],
  "initial_available_usd": 9.0,
  "projected_next_increment_usd": 0.75
}
```

```bash
PYTHONPATH=eval python -B -m \
  rondo_eval.publication_critic.full_model_training.plan087_cli \
  validate-cost-snapshot --cost-snapshot "$PLAN087_COST_RAW" \
  > "$PLAN087_COST_VALIDATED"
PYTHONPATH=eval python -B -m \
  rondo_eval.publication_critic.full_model_training.plan087_cli \
  validate-cost-snapshot --previous-cost-snapshot "$PLAN087_COST_VALIDATED" \
  --cost-snapshot "$PLAN087_NEXT_COST_RAW" > "$PLAN087_NEXT_COST_VALIDATED"
```

Cost entries are cumulative across all sequential Pods and include compute,
container disk, volume holding, volume creation/extension and small result
transfer. Use one immutable entry per independently estimated interval/action;
for delayed provider billing, keep the wall-clock × live-rate entries rather
than dropping them. The conservative task cost is the maximum of balance
delta, provider task billing and the sum of independent entries. The next
action is allowed only when its complete estimated increment fits both task
headroom and current balance minus 0.14 USD. Leave additional stopping room
for delayed billing.

There must be zero existing Pods before a first creation. On replacement, the
old exact Pod must first be stopped and deleted and account-level zero Pods
confirmed. Never touch an unrelated Pod. Any task Pod name starts with
`rondo-plan087-`; at most one may bill at any time.

Choose one secure-cloud A40 48GB or L40S 48GB from current stock and price.
Prefer the existing `mwemzrn33y` volume when its data center is compatible.
Record its ID, region, size, holding rate and the Plan 082 roots that remain
read-only. The only remote write root is a fresh
`/workspace/rondo-plan087-<run>` directory.

## 3. Capacity and resource creation

Before a checkpoint, collect actual volume use and a conservative replacement
checkpoint estimate. Validate a capacity-preflight JSON with
`plan087_cli capacity-preflight --input <json>`. Record provider `size_gb` in
decimal GB; never convert it as GiB. When the network-volume FUSE mount reports
the shared backend through `df` rather than the task volume quota, derive
`capacity_bytes = size_gb * 1000000000`, collect exact used bytes with
`du -s -B1 --one-file-system /workspace`, and set `available_bytes` to the
nonnegative difference. Preserve the raw `df`, `du` and provider observations.
Atomic publication needs the actual used bytes plus checkpoint staging and
reserve space. Every `start`, `resume` or `verify-recovery` command requires
this latest preflight, and refuses to enter a checkpoint-producing segment
unless `checkpoint_write_ready=true`.
If not ready,
extend by the smallest practical increment that satisfies the returned
`recommended_size_gb`, never above 60GB:

```json
{
  "schema": "rondo-publication-critic-plan087-capacity-preflight-v1",
  "captured_at": "<RFC3339>",
  "volume_id": "mwemzrn33y",
  "current_size_gb": 40,
  "capacity_bytes": 40000000000,
  "available_bytes": 8789929022,
  "checkpoint_estimate_bytes": 7000000000,
  "atomic_staging_copies": 2,
  "reserve_bytes": 1000000000,
  "maximum_size_gb": 60
}
```

```bash
runpodctl network-volume update "$PLAN087_VOLUME_ID" --size "$NEW_SIZE_GB" -o json
```

If the existing volume's region remains unusable, create at most one task
volume in the selected compatible data center, initially only as large as the
next useful closure requires:

```bash
runpodctl network-volume create --name "$PLAN087_VOLUME_NAME" \
  --data-center-id "$PLAN087_DATA_CENTER" --size "$INITIAL_SIZE_GB" -o json
```

There is deliberately no network-volume delete command in this runbook or the
task lifecycle helper.

Create one Pod with the selected image, GPU ID, data center and volume. When
stock is tight, use the repository-wide latency-sensitive helper:

```bash
python3 scripts/create-runpod-when-ready.py \
  --pod-name "$PLAN087_POD_NAME" --image "$PLAN087_IMAGE" \
  --gpu-id "$PLAN087_GPU_ID" --gpu-count 1 --cloud-type SECURE \
  --data-center-id "$PLAN087_DATA_CENTER" \
  --network-volume-id "$PLAN087_VOLUME_ID" \
  --container-disk-gb "$PLAN087_CONTAINER_GB" \
  --volume-mount-path /workspace --port 22/tcp \
  --poll-seconds 5 --query-timeout-seconds 15 \
  --create-timeout-seconds 30 --reconciliation-grace-seconds 30
```

The helper only polls inventory, submits create, and reconciles an uncertain
response by exact name before another attempt. Its JSON lines are status output,
not a resource qualification or receipt, and it performs no budget, price,
volume-eligibility, readiness, upload, training, stop or delete work.

Immediately after it reports an accepted or reconciled Pod, independently query
that exact ID with the existing RunPod MCP v2 `get_pod`, `runpodctl pod get/list`,
live GPU pricing/inventory and network-volume state. Check the actual price, one
allowed GPU, Secure Cloud, exact data center, image/container disk, and exactly
one network mount whose `volumeId` is the selected volume and whose path is
`/workspace`. A field still initializing may be re-read for a short operator
deadline, but no Plan 087 adapter or creation receipt is produced. If any fact
is wrong or cannot be confirmed, immediately invoke `runpod-terminal.py` for
the exact ID/name and confirm account-level zero before trying again. Do not
connect, upload or bootstrap until the independent checks pass.

Bind the confirmed exact ID and name in the task log. Use `runpodctl ssh info
<pod-id>` after every start/restart to refresh the SSH endpoint. Before upload,
create the fresh `/workspace/rondo-plan087-<run>/incoming` tree through that
endpoint and request mode `0700` for both directories. A provider FUSE mount
may normalize the observed mode (the live Plan 087 mount reported `0777` with
`allow_other`); record the actual `stat` and mount options rather than claiming
the requested mode was enforced. Upload only the two verified archives into
`incoming/` with `scp`; do not upload the worktree, ignored history, secrets,
unseen data or a local model.

## 4. Bootstrap the exact source, data, environment and model

Create the task root with mode 0700, set the `RONDO_PLAN087_*` variables and run
`runpod-bootstrap.sh`. The script rejects task roots outside the dedicated
Plan 087 namespace, verifies source/data before use, installs only the pinned
small dependencies and leaves image Torch intact. It invokes the Hugging Face
CLI with the exact public repository revision
`e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`, unsets token variables and verifies
every downloaded file against the tracked model lock. It never uploads to the
Hub.

The model, environment and large artifacts stay on the network volume. Keep
bootstrap logs and receipts under the task root. Failures may be fixed and
retried in the same debug namespace when already verified inputs remain valid.

## 5. Debug closure, then clean search

First use a task-owned `debug/` artifact namespace. Generate the real parameter
inventory, materialize one route candidate against a route-context JSON, and
validate the resulting run spec. `PLAN087_RECIPE` below is the candidate's
inner `.recipe` object, not the outer route-candidate document:

```bash
env RONDO_PLAN087_IMAGE_IDENTITY="$PLAN087_IMAGE" \
  PYTHONPATH="$PLAN087_SOURCE_ROOT/eval" "$PLAN087_TASK_ROOT/venv/bin/python" \
  -B -P -m rondo_eval.publication_critic.full_model_training.plan087_cli \
  parameter-inventory --snapshot "$PLAN087_MODEL_ROOT" \
  --model-lock "$PLAN087_MODEL_LOCK" --recipe "$PLAN087_RECIPE" \
  > "$PLAN087_INVENTORY"
env RONDO_PLAN087_TASK_ROOT="$PLAN087_TASK_ROOT" \
  PYTHONPATH="$PLAN087_SOURCE_ROOT/eval" "$PLAN087_TASK_ROOT/venv/bin/python" \
  -B -P -m rondo_eval.publication_critic.full_model_training.plan087_cli \
  materialize-run-spec --candidate "$PLAN087_ROUTE_CANDIDATE" \
  --route-context "$PLAN087_ROUTE_CONTEXT" --inventory "$PLAN087_INVENTORY" \
  --output "$PLAN087_RUN_SPEC"
```

The segment commands are explicit and use fresh, non-aliasing output names.
For the first segment:

```bash
env PYTHONPATH="$PLAN087_SOURCE_ROOT/eval" "$PLAN087_TASK_ROOT/venv/bin/python" \
  -B -P -m rondo_eval.publication_critic.full_model_training.plan087_cli start \
  --source-archive "$PLAN087_SOURCE_ARCHIVE" --source-root "$PLAN087_SOURCE_ROOT" \
  --source-receipt "$PLAN087_SOURCE_RECEIPT" --route "$PLAN087_ROUTE_CONTRACT" \
  --data-bundle "$PLAN087_DATA_ROOT" --snapshot "$PLAN087_MODEL_ROOT" \
  --model-lock "$PLAN087_MODEL_LOCK" --run-spec "$PLAN087_RUN_SPEC" \
  --capacity-preflight "$PLAN087_CAPACITY_VALIDATED" \
  --artifact-root "$PLAN087_ARTIFACT_ROOT" --state-output "$PLAN087_STATE_1" \
  --process-receipt-output "$PLAN087_PROCESS_1" --stop-after 1
```

For a continuing segment, bind the exact checkpoint and prior process receipt;
`resume` must perform at least one subsequent update:

```bash
env PYTHONPATH="$PLAN087_SOURCE_ROOT/eval" "$PLAN087_TASK_ROOT/venv/bin/python" \
  -B -P -m rondo_eval.publication_critic.full_model_training.plan087_cli resume \
  --source-archive "$PLAN087_SOURCE_ARCHIVE" --source-root "$PLAN087_SOURCE_ROOT" \
  --source-receipt "$PLAN087_SOURCE_RECEIPT" --route "$PLAN087_ROUTE_CONTRACT" \
  --data-bundle "$PLAN087_DATA_ROOT" --snapshot "$PLAN087_MODEL_ROOT" \
  --model-lock "$PLAN087_MODEL_LOCK" --run-spec "$PLAN087_RUN_SPEC" \
  --capacity-preflight "$PLAN087_CAPACITY_VALIDATED" \
  --artifact-root "$PLAN087_ARTIFACT_ROOT" --checkpoint-id "$PLAN087_CHECKPOINT" \
  --source-process-receipt "$PLAN087_PROCESS_1" \
  --state-output "$PLAN087_STATE_2" --process-receipt-output "$PLAN087_PROCESS_2" \
  --recovery-receipt-output "$PLAN087_RESUME_RECEIPT_2"
```

Use `runpod-launch.sh -- <exact command>` for bounded detached segments. In the
debug namespace, continue from the first unproven link until exact-base load,
one real update, same-cohort validation, checkpoint qualification, separate
process recovery and result finalization all work. Preserve useful verified
progress while fixing ordinary environment, OOM, dependency, connection or
checkpoint issues. Debug weights are never candidates.

Once that whole chain is stable, freeze the source/config actually used and
start the budget search from exact base in a fresh `formal-search/` artifact
namespace. Do not splice debug observations into it.

## 6. Adaptive search and candidate decision

Start a route at its first observation/checkpoint and inspect the complete
metrics and signed pair margins against `base-step-000000`. A route context
records the exact-base start, prior route-result hashes, cost snapshot, changes
and the reason those changes are being tried. A later route must include one
hash-bound prior summary for every earlier route.

Resolve every scope from the live parameter inventory. A new exact-base route
may be narrower, wider or select a different responsibility using score/final
modules, any available terminal depth, explicit dotted module prefixes or all
parameters. Only later scope phases inside the same route are monotonic: their
actual resolved parameter set must strictly contain the prior phase. Thus a
checkpoint never changes the meaning of already-created optimizer state, while
the next exact-base route is not forced into a four-block terminal sweep.

Do not classify a candidate from floating noise, a uniform logit offset, a
threshold-only change or one isolated aggregate. The operator assessment has
four booleans: clear ranking/pair improvement, no material companion collapse,
not noise/offset/threshold-only, and complete-metric review. The code requires
an improving ranking or pair signal but intentionally leaves the holistic
judgment and reason to the executor.

If an observation is promising, do not perform another search update. Exit the
process and run `verify-recovery` on that exact latest checkpoint from a new OS
process. It restores model, optimizer/scheduler, RNG, data cursor, actual scope,
route history, observations and selection state, records the selected
checkpoint's recovery identity, and performs no update. Finalize the route with
that recovered controller state and the assessment JSON. The finalizer rejects
a different latest/recovery checkpoint.

```bash
env PYTHONPATH="$PLAN087_SOURCE_ROOT/eval" "$PLAN087_TASK_ROOT/venv/bin/python" \
  -B -P -m rondo_eval.publication_critic.full_model_training.plan087_cli \
  verify-recovery --source-archive "$PLAN087_SOURCE_ARCHIVE" \
  --source-root "$PLAN087_SOURCE_ROOT" --source-receipt "$PLAN087_SOURCE_RECEIPT" \
  --route "$PLAN087_ROUTE_CONTRACT" --data-bundle "$PLAN087_DATA_ROOT" \
  --snapshot "$PLAN087_MODEL_ROOT" --model-lock "$PLAN087_MODEL_LOCK" \
  --run-spec "$PLAN087_RUN_SPEC" --capacity-preflight "$PLAN087_CAPACITY_VALIDATED" \
  --artifact-root "$PLAN087_ARTIFACT_ROOT" --checkpoint-id "$PLAN087_CHECKPOINT" \
  --source-process-receipt "$PLAN087_LAST_PROCESS" \
  --state-output "$PLAN087_RECOVERED_STATE" \
  --process-receipt-output "$PLAN087_RECOVERY_PROCESS" \
  --recovery-receipt-output "$PLAN087_RECOVERY_RECEIPT"

env PYTHONPATH="$PLAN087_SOURCE_ROOT/eval" "$PLAN087_TASK_ROOT/venv/bin/python" \
  -B -P -m rondo_eval.publication_critic.full_model_training.plan087_cli \
  finalize-route --controller-state "$PLAN087_RECOVERED_STATE" \
  --artifact-root "$PLAN087_ARTIFACT_ROOT" \
  --selected-observation-id "$PLAN087_OBSERVATION" \
  --selected-checkpoint-id "$PLAN087_CHECKPOINT" \
  --operator-disposition promising \
  --recovery-role promising_candidate --operator-reason "$PLAN087_REASON" \
  --operator-assessment "$PLAN087_ASSESSMENT" --cost-snapshot "$PLAN087_ROUTE_COST" \
  --process-receipt "$PLAN087_RECOVERY_PROCESS" \
  --recovery-receipt "$PLAN087_RECOVERY_RECEIPT" --output "$PLAN087_ROUTE_RESULT"
```

The first route context binds immutable Stage B baseline snapshot 0. Every
setup, debug and formal-route snapshot created afterward stays on the same
chain, and `finalize-route` receives all of them in index order by repeating
`--cost-snapshot`; do not pass only the last snapshot. This preserves all
cumulative setup cost without rewriting the baseline anchor. For example,
append
`--cost-snapshot "$PLAN087_ROUTE_COST_1" --cost-snapshot "$PLAN087_ROUTE_COST_2"`
when those are snapshots 1 and 2. A later route starts from the cost snapshot
bound by its route context and follows the same rule for every subsequent
snapshot.

If it is not promising and another useful observation closure still fits the
live budget, continue the route; a new-process `resume`, when needed, must
complete at least one subsequent update. The route does not have to consume
`maximum_updates`: at any saved step that has both the complete validation
observation and checkpoint, the executor may honestly close it as
`not_promising` with `--recovery-role none` and omit both recovery receipt
arguments. Set `reviewed_complete_metrics=true` and record the evidence-based
reason. Use `necessary_recovery_point` plus both exact recovery receipts only
when that non-candidate checkpoint itself has a concrete reuse need. Then use
`plan087_cli summarize-route` to derive the hash-bound compact lineage row for
the next exact-base route and choose its scope and dynamics from actual history.
There is no mechanical route-count target. Stop when a candidate is retained or
the next useful closure is unauthorized.

## 7. Small handoff and terminal result

The route result embeds base/selected full validation metrics and pair margins,
the exact run spec, selected checkpoint content identity, assessment, route
lineage and cumulative cost. Prepare only the explicit small files needed for
review: route results, validation/pair JSON, cumulative cost snapshots, resource
snapshots, selected-checkpoint metadata manifest, bootstrap/process/recovery
receipts and bounded logs. The handoff manifest rejects symlinks, weight/model/
optimizer/checkpoint payload extensions and trees, files over 16 MiB, or a total
over 64 MiB. It records role, relative path, bytes and SHA-256 for every file.

```bash
env PYTHONPATH="$PLAN087_SOURCE_ROOT/eval" "$PLAN087_TASK_ROOT/venv/bin/python" \
  -B -P -m rondo_eval.publication_critic.full_model_training.plan087_cli \
  create-handoff-manifest --task-root "$PLAN087_TASK_ROOT" \
  --entry route_result=formal-search/results/route-a.json \
  --entry validation_metrics=formal-search/results/validation-metrics.json \
  --entry pair_margins=formal-search/results/pair-margins.json \
  --entry checkpoint_manifest=formal-search/manifests/selected-checkpoint.json \
  --entry cost_snapshot=cost/latest.json \
  --entry resource_snapshot=resources/pre-terminal.json \
  --entry receipt=receipts/bootstrap-ready.json \
  --entry receipt=receipts/recovery.json \
  --entry log=logs/formal-search.log \
  --output "$PLAN087_HANDOFF_MANIFEST"

env PYTHONPATH="$PLAN087_SOURCE_ROOT/eval" "$PLAN087_TASK_ROOT/venv/bin/python" \
  -B -P -m rondo_eval.publication_critic.full_model_training.plan087_cli \
  stage-handoff --task-root "$PLAN087_TASK_ROOT" \
  --manifest "$PLAN087_HANDOFF_MANIFEST" --output "$PLAN087_HANDOFF_STAGING"
scp -r "$PLAN087_SSH:$PLAN087_HANDOFF_STAGING" "$PLAN087_LOCAL_HANDOFF"
PYTHONPATH=eval python -B -m \
  rondo_eval.publication_critic.full_model_training.plan087_cli verify-handoff \
  --root "$PLAN087_LOCAL_HANDOFF" \
  --manifest "$PLAN087_LOCAL_HANDOFF/handoff-manifest.json" --exact-tree
```

Only after local exact-tree verification succeeds may the Pod be deleted.
Never download checkpoint payloads, weights, caches, model files or the training
environment. The post-delete Pod receipt and terminal result are generated
locally and retained alongside this already verified handoff.

Choose exactly one terminal outcome:

- `PROMISING_CANDIDATE_RETAINED` after exact selected-checkpoint recovery;
- `BUDGET_EXHAUSTED_NO_CANDIDATE` only when the next cost snapshot says the
  next meaningful closure is unauthorized;
- `INCONCLUSIVE_INFRASTRUCTURE` for persistent external failure, never as a
  model-route failure.

Before terminal finalization, verify the retained checkpoint/manifest on the
volume and record every retained volume with `deleted: false`, region, capacity,
content role and continuing rate.

## 8. Stop/delete Pod and prove zero compute

After the small handoff is safely local, run the task-owned exact lifecycle
helper. It first binds the current provider object to the supplied ID, exact
Plan 087 name and one GPU, stops it, polls the stopped state, deletes that exact
ID, then requires the account Pod list to be empty. Stop/delete response
timeouts are reconciled through the exact ID and account list; if
terminate-after already removed the Pod, rerunning the command is idempotent.
The receipt also captures the empty all-Pod list, task-window Pod billing and
sanitized balance/current-spend fields. Provider error bodies are not forwarded.

```bash
python3 training/publication-critic-plan087/runpod-terminal.py \
  --pod-id "$PLAN087_POD_ID" --pod-name "$PLAN087_POD_NAME" \
  --task-started-at "$PLAN087_TASK_STARTED_AT" \
  --captured-at "$PLAN087_TERMINAL_CAPTURED_AT" \
  > "$PLAN087_LOCAL_ROOT/runpod-terminal.json"
```

Re-query user, all Pods, Pod billing and network volumes. Finalize the search
only with `pod_count: 0` and `compute_rate_usd_per_hour: 0`. Account spend may
still include retained volume holding. Never delete a network volume. Record
the final balance/cumulative conservative task cost honestly; ongoing volume
cost after the terminal snapshot is outside the Plan 087 task total and is
covered by the retained 0.14 USD reserve.

Create one final chained cost snapshot and a resource-state JSON from these
live terminal receipts, then finalize locally:

```bash
PYTHONPATH=eval RONDO_PLAN087_TASK_ROOT="$PLAN087_LOCAL_ROOT" python -B -m \
  rondo_eval.publication_critic.full_model_training.plan087_cli finalize-search \
  --route-result "$PLAN087_LOCAL_ROUTE_RESULT" --outcome "$PLAN087_OUTCOME" \
  --reason "$PLAN087_TERMINAL_REASON" --selected-route-id "$PLAN087_SELECTED_ROUTE" \
  --terminal-cost-snapshot "$PLAN087_TERMINAL_COST" \
  --resource-state "$PLAN087_RESOURCE_STATE" --output "$PLAN087_TERMINAL_RESULT"
```

If more than one cost snapshot was captured after the last route result,
repeat `--terminal-cost-snapshot` for every snapshot in increasing index order;
the terminal finalizer rejects a skipped link.

Omit `--selected-route-id` for no-candidate or infrastructure-inconclusive
outcomes. A multi-route search repeats `--route-result` in generation order.
