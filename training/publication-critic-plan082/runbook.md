# Plan 082 operator runbook

This runbook is intentionally operational, not a cloud orchestrator. Exact
model/data/objective identities remain fixed in code; GPU location, volume,
task root, run recipe, parameter scopes, control points and S3 binding are
typed inputs chosen from live commissioning facts.

## 1. Authorization and resource gate

Stage A ends before this section is executed. Reviewer acceptance alone is not
paid authorization. Create no Pod or network volume until the reviewer has
explicitly relayed the user's manual paid approval.

Immediately before creation, query A40 48GB and L40S 48GB together for live
stock, price, data center, cloud type and Standard network-volume compatibility;
record the cost baseline. Prefer A40, use L40S only as the allowed fallback,
and keep at most one billable GPU. Create the smallest practical Plan 082
network volume in the chosen compatible center and mount it at `/workspace`.
The Plan 079 polling helper may be used only with the exact live placeholders
and finite timeout shown in the ExecPlan. It does not select a GPU, create a
volume, start/stop/delete a Pod, or reconcile two concurrent creators.

Use a unique task root such as `/workspace/rondo-plan082-<run>`. Never reuse the
Plan 068/079 volume, endpoint or task root. Track training GPU time/cost against
12 hours and 15 USD; report retention/handoff/storage separately. Send the
one-time nonblocking queue warning when combined actual cost or conservative
upper bound first reaches 10 USD.

## 2. Build and upload the two inputs

From a clean committed Plan 082 worktree, create the narrow source archive:

```bash
PYTHONPATH=eval python -B -m \
  rondo_eval.publication_critic.full_model_training.plan082_cli \
  create-source-archive --repo "$PLAN082_REPO" --commit "$PLAN082_COMMIT" \
  --output "$PLAN082_SOURCE_TAR" > "$PLAN082_SOURCE_RECEIPT"
```

The data archive is built only from the canonical, already verified physical
Plan 066 train+validation bundle. It does not read mixed v8 and contains exactly
the typed contract, rubric, train+validation body and its Plan 082 manifest:

```bash
PYTHONPATH=eval python -B -m \
  rondo_eval.publication_critic.full_model_training.plan082_cli \
  prepare-data --canonical-plan066 "$PLAN066_CANONICAL" \
  --output "$PLAN082_DATA_ROOT"
PYTHONPATH=eval python -B -m \
  rondo_eval.publication_critic.full_model_training.plan082_cli \
  create-data-archive --bundle "$PLAN082_DATA_ROOT" \
  --output "$PLAN082_DATA_TAR"
```

Upload only these two archives; carry their SHA-256 values and the 40-hex source
commit as nonsecret launch parameters. The cloud bootstrap derives the source
receipt again from the exact extracted bytes. Do not upload `.env.local`,
ignored caches, unseen data, model weights, or unrelated project files.

## 3. Bootstrap and commissioning

Set task-owned absolute paths, including `RONDO_PLAN082_SOURCE_COMMIT`, and set
`RONDO_PLAN082_IMAGE_IDENTITY` to the exact approved container image identity,
then run `runpod-bootstrap.sh`. The first invocation may be streamed from the archive
after checking its known SHA-256; the script verifies the archive again before
using its code. It stages and exactly verifies source before atomic publication,
re-verifies correct existing source/data on retry, installs the small locked
dependency set without replacing image Torch, downloads only the exact public
1.7B revision, and verifies every model file against the tracked lock.
Dependency/install/download output is isolated in the task-owned bootstrap log.
Successful stdout contains only one canonical ready result, also published as a
stable task-owned receipt; that receipt binds source, data, exact snapshot,
actual installed-environment receipt, and all three roots. An identical retry
reuses the same receipts, while a changed input fails instead of overwriting them.

After bootstrap, create a run spec from the observed `named_parameters()`
inventory. Start with a partial original-parameter scope. The tracked recipe is
only a commissioning candidate; adjust the optimizer/batch/scope/control
parameters from real memory and training behavior as needed, while preserving
the fixed scalar, direction, Binary/Pair losses and equal component weights.
The recipe also selects `parameter_dtype` (`float32` or `bfloat16`); this is a
commissioning parameter, not a hidden loader default. Every accepted macro
update records one current-scope original parameter whose stored numeric value
changed across the optimizer step. A nonzero gradient with no representable
change is rejected, so commissioning must adjust dtype, learning rate, or scope
before freezing. The run-spec schema is:

```json
{
  "schema": "rondo-publication-critic-plan082-run-spec-v1",
  "recipe": {"...": "validated recipe"},
  "initial_scope": {"...": "actual parameter names and element count"},
  "scope_schedule": [
    {"after_observation_step": 1, "scope": {"...": "strict expansion"}}
  ],
  "control_plan": {
    "maximum_updates": 4,
    "observation_steps": [1, 2, 3, 4],
    "checkpoint_steps": [2, 4],
    "turning_point_limit": 2
  },
  "comparison_policy": {
    "metric": "boundary_pair_mean_margin",
    "direction": "higher_is_better",
    "tolerance": 0.0
  },
  "report_threshold": 0.5
}
```

Invoke the CLI with the venv interpreter and explicit source path; do not rely
on `PYTHONPATH` exported by a completed bootstrap process:

```bash
env PYTHONPATH="$source_root/eval" "$task_root/venv/bin/python" -B -P -m \
  rondo_eval.publication_critic.full_model_training.plan082_cli start \
  --source-archive "$source_archive" --source-root "$source_root" \
  --source-receipt "$source_receipt" --route "$route" \
  --data-bundle "$data_root" --snapshot "$model_root" \
  --model-lock "$model_lock" --run-spec "$run_spec" \
  --artifact-root "$artifact_root" --state-output "$state_output" \
  --process-receipt-output "$process_receipt" --stop-after "$stop_after"
```

The same source triple is mandatory for `resume`; additionally pass the
qualified checkpoint ID, source process receipt and new recovery receipt output.
Give start and resume distinct state, process-receipt, and recovery-receipt
paths, all outside the artifact namespace. The CLI rejects existing, symlinked,
or aliased segment outputs before creating the artifact namespace or performing
an update.
`--stop-after` supports bounded commissioning. Resume only from a qualified
checkpoint with `plan082_cli resume`, passing the source process receipt and a
new recovery receipt output. Resume rejects the same host PID and proves at
least one subsequent update. The controller records the actual scope history,
full validation observations and a complete optimizer/scheduler/RNG/data state.

Use `runpod-launch.sh -- <command...>` to detach that explicit command under one
task-root lock and write a unique status/log/PID. Set a positive finite
`RONDO_PLAN082_MAX_SECONDS`; timeout is reported as command failure. The wrapper
does not reinterpret arbitrary command arguments. Do not start two Plan 082
launchers or creator monitors concurrently.

Commissioning is not a formal result. Preserve verified progress while fixing
the first broken link until exact load, update, observation, full checkpoint,
fresh-process resume and continuation have all worked. Then commit the final
result-related source and build a new source archive.

## 4. Freeze and one clean formal run

Choose the final recipe, deterministic scope schedule, seed, observation and
checkpoint points, same-cohort comparison/tolerance and retention roles. The
formal artifact namespace must not yet exist. Run `freeze-formal` with the venv
interpreter and explicit `PYTHONPATH`, committed source receipt, data bundle,
route, snapshot, model lock, final run spec, new formal namespace and freeze
output. The freeze records the full original-model parameter inventory and
chooses the latest declared checkpoint before the terminal update as its
required recovery boundary.

Start the clean formal run from the exact base with `--formal-freeze` and
`--stop-after` equal to that frozen recovery boundary. Exit the process, then
use `resume` from the checkpoint and a new OS process to continue to the frozen
maximum. Both commands require the exact source archive/root/receipt triple.
The finalizer accepts only a controller state carrying the pre-run freeze
identity and the new-process recovery receipt. Run every command in this
section with the same explicit venv/PYTHONPATH form:

```bash
env PYTHONPATH="$source_root/eval" "$task_root/venv/bin/python" -B -P -m \
  rondo_eval.publication_critic.full_model_training.plan082_cli \
  finalize-formal --freeze "$FREEZE" --controller-state "$FINAL_STATE" \
  --recovery-receipt "$RECOVERY_RECEIPT" --artifact-root "$artifact_root" \
  --output "$FORMAL_RESULT"
```

The finalizer reopens that exact artifact root and verifies the exact-base
observation, all completed-history observation/snapshot/checkpoint relations,
selection, latest and recovery checkpoint identities, retained artifact set,
content identities and retention-completion marker. The final candidate is the
best validation observation that has a complete qualified checkpoint; the
all-observation training best remains diagnostic.
Its checkpoint and small snapshot reference are retained even when a better
non-checkpoint observation exists. An improved frozen comparison produces
`TRAINING_IMPROVEMENT_FOUND`; a valid complete run without improvement produces
`VALID_NO_IMPROVEMENT`. Do not change seed, tolerance, comparison rule or recipe
and rerun a valid result to seek a positive outcome.

## 5. GPU review, release, and zero-Pod handoff

Before GPU review, generate the small bootstrap directly from the formal result
and retained artifact store. The producer verifies the exact retained ID set
and artifact manifests, then scans only those task-root artifact trees for
ordinary files—including the base and every permanent validation observation—
and derives every relative key, byte size, SHA-256 and role:

```bash
env PYTHONPATH="$source_root/eval" "$task_root/venv/bin/python" -B -P -m \
  rondo_eval.publication_critic.full_model_training.plan082_cli \
  create-handoff-bootstrap --freeze-sha256 "$FREEZE_SHA256" \
  --task-root "$task_root" --artifact-root "$artifact_root" \
  --formal-result "$FORMAL_RESULT" --output "$BOOTSTRAP_MANIFEST"
```

The nonsecret Plan 082 S3
binding records the live volume ID, region-matching HTTPS RunPod endpoint, task
root, allowed prefixes, ignored destination and exact bootstrap key/bytes/hash.
Then use `create-handoff-binding`; it derives the RunPod endpoint from the live
region and the ignored destination from the run ID. The transfer CLI accepts
this one binding and has no per-field endpoint/root overrides. Upload the
bootstrap to its bound key only after it and the retained inventory are final.

Submit only small evidence for GPU review: source/recipe/freeze identities,
metrics and pair margins, checkpoint path/size/SHA-256, recovery receipt, cost,
and Pod/volume state. Keep Pod and volume. Do not download a large checkpoint.
Release the Pod only after the reviewer explicitly says no further GPU work is
needed, then confirm zero Pod and zero compute billing. Keep the volume.

Wait for a Plan 083-free and capacity-safe local window. From the exact retained
Plan 082 worktree, prepare the one project-local pinned handoff environment
once. It lives in the main physical root's ignored Plan 082 directory:

```bash
training/publication-critic-plan082/prepare-local-handoff.sh
training/publication-critic-plan082/run-local-handoff.sh \
  --dry-run inventory --binding "$PLAN082_S3_BINDING"
training/publication-critic-plan082/run-local-handoff.sh \
  --dry-run download --binding "$PLAN082_S3_BINDING"
training/publication-critic-plan082/run-local-handoff.sh \
  inventory --binding "$PLAN082_S3_BINDING"
training/publication-critic-plan082/run-local-handoff.sh \
  download --binding "$PLAN082_S3_BINDING"
```

Both dry-runs validate the exact boto3 environment, worktree source and ignored
destination without reading secrets or touching the network. Both real commands
use that same interpreter and explicit `PYTHONPATH`. The strict loader reads
only the two allowlisted RunPod S3 values from the main
root `.env.local` and injects them directly into the client. Never put secrets
in arguments, receipts or logs. Inventory downloads/verifies the small
bootstrap first; download then uses its exact manifest, `.part` Range resume,
size/SHA-256 verification, atomic publication and refusal to overwrite wrong
existing bytes. Repeating either command is safe for correct existing files.

Apply the ExecPlan's 270/285/290GB project limits and Windows C: capacity facts
before and throughout large transfer. If facts or the shared-disk window are
unsafe, keep zero Pod and wait with the network volume. After final review, the
volume remains until the user personally approves deletion.
