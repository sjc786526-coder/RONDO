# Plan 060 operator runbook

This runbook is limited to the task-owned RunPod resources authorized for Plan
060. It is not a reusable cloud account controller. All runtime output belongs
under the ignored physical-root directory
`eval-data/publication-critic/plan060/`; the worktree must not contain a second
runtime asset tree.

## Fixed boundaries

- The only candidates are Secure single-card 80 GB `NVIDIA H100 PCIe` and
  `NVIDIA H100 80GB HBM3`. Rank current stock High, then Medium, then Low;
  prefer PCIe only within the same stock grade. Never use NVL, another GPU,
  multi-GPU or another backend.
- At most one task GPU Pod may be running at any instant, including asset
  transfer. The first candidate to reach RUNNING and pass exact provider and
  hardware checks is written to the winner lock before training. Training
  results never influence selection. After lock, a replacement is permitted
  only on the exact winning GPU model, reusing its verified network volume and
  with no predecessor GPU Pod still running.
- The existing stopped local-volume Pod is a pre-selection asset source only,
  never a candidate or formal identity. Create at most two task-only 60 GB
  Standard network volumes, in the runtime-selected candidate data centers.
  A volume's data center and tier are immutable: reject any Pod/volume location
  mismatch rather than silently changing the candidate.
- The only adjustable Plan 060 cap is `hard_cap_usd` in the ignored physical-root
  `eval-data/publication-critic/plan060/controller/budget-policy.json`. There is
  no fixed paid-runtime window. The controller reloads that regular JSON file
  before every decision and derives normal-work, stop-and-recover and delete-now
  cutoffs from fixed cleanup reserves; an absent or invalid policy fails closed.
- Only the verified archive and its one Plan 059 v7 train-only smoke JSON may
  leave the host. Never upload a repository checkout, validation, unseen-test,
  caches, secrets, or another task's assets.
- Pod-side Hugging Face access is anonymous, read-only, and revision-pinned to
  `e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc`. Do not log in or forward a token.
- Commissioning may be repaired in place. After it succeeds, freeze source,
  archive, image/runtime, dependencies, model/tokenizer and recipe identities;
  the formal start and formal resume each use a fresh OS process, and the formal
  start uses a new output/checkpoint directory with no training state copied
  from commissioning.
- A stopped Pod must not be started or replaced merely because local readiness
  is green. Immediately re-read the external policy and refresh live candidate
  stock, price, storage rate, task/account billing and cleanup projection. The
  policy and existing task authorization are the only budget authority; do not
  introduce a second hard-coded cap or paid-runtime window.
- On the Pod, the canonical task root is a persistent `/workspace/...`
  directory. The verified bundle, model, venv, caches, commissioning/formal
  outputs, checkpoint, dependency identity/freeze and frozen recipe must all
  resolve below that one root; launcher and entrypoint reject any other path.

## Stage A: free local readiness

1. Run the focused unit tests and prepare the portable bundle directory using
   the Plan 060 CLI. The preparation gate re-verifies the Plan 054 freeze, the
   Plan 059 manifest and four source files, the public v7 validator, and the
   fixed train-only bundle hash.
2. Create a deterministic archive from only the bundle manifest's file set.
   Record its byte size and SHA-256, unpack it into a new local directory, and
   run the same portable verifier there with `python -B -P -m ...`. Reject symlinks, devices, unknown
   files, absolute paths and parent traversal.
3. Record a body-free readiness receipt: client version; balance; account and
   task spend; exact task resource reconciliation; both H100 candidates' live
   stock and price; candidate data-center Standard-volume support/rate;
   image/runtime candidate; disk sizes; conservative migration, training and
   cleanup cost; and effective policy hash/value with derived cutoffs. Do not
   create or start if any required fact is absent, more than one task GPU would
   run, or the conservative cost exceeds the effective cap.
4. Save the exact pre-selection source identity, baseline balance and each
   unique candidate attempt name in a mode-0600 controller state file. These
   runtime identifiers are provider evidence, not training identity.

## Stage B: asset placement, winner selection and commissioning

Reconcile the stopped source before any write and keep it until its required
assets are hash-verified on a Standard network volume. It may run only for
bounded transfer/recovery and must be stopped again before a candidate GPU Pod
starts. Create no more than two 60 GB Standard volumes; verify each returned
ID, tier, size and data center, and never attach a candidate to a volume in a
different data center.

On every pre-lock selection cycle, reload the budget policy, refresh both
candidate observations and apply the fixed stock order and PCIe tie-break. For
each intended candidate attempt, freeze a unique name, query that exact name,
and issue at most one create request. If create times out, reconcile that exact
name rather than duplicating it. Capacity failure may move to the next ranked
candidate; a stable request, billing or identity failure fails closed.

Verify a RUNNING candidate's exact ID/name, GPU model/count/memory, Secure
cloud, image, CUDA, data center, attached Standard volume and price against the
same observation. Then create the winner lock exclusively. Its training-facing
identity selects the winning GPU model; live price, effective budget, Pod
ID/name and data center remain separate provider evidence. Once locked, never
switch models because of a commissioning or training result. A later lost or
unusable compute Pod may be replaced only by the same winning model attached
to the same winner volume, after enforcing the one-running-GPU invariant.

Use `runpodctl ssh info <pod-id>` only as an ephemeral input. Do not print or
save its raw output because it can contain a private-key path. Use
`IdentitiesOnly=yes`, a task-local mode-0600 `controller/known_hosts`, and
`StrictHostKeyChecking=accept-new`. Refresh host/port after any restart.

Upload the single archive to the selected network-volume task root. Compare
host and Pod SHA-256 values, unpack into a new directory, and run the same
bundle verifier before any model download. Reuse hash-verified assets migrated
from the old source or built on an earlier candidate; do not copy
commissioning/formal training state across runs. On the winner Pod:

The controller-side winner-lock authority remains a regular mode-0600 file.
RunPod Standard volumes may normalize the uploaded remote replica's reported
POSIX mode (observed as 0666 even after `chmod 0600`). Before every training
launch, compare that replica's SHA-256 with the controller authority. The
runner opens it no-follow and requires a bounded stable regular file, strict
schema/selected-GPU identity and exact byte hash in receipts; do not weaken the
controller-side 0600 lock or substitute a different remote JSON.

1. verify Torch/CUDA/Triton and install exact dependencies without changing
   Torch; install the exact `flashoptim==0.1.4` wheel with `--no-deps`, verify
   its wheel hash, then run `pip check`;
2. unset all HF token variables and use `hf download` with the exact repository
   and revision; verify the locked model/tokenizer file set and hashes;
3. record the complete dependency/runtime identity and a private package
   freeze;
4. before any objective/update, require the runner's global FlashAdamW
   numerics preflight to recompute cached parameter stats and validate the
   configured LR against every optimizer parameter. If it fails, recover the
   aggregate required power-of-two candidate, stop compute and repair locally;
   do not repeat per-parameter paid discovery or disable `check_numerics`;
5. launch commissioning detached, with a task-only Triton cache and log/PID/
   status files; execute C1, C2 and C3, save a full checkpoint, terminate the
   original process, then launch a new process which restores and performs one
   further C3 update.

Use `runpod-launch.sh` for bootstrap and every training phase. Give every
attempt a new `RONDO_PLAN060_LAUNCH_NAME`; it writes task-local PID/log/status
paths and refuses to overwrite an earlier attempt. Bootstrap and training
status files are written atomically by their owning script. Do not assemble a
new ad-hoc `nohup` wrapper while the GPU is billing.

Commissioning receipts and any superseded attempts remain diagnostic. Preserve
verified model, environment and download/JIT caches on the winner volume and
begin repairs at the first unpassed seam.

## Stage C: clean formal run

After commissioning passes, freeze the exact source/archive hashes, dependency
identity, image/runtime, model/tokenizer identity, selected GPU model/winner
lock and final recipe. No code, package, image or recipe changes are allowed
after this point. Runtime price, effective budget, Pod ID/name and data center
remain provider facts outside that training identity.

Write a fresh complete `pip freeze --all` file, then create the formal
dependency identity with the package CLI's `capture-dependencies --status
formal_frozen --complete-freeze <file>` command. Formal start and resume must
receive both files; the runner re-hashes the complete freeze and compares the
live critical package/runtime identity. Copy the converged recipe into a new
formal-frozen path and record its SHA-256 rather than mutating the archived
commissioning recipe in place.

Every direct package CLI invocation, including unpack verification, dependency
capture and finalization, uses `python -B -P -m
rondo_eval.publication_critic.full_model_training ...`. `-B` prevents strict
bundle verification from being invalidated by generated bytecode; `-P` prevents
the operator's current directory from shadowing the verified package.

Create a new formal run directory and assert it does not exist. In a fresh
process, start from the exact base model and execute the complete C1 -> C2 -> C3
sequence. Save the full BF16 model, compressed FlashAdamW state, scheduler,
RNG, progress/cursor and identity. The start process must exit. In another
fresh process, restore the exact checkpoint and perform one more real C3
update. Finalization must reject equal start/resume process identities, missing
optimizer state, parameter-set mismatch, non-finite/non-positive update facts,
or a receipt that lacks all stage consumption.

The formal receipt is pending until the controller adds actual provider facts.
It must record process identities, steps, supervision consumption, loss and
gradient/update evidence, optimizer coverage/state, peak VRAM, token and sample
throughput, cold/JIT and steady timings, save/reload/continue timings,
checkpoint bytes/hash, disk peak and the frozen identities. A commissioning
receipt cannot be renamed or copied into the formal directory.

After compute termination and settled billing for deleted resources, run the
local package command `finalize-formal --budget-policy <path>` with the recovered
formal start/pending receipts and one sanitized provider-terminal facts JSON.
The finalizer binds
their hashes plus the effective policy value/file SHA-256, requires every task
compute Pod terminated, zero running compute rate, no loser or superseded task
volume, exactly one verified retained winner volume, its ongoing Standard
storage rate, and settled compute/deleted-resource cost no greater than that
policy cap. It combines the measured formal step/token rates with explicit
M3-B1c update-range, retry, overhead and storage assumptions. It emits low,
mid and conservative GPU-hour/cost estimates, remaining-hour/update capacity
and risk margin; `GO_RECOMMENDED` is rejected when the conservative estimate
does not fit `23 - actual_plan060_cost`.
Provider facts separately bind the controller-recorded source, candidate,
winner and any same-model replacement identities, their actual billing windows,
and the retained winner volume. No live ID, location, price or budget value is
copied into the static cloud candidate or used to redefine training identity.

Launch each phase through `runpod-launch.sh` with a unique
`RONDO_PLAN060_LAUNCH_NAME`; never invoke the training entrypoint in a separate
ad-hoc detached shell. The launcher starts exactly one
`runpod-training-entrypoint.sh` process in one of four legal modes:
`commission-start`, `commission-resume`, `formal-start`, or `formal-resume`.

## Monitoring, budget and recovery

At every phase transition and at least every five minutes while work is active,
append one timestamped, body-free line to the local monitor JSONL containing
the reconciled source/candidate/winner/replacement identities and status,
running-GPU count, task volume set, current task billing, account current spend,
remote phase/status, elapsed time, effective policy hash/value, derived cutoffs
and budget decision. Reload the policy before each sample. Query billing for
every task Pod and volume over its actual lifecycle window. Treat balance delta
only as a cross-check; provider billing for compute, deleted resources and the
retained winner-volume rate is authoritative.

Recover only the explicit small-file allowlist: bundle/identity manifests and
hashes, recipe/dependency/runtime facts, status, logs, receipts, billing facts
and aggregate resource measurements. Never recursively copy the formal output
or download a full checkpoint. After the new-process continuation is proved,
delete its remote full checkpoint when it is not part of the explicitly retained
reusable asset set; keep the verified base model, environment, caches and small
identity evidence on the winner volume.

## Stage D: finally-style cleanup

For GO-candidate, route failure, platform failure, timeout or interruption:

1. stop new training launches and recover the small evidence that is available;
2. re-read controller state and live provider facts, and require the exact saved
   identity for every source, candidate, winner, replacement and task volume
   before any stop, terminate or delete;
3. terminate every task compute Pod, including the old local-volume source and
   superseded same-model compute, only after required source assets are verified
   on the winner volume;
4. retain exactly the verified 60 GB Standard winner volume, delete loser or
   superseded task volumes, and never touch a volume outside the recorded task
   set;
5. query until no task compute remains, no GPU/CPU rate is active, and the sole
   retained task object is the winner volume; record its current storage rate
   and account current spend relative to baseline;
6. poll compute and deleted-resource billing until stable, record the retained
   volume's continuing cost, and write the final cost receipt.

Stopping a compute Pod is not cleanup. Retaining the one winner volume is an
intentional terminal asset, not zero-cost state; any extra Pod/volume, compute
rate, missing retained-volume rate or billing uncertainty yields
`BLOCKED/INCONCLUSIVE`, not GO or technical NO-GO. Only a completed formal run
plus this terminal resource policy can be recommended for GO; a principled
training-route failure after successful infrastructure convergence may be
recommended for NO-GO. Independent acceptance owns the final decision.
