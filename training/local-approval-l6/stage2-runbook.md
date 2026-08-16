# Plan 037 stage-2 RunPod runbook

This is an operator runbook, not stage-2 authorization. Section A is local and
read-only. Sections B-J create, use, bill, upload to, or delete remote objects
and must not be run until the user separately approves stage 2. Replace every
`<PLACEHOLDER>` from live control-plane output; never paste a secret into this
file, a receipt, shell history, or a process argument. Do not read or source
`.env.local`.

The default is exactly one on-demand Secure Cloud `NVIDIA A40` Pod. The only
fallback is `NVIDIA RTX A6000`, and only when its live Secure price is at most
`$0.60/h`. Both have 48 GB VRAM. The Pod uses the frozen image
`runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`, 40 GB container disk and a
100 GB Pod volume mounted at `/workspace`. Do not create a template, registry
credential or network volume.

## A. Before authorization: local read-only gates

Run from the Plan 037 worktree. These commands do not create a remote object.

```bash
set -euo pipefail
TASK_WORKTREE=/home/sjc/desktop/RONDO/.claude/worktrees/037-l6-first-lora-paired-artifacts
TASK_STAGE1=/home/sjc/desktop/RONDO/eval-data/local-approval/l6/plan037-stage1
TASK_BUNDLE="$TASK_STAGE1/train-only-bundle"
TASK_BUNDLE_TAR="$TASK_STAGE1/train-only-bundle.tar"
TASK_CENSUS="$TASK_STAGE1/token-census.json"

cd "$TASK_WORKTREE"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=eval python3 -B -m unittest -v \
  eval.tests.test_l6_training
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=eval python3 -B \
  -m rondo_eval.local_approval.l6_training verify-bundle \
  --bundle "$TASK_BUNDLE"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=eval python3 -B \
  -m rondo_eval.local_approval.l6_training mock-dry-run \
  --repo . --records 6
bash -n training/local-approval-l6/runpod-stage2-entrypoint.sh
git diff --check -- eval/rondo_eval/local_approval/l6_training.py \
  eval/tests/test_l6_training.py training/local-approval-l6

TASK_BUNDLE_SHA256="$(sha256sum "$TASK_BUNDLE_TAR" | cut -d' ' -f1)"
TASK_CENSUS_SHA256="$(sha256sum "$TASK_CENSUS" | cut -d' ' -f1)"
printf 'bundle_tar_sha256=%s\ncensus_sha256=%s\n' \
  "$TASK_BUNDLE_SHA256" "$TASK_CENSUS_SHA256"
```

Confirm the census still says 470 records, limit 4096, over-limit 0, total
145360, prompt 128545 and completion 16815. Record the printed hashes in the
stage-2 controller notes. Do not continue without separate authorization for
the Pod, bundle transfer, official model download, compute budget and any
optional private HF mirror.

## B. After authorization: select and create the one Pod

On the local control-plane shell, first verify the CLI, balance, zero unrelated
spend and live GPU facts. `runpodctl config` is intentionally absent: use an
already configured task-safe client, and never put an API key in these commands.

```bash
set -euo pipefail
runpodctl version
runpodctl user
runpodctl pod list --all
runpodctl gpu list

TASK_GPU_ID="NVIDIA A40"
TASK_GPU_RATE_USD='<LIVE_SECURE_A40_USD_PER_HOUR>'
# Only if Secure A40 is unavailable:
# TASK_GPU_ID="NVIDIA RTX A6000"
# TASK_GPU_RATE_USD='<LIVE_SECURE_A6000_USD_PER_HOUR>'

python3 - "$TASK_GPU_RATE_USD" <<'PY'
from decimal import Decimal
import sys
rate = Decimal(sys.argv[1])
if rate <= 0 or rate > Decimal("0.60"):
    raise SystemExit("refuse: selected Secure GPU exceeds $0.60/h")
PY

TASK_START_UTC="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
TASK_START_BALANCE_USD='<CLIENT_BALANCE_FROM_RUNPODCTL_USER>'
TASK_POD_NAME="rondo-l6-plan037-<UTC_COMPACT>"
TASK_IMAGE="runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404"
TASK_TERMINATE_UTC="$(date -u -d '+10 hours' +%Y-%m-%dT%H:%M:%SZ)"

TASK_CREATE_JSON="$(runpodctl pod create \
  --name "$TASK_POD_NAME" \
  --gpu-id "$TASK_GPU_ID" \
  --gpu-count 1 \
  --compute-type GPU \
  --cloud-type SECURE \
  --image "$TASK_IMAGE" \
  --container-disk-in-gb 40 \
  --volume-in-gb 100 \
  --volume-mount-path /workspace \
  --ports '22/tcp' \
  --ssh \
  --min-cuda-version 12.8 \
  --terminate-after "$TASK_TERMINATE_UTC" \
  --wait \
  --wait-timeout 30m)"
printf '%s\n' "$TASK_CREATE_JSON"
TASK_POD_ID="$(printf '%s\n' "$TASK_CREATE_JSON" | jq -er .id)"
runpodctl pod get "$TASK_POD_ID"
runpodctl pod list
```

Fail closed unless the returned object is the named single-GPU Secure Pod, has
the selected GPU, image, 40/100 GB disks, `/workspace`, SSH and a live rate no
higher than `$0.60/h`. Keep `TASK_POD_ID`, `TASK_START_UTC`, start balance and
rate in the controller shell. Do not create a second Pod.
A wait timeout does not prove that creation failed: do not retry `create`.
Locate the exact `TASK_POD_NAME` with `pod list`/`pod get`, then either continue
with that one Pod or explicitly delete it under the same cost controls.

## C. Establish SSH and transfer only the verified bundle

Full SSH over the exposed TCP port is required for SCP. Obtain the connection
facts from the control plane, then fill the placeholders without committing
them.

```bash
runpodctl ssh info "$TASK_POD_ID"
TASK_SSH_HOST='<PUBLIC_IP_FROM_SSH_INFO>'
TASK_SSH_PORT='<MAPPED_TCP_22_PORT_FROM_SSH_INFO>'
TASK_SSH_KEY='<LOCAL_PRIVATE_SSH_KEY_PATH>'

ssh -o IdentitiesOnly=yes -i "$TASK_SSH_KEY" \
  -p "$TASK_SSH_PORT" root@"$TASK_SSH_HOST" \
  'install -d -m 700 /workspace/rondo-l6/incoming /workspace/rondo-l6/runs /workspace/rondo-l6/controller-logs /workspace/rondo-l6/contracts'
scp -o IdentitiesOnly=yes -i "$TASK_SSH_KEY" \
  -P "$TASK_SSH_PORT" "$TASK_BUNDLE_TAR" \
  root@"$TASK_SSH_HOST":/workspace/rondo-l6/incoming/train-only-bundle.tar
```

In the remote SSH shell, verify the exact local tar hash before extraction and
then use the bundled verifier. No other dataset file may be transferred.

```bash
set -euo pipefail
TASK_ROOT=/workspace/rondo-l6
TASK_BUNDLE="$TASK_ROOT/train-only-bundle"
TASK_EXPECTED_BUNDLE_SHA256='<TASK_BUNDLE_SHA256_FROM_SECTION_A>'
test "$(sha256sum "$TASK_ROOT/incoming/train-only-bundle.tar" | cut -d' ' -f1)" \
  = "$TASK_EXPECTED_BUNDLE_SHA256"
tar -xf "$TASK_ROOT/incoming/train-only-bundle.tar" -C "$TASK_ROOT"
python3 "$TASK_BUNDLE/bin/l6_training.py" verify-bundle --bundle "$TASK_BUNDLE"
```

## D. Download the frozen official revision and install exact dependencies

Still in the remote shell, type the HF read token with the shell `read` builtin:
silent input does not enter shell history or a process argument, and the value
is unset immediately after download. Do not call `hf auth token`, and do not use
HF Jobs, Endpoints or Spaces. Download only the four indexed BF16 shards and
the exact config/tokenizer files by immutable commit into the Pod-volume Hub
cache. This intentionally omits the duplicate consolidated weight file; the
training loader uses the same `HF_HOME`, fixed revision and offline mode.

```bash
set -euo pipefail
TASK_ROOT=/workspace/rondo-l6
TASK_BUNDLE="$TASK_ROOT/train-only-bundle"
export HF_HOME="$TASK_ROOT/hf-home"
export PIP_CACHE_DIR="$TASK_ROOT/pip-cache"
install -d -m 700 "$HF_HOME" "$PIP_CACHE_DIR"
read -rsp 'HF read token: ' HF_TOKEN
printf '\n'
export HF_TOKEN
hf auth whoami
TASK_DOWNLOAD_LOG="$TASK_ROOT/controller-logs/model-download.log"
hf download mistralai/Ministral-3-8B-Instruct-2512-BF16 \
  config.json \
  params.json \
  model.safetensors.index.json \
  model-00001-of-00004.safetensors \
  model-00002-of-00004.safetensors \
  model-00003-of-00004.safetensors \
  model-00004-of-00004.safetensors \
  tokenizer.json \
  tokenizer_config.json \
  special_tokens_map.json \
  --revision f6fae9795746f63c9be8344932f01275f3c63734 \
  --cache-dir "$HF_HOME/hub" 2>&1 | tee "$TASK_DOWNLOAD_LOG"
unset HF_TOKEN
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1

python3 -m venv --system-site-packages "$TASK_ROOT/venv"
. "$TASK_ROOT/venv/bin/activate"
python -m pip install -r "$TASK_BUNDLE/contracts/dependencies-candidate-v1.txt"
python -m pip check
python - <<'PY'
import importlib.metadata as m
import platform
import torch
names = ("torch", "transformers", "peft", "trl", "accelerate", "bitsandbytes", "safetensors")
print({name: m.version(name) for name in names})
print({"python": platform.python_version(), "cuda": torch.version.cuda})
assert torch.cuda.is_available()
PY
nvidia-smi
```

Stop immediately on a missing file, dependency conflict, CUDA mismatch or a
GPU other than the approved 48 GB device. Keep `HF_TOKEN` only in the remote
process environment and unset it after the official download if no optional HF
mirror is authorized.

## E. Run the one-step optimizer smoke and isolated reload

The remote environment below is complete. The entrypoint runs only `smoke`,
forces exactly one optimizer step, writes the selected attempt's `/smoke`
subdirectory, and reloads the adapter in a separate process. Controller logs
stay outside artifact output. It never launches formal training.

```bash
set -euo pipefail
TASK_ROOT=/workspace/rondo-l6
TASK_ATTEMPT_ID=attempt-01
TASK_ATTEMPT_ROOT="$TASK_ROOT/runs/$TASK_ATTEMPT_ID"
TASK_CONTROLLER_LOG_ROOT="$TASK_ROOT/controller-logs/$TASK_ATTEMPT_ID"
install -d -m 700 "$TASK_ATTEMPT_ROOT" "$TASK_CONTROLLER_LOG_ROOT"
. "$TASK_ROOT/venv/bin/activate"
export HF_HOME="$TASK_ROOT/hf-home"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export RONDO_L6_BUNDLE="$TASK_ROOT/train-only-bundle"
export RONDO_L6_OUTPUT="$TASK_ATTEMPT_ROOT"
export RONDO_L6_RUN_ID="$TASK_ATTEMPT_ID-smoke-<UTC_COMPACT>"
export RONDO_L6_POD_ID='<TASK_POD_ID>'
export RONDO_L6_GPU='<NVIDIA_A40_OR_NVIDIA_RTX_A6000>'
export RONDO_L6_RUN_KIND=smoke
export RONDO_L6_MAX_SECONDS=1800
unset RONDO_L6_FINAL_RECIPE RONDO_L6_DEPENDENCY_IDENTITY RONDO_L6_RESUME_CHECKPOINT
bash "$RONDO_L6_BUNDLE/bin/runpod-stage2-entrypoint.sh" \
  2>&1 | tee "$TASK_CONTROLLER_LOG_ROOT/smoke.log"

jq -e '.status == "pending_adapter_reload_and_finalize" and .metrics.global_step == 1' \
  "$TASK_ATTEMPT_ROOT/smoke/training-pending.json"
jq -e '.status == "adapter_reloaded" and .separate_command == true' \
  "$TASK_ATTEMPT_ROOT/smoke/adapter-reload-receipt.json"
test ! -e "$TASK_ATTEMPT_ROOT/smoke/training-receipt.json"
```

Stop here for human/agent review. The local mock is not this evidence. An OOM,
wrong target module, zero/extra optimizer steps, reload failure or missing
receipt is a failed smoke and must not be converted into formal success.

## F. Converge once and freeze the formal contracts

Only fields named by `smoke_adjustable_once` may change. Packing remains false,
quantization and the fixed PEFT target regex cannot change. The following
starts from the bundled candidate recipe, not smoke's forced one-step actual
recipe, and freezes the smoke-observed dependency identity. Make any
evidence-backed allowed edit inside the marked Python block before writing the
attempt-specific files; the formal entrypoint resolves the contract before
optimizer work begins.

```bash
set -euo pipefail
TASK_ROOT=/workspace/rondo-l6
TASK_ATTEMPT_ID=attempt-01
python3 - "$TASK_ROOT" "$TASK_ATTEMPT_ID" <<'PY'
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
attempt = sys.argv[2]
bundle = root / "train-only-bundle"
smoke = root / "runs" / attempt / "smoke"
contracts = root / "contracts" / attempt
contracts.mkdir(mode=0o700, parents=True, exist_ok=False)
recipe = json.loads(
    (bundle / "contracts/recipe-candidate-v1.json").read_text()
)
dependency = json.loads((smoke / "dependency-identity.json").read_text())
recipe["candidate_status"] = "stage2_final_frozen"
# At most one evidence-backed convergence may edit only smoke_adjustable_once.
dependency["status"] = "stage2_final_frozen"
(contracts / "final-recipe.json").write_text(
    json.dumps(recipe, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
)
(contracts / "dependency-identity.json").write_text(
    json.dumps(dependency, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
)
PY
chmod 600 "$TASK_ROOT/contracts/$TASK_ATTEMPT_ID/final-recipe.json" \
  "$TASK_ROOT/contracts/$TASK_ATTEMPT_ID/dependency-identity.json"
sha256sum "$TASK_ROOT/contracts/$TASK_ATTEMPT_ID/final-recipe.json" \
  "$TASK_ROOT/contracts/$TASK_ATTEMPT_ID/dependency-identity.json"
```

## G. Run formal training or resume one matching checkpoint

Use a new formal output. Do not reuse the smoke output. On a fresh formal run,
leave `RONDO_L6_RESUME_CHECKPOINT` unset:

```bash
set -euo pipefail
TASK_ROOT=/workspace/rondo-l6
TASK_ATTEMPT_ID=attempt-01
TASK_ATTEMPT_ROOT="$TASK_ROOT/runs/$TASK_ATTEMPT_ID"
TASK_CONTROLLER_LOG_ROOT="$TASK_ROOT/controller-logs/$TASK_ATTEMPT_ID"
. "$TASK_ROOT/venv/bin/activate"
export HF_HOME="$TASK_ROOT/hf-home"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export RONDO_L6_BUNDLE="$TASK_ROOT/train-only-bundle"
export RONDO_L6_OUTPUT="$TASK_ATTEMPT_ROOT"
export RONDO_L6_RUN_ID="$TASK_ATTEMPT_ID-formal-<UTC_COMPACT>"
export RONDO_L6_POD_ID='<TASK_POD_ID>'
export RONDO_L6_GPU='<NVIDIA_A40_OR_NVIDIA_RTX_A6000>'
export RONDO_L6_RUN_KIND=formal
export RONDO_L6_FINAL_RECIPE="$TASK_ROOT/contracts/$TASK_ATTEMPT_ID/final-recipe.json"
export RONDO_L6_DEPENDENCY_IDENTITY="$TASK_ROOT/contracts/$TASK_ATTEMPT_ID/dependency-identity.json"
export RONDO_L6_MAX_SECONDS=10800
unset RONDO_L6_RESUME_CHECKPOINT
bash "$RONDO_L6_BUNDLE/bin/runpod-stage2-entrypoint.sh" \
  2>&1 | tee "$TASK_CONTROLLER_LOG_ROOT/formal.log"
```

If the process was interrupted after a valid checkpoint was written, keep the
same run ID, recipe, dependency identity, hardware and output root. Resume only
one direct child matching `checkpoint-N`; the CLI rejects all outside paths,
symlinks, changed contracts and outputs that already reached pending/reload:

```bash
export RONDO_L6_RUN_ID='<ORIGINAL_FORMAL_RUN_ID>'
export RONDO_L6_RESUME_CHECKPOINT='/workspace/rondo-l6/runs/attempt-01/formal/checkpoints/checkpoint-<N>'
bash "$RONDO_L6_BUNDLE/bin/runpod-stage2-entrypoint.sh" \
  2>&1 | tee -a "$TASK_CONTROLLER_LOG_ROOT/formal-resume.log"
```

If `training-pending.json` already exists, training and adapter saving finished;
do **not** invoke the entrypoint or resume a checkpoint. Continue the interrupted
state transition on the same output. Run the isolated reload only when its
receipt is absent, validate both receipts, then continue with H to finalize:

```bash
set -euo pipefail
TASK_FORMAL_OUTPUT="$TASK_ATTEMPT_ROOT/formal"
test -f "$TASK_FORMAL_OUTPUT/training-pending.json"
test ! -e "$TASK_FORMAL_OUTPUT/training-receipt.json"
if test ! -e "$TASK_FORMAL_OUTPUT/adapter-reload-receipt.json"; then
  python3 "$RONDO_L6_BUNDLE/bin/l6_training.py" reload-adapter \
    --bundle "$RONDO_L6_BUNDLE" \
    --output "$TASK_FORMAL_OUTPUT"
fi
jq -e '.status == "pending_adapter_reload_and_finalize"' \
  "$TASK_FORMAL_OUTPUT/training-pending.json"
jq -e '.status == "adapter_reloaded" and .separate_command == true' \
  "$TASK_FORMAL_OUTPUT/adapter-reload-receipt.json"
```

`reload-adapter` and `finalize-receipt` rehash the recipe, dependencies,
adapter and pending receipt. Any drift fails closed; it is not permission to
restart formal training on that completed output.

Never resume a different run contract merely because its files fit. If failure
occurs before a valid checkpoint exists, do not reuse the partial output:
select `attempt-02`, repeat E-F-G with a fresh attempt output, controller-log
directory and contract directory, and preserve the already converged recipe
values (the one-time technical convergence cannot be repeated). A valid
checkpoint is the only case that resumes the original attempt.

## H. Control cost, finalize receipts and verify remote artifacts

Run cost control concurrently from the local control-plane shell. Query the Pod
and account at least every five minutes and after every phase transition:

```bash
runpodctl pod get "$TASK_POD_ID"
runpodctl user
runpodctl billing pods --bucket-size hour --start-time "$TASK_START_UTC" \
  --grouping podId --pod-id "$TASK_POD_ID"
TASK_CURRENT_BALANCE_USD='<CURRENT_CLIENT_BALANCE_FROM_RUNPODCTL_USER>'
python3 - "$TASK_START_BALANCE_USD" "$TASK_CURRENT_BALANCE_USD" <<'PY'
from decimal import Decimal
import sys
spent = Decimal(sys.argv[1]) - Decimal(sys.argv[2])
print(f"task_spend_usd={spent:.6f}")
PY
```

Compute cumulative task spend as start balance minus current balance, including
storage. The control decisions are mandatory:

- `$8`: soft stop. Start no new phase or retry. If no critical write is active,
  stop the Pod and begin recovery review.
- `$10` hard recovery line: `runpodctl pod stop "$TASK_POD_ID"` immediately.
  A single short restart is allowed only to recover `/workspace`, with the `$2`
  reserve and the same user authorization.
- `$12` cap: `runpodctl pod delete "$TASK_POD_ID"`; no retry.
- 10 hours since creation: forced deletion. The RFC3339
  `TASK_TERMINATE_UTC` passed to `--terminate-after` is the independent
  control-plane backstop; the controller also deletes explicitly.

If that one recovery restart is needed, do not reuse the old SSH address. Start
the same stopped Pod, wait for it to become ready, then obtain the current host
and port:

```bash
runpodctl pod start "$TASK_POD_ID"
runpodctl pod get "$TASK_POD_ID"
runpodctl ssh info "$TASK_POD_ID"
export TASK_SSH_HOST='<CURRENT_SSH_HOST_FROM_SSH_INFO>'
export TASK_SSH_PORT='<CURRENT_SSH_PORT_FROM_SSH_INFO>'
ssh -o IdentitiesOnly=yes -i "$TASK_SSH_KEY" \
  -p "$TASK_SSH_PORT" root@"$TASK_SSH_HOST"
```

In that new remote shell, inspect the existing formal output before choosing
the recovery branch. A
completed receipt may proceed to remote `verify-artifacts` and I. A pending
receipt must complete the reload/finalize transition described above, using the
existing environment and without invoking `train` or the entrypoint:

```bash
set -euo pipefail
TASK_ROOT=/workspace/rondo-l6
TASK_POD_ID='<TASK_POD_ID_FROM_CONTROLLER>'
TASK_ATTEMPT_ID=attempt-01
TASK_ATTEMPT_ROOT="$TASK_ROOT/runs/$TASK_ATTEMPT_ID"
TASK_FORMAL_OUTPUT="$TASK_ATTEMPT_ROOT/formal"
RONDO_L6_BUNDLE="$TASK_ROOT/train-only-bundle"
if test -f "$TASK_FORMAL_OUTPUT/training-receipt.json"; then
  : # completed branch; verify below, then recover with I
elif test -f "$TASK_FORMAL_OUTPUT/training-pending.json"; then
  . "$TASK_ROOT/venv/bin/activate"
  export HF_HOME="$TASK_ROOT/hf-home"
  export HF_HUB_OFFLINE=1
  export TRANSFORMERS_OFFLINE=1
  if test ! -f "$TASK_FORMAL_OUTPUT/adapter-reload-receipt.json"; then
    python3 "$RONDO_L6_BUNDLE/bin/l6_training.py" reload-adapter \
      --bundle "$RONDO_L6_BUNDLE" --output "$TASK_FORMAL_OUTPUT"
  fi
  TASK_ACTUAL_COST_USD='<ACTUAL_CUMULATIVE_RUNPOD_COST_USD_AFTER_RELOAD>'
  python3 "$RONDO_L6_BUNDLE/bin/l6_training.py" finalize-receipt \
    --bundle "$RONDO_L6_BUNDLE" --output "$TASK_FORMAL_OUTPUT" \
    --actual-runpod-cost-usd "$TASK_ACTUAL_COST_USD" \
    --persistence-kind pod_volume \
    --persistence-revision "pod:$TASK_POD_ID:$TASK_FORMAL_OUTPUT"
else
  echo 'recovery_missing_pending_or_completed_receipt' >&2
  exit 1
fi
python3 "$RONDO_L6_BUNDLE/bin/l6_training.py" verify-artifacts \
  --bundle "$RONDO_L6_BUNDLE" --output "$TASK_FORMAL_OUTPUT"
```

The controller continues polling spend during recovery and deletes at the
`$12` cap or 10-hour deadline.

After each successful reload, obtain actual cumulative RunPod cost from the
controller and finalize. Use a concrete persistence revision. For the live Pod
volume it can bind Pod ID plus absolute output path; after local recovery use
the downloaded artifact-manifest hash instead.

```bash
set -euo pipefail
TASK_ROOT=/workspace/rondo-l6
TASK_ATTEMPT_ID=attempt-01
TASK_ATTEMPT_ROOT="$TASK_ROOT/runs/$TASK_ATTEMPT_ID"
TASK_ACTUAL_COST_USD='<ACTUAL_CUMULATIVE_RUNPOD_COST_USD>'
python3 "$TASK_ROOT/train-only-bundle/bin/l6_training.py" finalize-receipt \
  --bundle "$TASK_ROOT/train-only-bundle" \
  --output "$TASK_ATTEMPT_ROOT/formal" \
  --actual-runpod-cost-usd "$TASK_ACTUAL_COST_USD" \
  --persistence-kind pod_volume \
  --persistence-revision "pod:<TASK_POD_ID>:$TASK_ATTEMPT_ROOT/formal"
python3 "$TASK_ROOT/train-only-bundle/bin/l6_training.py" verify-artifacts \
  --bundle "$TASK_ROOT/train-only-bundle" \
  --output "$TASK_ATTEMPT_ROOT/formal"
```

Finalization must leave a schema-valid `completed` receipt only after the
pending and reload receipts, actual cost, persistence identity and every
allowlisted artifact hash agree.

## I. SCP recovery, local verification, and optional private HF mirror

Recover the complete allowlisted formal output into a new ignored local
directory before Pod deletion:

```bash
set -euo pipefail
TASK_ATTEMPT_ID=attempt-01
TASK_LOCAL_RECOVERY='/home/sjc/desktop/RONDO/eval-data/local-approval/l6/plan037-stage2/<FORMAL_RUN_ID>'
test ! -e "$TASK_LOCAL_RECOVERY"
install -d -m 700 "$TASK_LOCAL_RECOVERY"
scp -r -o IdentitiesOnly=yes -i "$TASK_SSH_KEY" \
  -P "$TASK_SSH_PORT" \
  root@"$TASK_SSH_HOST":/workspace/rondo-l6/runs/"$TASK_ATTEMPT_ID"/formal/. \
  "$TASK_LOCAL_RECOVERY"/

cd "$TASK_WORKTREE"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=eval python3 -B \
  -m rondo_eval.local_approval.l6_training verify-artifacts \
  --bundle "$TASK_BUNDLE" --output "$TASK_LOCAL_RECOVERY"
sha256sum "$TASK_LOCAL_RECOVERY/artifact-manifest.json"
```

The optional private HF model mirror is a separate remote mutation and is
forbidden unless the user explicitly authorizes the named private repo and the
operator confirms it remains inside free private quota with `$0` incremental
HF cost. Never enable PRO, pay-as-you-go or another paid feature. Because
`verify-artifacts` rejects every non-allowlisted path, the verified recovery
directory may be uploaded as one commit only after that extra approval:

```bash
HF_MODEL_REPO='<AUTHORIZED_PRIVATE_NAMESPACE/REPO>'
hf repos create "$HF_MODEL_REPO" --type model --private
hf upload "$HF_MODEL_REPO" "$TASK_LOCAL_RECOVERY" . \
  --type model --revision main --private \
  --commit-message 'Plan 037 L6 verified artifacts'
```

Do not upload the bundle, train projection, any dataset, validation/holdout,
seed material or per-sample outputs. If quota or `$0` cost cannot be confirmed,
skip HF entirely and retain the locally verified copy.

## J. Delete the task Pod and confirm zero live objects

Only after local verification (and optional separately authorized HF mirror)
succeeds, delete the Pod. This permanently removes its Pod volume.

```bash
runpodctl pod delete "$TASK_POD_ID"
if runpodctl pod list --all | grep -F "$TASK_POD_ID"; then
  echo 'refuse completion: task Pod still listed' >&2
  exit 2
fi
runpodctl user
runpodctl billing pods --bucket-size hour --start-time "$TASK_START_UTC" \
  --grouping podId --pod-id "$TASK_POD_ID"
runpodctl network-volume list
```

Confirm no task template, registry credential or network volume was created,
current spend per hour returned to its pre-task value, final task cost did not
exceed `$12`, and the local artifact manifest still verifies. Record the final
billing result and deleted Pod ID in the stage-2 handoff without recording any
credential.

Official command references: [RunPod Pod CLI](https://docs.runpod.io/runpodctl/reference/runpodctl-pod),
[RunPod SSH](https://docs.runpod.io/pods/configuration/use-ssh),
[RunPod file transfer](https://docs.runpod.io/pods/storage/transfer-files),
[RunPod billing CLI](https://docs.runpod.io/runpodctl/reference/runpodctl-billing),
and [HF CLI download](https://huggingface.co/docs/huggingface_hub/guides/cli#hf-download).
