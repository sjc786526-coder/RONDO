# Plan 037 stage-2 RunPod runbook

This is an operator runbook, not remote authorization. Section A is the local
stage-2A preparation scope. Sections B-J create, use, bill, upload to, or delete
remote objects and must not be run until the user separately approves that
paid stage. Replace every
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
TASK_STAGE2A="$TASK_WORKTREE/eval-data/local-approval/l6/plan037-stage2a"
TASK_BUNDLE="$TASK_STAGE1/train-only-bundle"
TASK_BUNDLE_TAR="$TASK_STAGE1/train-only-bundle.tar"
TASK_CENSUS="$TASK_STAGE1/token-census.json"
TASK_CONVERSION_TOOL_BUNDLE="$TASK_STAGE2A/conversion-tool-bundle"
TASK_CONVERSION_TOOL_TAR="$TASK_STAGE2A/conversion-tool-bundle.tar"
TASK_CONVERSION_CONTRACT="$TASK_WORKTREE/training/local-approval-l6/conversion-tool-contract-v1.json"
TASK_LLAMA_SOURCE=/home/sjc/desktop/RONDO/eval-data/sources/llama.cpp-b10333-08659901
TASK_QUANTIZER_RUNTIME=/home/sjc/desktop/RONDO/eval-data/tools/llama-b10333
TASK_C_AVAILABLE_BYTES="$(df -B1 --output=avail /mnt/c | tail -n1 | tr -d ' ')"
# 80 GiB mandatory post-download floor plus a conservative 35 GiB local peak.
test "$TASK_C_AVAILABLE_BYTES" -ge 123480309760
printf 'windows_c_available_bytes=%s\n' "$TASK_C_AVAILABLE_BYTES"

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
if test ! -e "$TASK_CONVERSION_TOOL_BUNDLE"; then
  python3 -B training/local-approval-l6/conversion_tooling.py prepare \
    --contract "$TASK_CONVERSION_CONTRACT" \
    --source-root "$TASK_LLAMA_SOURCE" \
    --quantizer-root "$TASK_QUANTIZER_RUNTIME" \
    --output "$TASK_CONVERSION_TOOL_BUNDLE"
fi
python3 -B "$TASK_CONVERSION_TOOL_BUNDLE/bin/conversion_tooling.py" verify \
  --bundle "$TASK_CONVERSION_TOOL_BUNDLE"
if test ! -e "$TASK_CONVERSION_TOOL_TAR"; then
  tar --sort=name --mtime=@0 --owner=0 --group=0 --numeric-owner \
    -cf "$TASK_CONVERSION_TOOL_TAR" -C "$TASK_STAGE2A" conversion-tool-bundle
fi
TASK_TAR_VERIFY="$(mktemp -d /tmp/plan037-conversion-tar.XXXXXX)"
trap 'rm -rf -- "$TASK_TAR_VERIFY"' EXIT
tar -xf "$TASK_CONVERSION_TOOL_TAR" -C "$TASK_TAR_VERIFY"
python3 -B "$TASK_TAR_VERIFY/conversion-tool-bundle/bin/conversion_tooling.py" \
  verify --bundle "$TASK_TAR_VERIFY/conversion-tool-bundle"
cmp "$TASK_CONVERSION_CONTRACT" \
  "$TASK_TAR_VERIFY/conversion-tool-bundle/contracts/conversion-tool-contract-v1.json"
cmp "$TASK_CONVERSION_TOOL_BUNDLE/conversion-tool-bundle-manifest.json" \
  "$TASK_TAR_VERIFY/conversion-tool-bundle/conversion-tool-bundle-manifest.json"
rm -rf -- "$TASK_TAR_VERIFY"
trap - EXIT
git diff --check -- eval/rondo_eval/local_approval/l6_training.py \
  eval/tests/test_l6_training.py training/local-approval-l6

TASK_BUNDLE_SHA256="$(sha256sum "$TASK_BUNDLE_TAR" | cut -d' ' -f1)"
TASK_CENSUS_SHA256="$(sha256sum "$TASK_CENSUS" | cut -d' ' -f1)"
TASK_CONVERSION_TOOL_SHA256="$(sha256sum "$TASK_CONVERSION_TOOL_TAR" | cut -d' ' -f1)"
printf 'bundle_tar_sha256=%s\ncensus_sha256=%s\nconversion_tool_tar_sha256=%s\n' \
  "$TASK_BUNDLE_SHA256" "$TASK_CENSUS_SHA256" "$TASK_CONVERSION_TOOL_SHA256"
```

Confirm the census still says 470 records, limit 4096, over-limit 0, total
145360, prompt 128545 and completion 16815. Record the printed hashes in the
stage-2 controller notes. The conversion bundle is body-free: its generated
manifest is the exact upload allowlist, and its builder rejects source drift,
unknown package files, model/data bodies and unlisted symlinks. Do not continue
without separate authorization for the Pod, both bundle transfers, official
model download and compute budget. This run does not include a private HF
mirror.

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
scp -o IdentitiesOnly=yes -i "$TASK_SSH_KEY" \
  -P "$TASK_SSH_PORT" "$TASK_CONVERSION_TOOL_TAR" \
  root@"$TASK_SSH_HOST":/workspace/rondo-l6/incoming/conversion-tool-bundle.tar
```

In the remote SSH shell, verify the exact local tar hash before extraction and
then use the bundled verifier. No other dataset file may be transferred.

```bash
set -euo pipefail
TASK_ROOT=/workspace/rondo-l6
TASK_BUNDLE="$TASK_ROOT/train-only-bundle"
TASK_CONVERSION_TOOLS="$TASK_ROOT/conversion-tool-bundle"
TASK_EXPECTED_BUNDLE_SHA256='<TASK_BUNDLE_SHA256_FROM_SECTION_A>'
TASK_EXPECTED_CONVERSION_TOOL_SHA256='<TASK_CONVERSION_TOOL_SHA256_FROM_SECTION_A>'
test "$(sha256sum "$TASK_ROOT/incoming/train-only-bundle.tar" | cut -d' ' -f1)" \
  = "$TASK_EXPECTED_BUNDLE_SHA256"
test "$(sha256sum "$TASK_ROOT/incoming/conversion-tool-bundle.tar" | cut -d' ' -f1)" \
  = "$TASK_EXPECTED_CONVERSION_TOOL_SHA256"
tar -xf "$TASK_ROOT/incoming/train-only-bundle.tar" -C "$TASK_ROOT"
tar -xf "$TASK_ROOT/incoming/conversion-tool-bundle.tar" -C "$TASK_ROOT"
python3 "$TASK_BUNDLE/bin/l6_training.py" verify-bundle --bundle "$TASK_BUNDLE"
python3 "$TASK_CONVERSION_TOOLS/bin/conversion_tooling.py" verify \
  --bundle "$TASK_CONVERSION_TOOLS"
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

# Keep Transformers 4.57.6 isolated from the training venv's 5.14.1. The
# --system-site-packages link deliberately reuses image torch 2.8.0.
python3 -m venv --system-site-packages "$TASK_ROOT/conversion-venv"
. "$TASK_ROOT/conversion-venv/bin/activate"
python -m pip install \
  -r "$TASK_ROOT/conversion-tool-bundle/contracts/conversion-dependencies-v1.txt"
python -m pip check
python - <<'PY'
import importlib.metadata as metadata
import torch

expected = {
    "numpy": "1.26.4",
    "sentencepiece": "0.2.1",
    "transformers": "4.57.6",
    "protobuf": "4.25.8",
    "huggingface-hub": "0.36.0",
    "safetensors": "0.8.0",
    "tqdm": "4.67.3",
    "PyYAML": "6.0.3",
    "requests": "2.32.5",
}
actual = {name: metadata.version(name) for name in expected}
assert actual == expected, (actual, expected)
assert torch.__version__.split("+", 1)[0] == "2.8.0", torch.__version__
print({"conversion_dependencies": actual, "torch": torch.__version__})
PY
PYTHONPATH="$TASK_ROOT/conversion-tool-bundle/tools/llama.cpp/gguf-py" \
  python "$TASK_ROOT/conversion-tool-bundle/tools/llama.cpp/convert_hf_to_gguf.py" \
  --print-supported-models 2>&1 | grep -E 'Mistral3|Ministral3|mistral3'
ldd "$TASK_ROOT/conversion-tool-bundle/tools/llama-b10333-cpu/llama-quantize"
"$TASK_ROOT/conversion-tool-bundle/tools/llama-b10333-cpu/llama-quantize" \
  --help >/dev/null 2>&1 || test "$?" -eq 1
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

Stop here for the active executor's technical review. After the one paid-stage
authorization this is not another user approval gate. The local mock is not
this evidence. An OOM, wrong target module, zero/extra optimizer steps, reload
failure or missing receipt is a failed smoke and must not be converted into
formal success.

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

- `$8`: soft checkpoint, not automatic failure. Before starting another
  high-cost phase or retry, recompute its conservative completion and recovery
  cost. Continue the current critical write or necessary evidenced recovery
  only when that bound remains below `$12`; otherwise stop the Pod.
- `$10` hard recovery line: `runpodctl pod stop "$TASK_POD_ID"` immediately.
  Do not restart GPU computation; use the remaining reserve only for short
  artifact recovery and deletion.
- `$12` cap: `runpodctl pod delete "$TASK_POD_ID"`; no retry.
- 10 hours since creation: forced deletion. The RFC3339
  `TASK_TERMINATE_UTC` passed to `--terminate-after` is the independent
  control-plane backstop; the controller also deletes explicitly.

Conversion is deliberately deferred until the completed training receipt has been finalized, recovered locally and verified file by file. The deployment procedure is in I; a conversion failure cannot erase or downgrade completed training evidence.

After the paid-stage authorization, ordinary dependency, OOM, SSH, download,
conversion, checkpoint and model-load problems are owned by the active
executor: diagnose, make a narrow evidence-backed correction and continue
within the frozen contracts and budget without asking again. Pause only when
the conservative total would exceed `$12`, a new remote object or data class is
needed outside the authorized boundaries, a second valid training recipe is
required, or the frozen base, template, b10333 runtime or product route must
change.

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

## I. SCP recovery and local verification

Recover the complete allowlisted formal output into a new ignored local
directory before Pod deletion:

```bash
set -euo pipefail
TASK_ATTEMPT_ID=attempt-01
TASK_WORKTREE=/home/sjc/desktop/RONDO/.claude/worktrees/037-l6-first-lora-paired-artifacts
TASK_BUNDLE=/home/sjc/desktop/RONDO/eval-data/local-approval/l6/plan037-stage1/train-only-bundle
TASK_LOCAL_RECOVERY='/home/sjc/desktop/RONDO/eval-data/local-approval/l6/plan037-stage2/<FORMAL_RUN_ID>'
TASK_C_AVAILABLE_BYTES="$(df -B1 --output=avail /mnt/c | tail -n1 | tr -d ' ')"
# Fail before SCP unless the 35 GiB conservative local peak still leaves 80 GiB.
test "$TASK_C_AVAILABLE_BYTES" -ge 123480309760
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

Only after this local training-artifact verification may the remote deployment
conversion begin. It writes to the sibling
`/workspace/rondo-l6/deployments/<attempt>`, never under formal training output.
The completed receipt and adapter are read-only sources. Conversion failure
does not change completed training status.

Start with the preferred `adapter_on_off` route. This is the executor's
technical choice under the paid authorization, not a new user review:

- `adapter_on_off`: one Q4_K_M base plus one F16 LoRA GGUF; the fine-tuned side
  adds `--lora` to the same base.
- `paired_gguf`: the same base plus a separately merged and quantized Q4_K_M
  fine-tuned model; neither side uses `--lora`.

The frozen BF16 cache is exactly 17,836,052,480 bytes. A prior same-family
Q4_K_M artifact was 5,198,387,456 bytes, which is only a size estimate. Reserve
a conservative 60 GB total Pod-volume peak for `adapter_on_off` or 80 GB for
sequential `paired_gguf`; require 45/65 GB free respectively before starting
and 20 GB free at each transition. All weights stay on the 100 GB Pod volume,
not the 40 GB container disk.

```bash
set -euo pipefail
umask 077
TASK_ROOT=/workspace/rondo-l6
TASK_ATTEMPT_ID=attempt-01
TASK_FORMAL_OUTPUT="$TASK_ROOT/runs/$TASK_ATTEMPT_ID/formal"
TASK_ROUTE="${TASK_ROUTE:-adapter_on_off}"
TASK_CONVERSION_TOOLS="$TASK_ROOT/conversion-tool-bundle"
TASK_CONVERTER_ROOT="$TASK_CONVERSION_TOOLS/tools/llama.cpp"
TASK_QUANTIZER_ROOT="$TASK_CONVERSION_TOOLS/tools/llama-b10333-cpu"
case "$TASK_ROUTE" in
  adapter_on_off)
    TASK_ROUTE_ATTEMPT="${TASK_ROUTE_ATTEMPT:-adapter-on-off-01}"
    TASK_REQUIRED_FREE_GB=45
    ;;
  paired_gguf)
    TASK_ROUTE_ATTEMPT="${TASK_ROUTE_ATTEMPT:-paired-gguf-01}"
    TASK_REQUIRED_FREE_GB=65
    ;;
  *) echo 'conversion_route_invalid' >&2; exit 2 ;;
esac
TASK_DEPLOYMENT="$TASK_ROOT/deployments/$TASK_ATTEMPT_ID/$TASK_ROUTE_ATTEMPT"
test -f "$TASK_FORMAL_OUTPUT/training-receipt.json"
test "$(jq -r .status "$TASK_FORMAL_OUTPUT/training-receipt.json")" = completed
test ! -e "$TASK_DEPLOYMENT"
TASK_AVAILABLE_BYTES="$(df -B1 --output=avail /workspace | tail -n1 | tr -d ' ')"
test "$TASK_AVAILABLE_BYTES" -ge "$((TASK_REQUIRED_FREE_GB * 1000 * 1000 * 1000))"
install -d -m 700 "$TASK_DEPLOYMENT/tooling" "$TASK_DEPLOYMENT/work"
install -m 600 "$TASK_CONVERTER_ROOT/convert_hf_to_gguf.py" \
  "$TASK_DEPLOYMENT/tooling/convert_hf_to_gguf.py"
install -m 700 "$TASK_QUANTIZER_ROOT/llama-quantize" \
  "$TASK_DEPLOYMENT/tooling/llama-quantize"
if test "$TASK_ROUTE" = adapter_on_off; then
  install -m 600 "$TASK_CONVERTER_ROOT/convert_lora_to_gguf.py" \
    "$TASK_DEPLOYMENT/tooling/convert_lora_to_gguf.py"
else
  install -m 600 "$TASK_CONVERSION_TOOLS/bin/merge_adapter.py" \
    "$TASK_DEPLOYMENT/tooling/merge_adapter.py"
fi

. "$TASK_ROOT/conversion-venv/bin/activate"
TASK_CONVERSION_PYTHON="$TASK_ROOT/conversion-venv/bin/python"
TASK_TRAINING_PYTHON="$TASK_ROOT/venv/bin/python"
export HF_HOME="$TASK_ROOT/hf-home"
export HF_HUB_OFFLINE=1
export TRANSFORMERS_OFFLINE=1
export PYTHONPATH="$TASK_CONVERTER_ROOT/gguf-py"
TASK_BASE_DIR="$(python - <<'PY'
from huggingface_hub import snapshot_download
print(snapshot_download(
    repo_id="mistralai/Ministral-3-8B-Instruct-2512-BF16",
    revision="f6fae9795746f63c9be8344932f01275f3c63734",
    cache_dir="/workspace/rondo-l6/hf-home/hub",
    local_files_only=True,
))
PY
)"
test "$(python - "$TASK_BASE_DIR/model.safetensors.index.json" <<'PY'
import json, pathlib, sys
print(json.loads(pathlib.Path(sys.argv[1]).read_text())["metadata"]["total_size"])
PY
)" = 17836052480

"$TASK_CONVERSION_PYTHON" "$TASK_CONVERTER_ROOT/convert_hf_to_gguf.py" \
  --outfile "$TASK_DEPLOYMENT/work/base-f16.gguf" --outtype f16 \
  --use-temp-file "$TASK_BASE_DIR" \
  2>&1 | tee "$TASK_DEPLOYMENT/base-convert.log"
"$TASK_QUANTIZER_ROOT/llama-quantize" \
  "$TASK_DEPLOYMENT/work/base-f16.gguf" \
  "$TASK_DEPLOYMENT/base-q4_k_m.gguf" Q4_K_M \
  2>&1 | tee "$TASK_DEPLOYMENT/base-quantize.log"
test -s "$TASK_DEPLOYMENT/base-q4_k_m.gguf"
rm -f -- "$TASK_DEPLOYMENT/work/base-f16.gguf"
test "$(df -B1 --output=avail /workspace | tail -n1 | tr -d ' ')" \
  -ge 20000000000

if test "$TASK_ROUTE" = adapter_on_off; then
  "$TASK_CONVERSION_PYTHON" "$TASK_CONVERTER_ROOT/convert_lora_to_gguf.py" \
    --base "$TASK_BASE_DIR" \
    --outfile "$TASK_DEPLOYMENT/adapter-f16.gguf" --outtype f16 \
    "$TASK_FORMAL_OUTPUT/adapter-final" \
    2>&1 | tee "$TASK_DEPLOYMENT/adapter-convert.log"
  test -s "$TASK_DEPLOYMENT/adapter-f16.gguf"
else
  "$TASK_TRAINING_PYTHON" "$TASK_DEPLOYMENT/tooling/merge_adapter.py" \
    --base "$TASK_BASE_DIR" \
    --adapter "$TASK_FORMAL_OUTPUT/adapter-final" \
    --output "$TASK_DEPLOYMENT/work/merged-hf" \
    2>&1 | tee "$TASK_DEPLOYMENT/merge.log"
  export PYTHONPATH="$TASK_CONVERTER_ROOT/gguf-py"
  "$TASK_CONVERSION_PYTHON" "$TASK_CONVERTER_ROOT/convert_hf_to_gguf.py" \
    --outfile "$TASK_DEPLOYMENT/work/finetuned-f16.gguf" --outtype f16 \
    --use-temp-file "$TASK_DEPLOYMENT/work/merged-hf" \
    2>&1 | tee "$TASK_DEPLOYMENT/finetuned-convert.log"
  "$TASK_QUANTIZER_ROOT/llama-quantize" \
    "$TASK_DEPLOYMENT/work/finetuned-f16.gguf" \
    "$TASK_DEPLOYMENT/finetuned-q4_k_m.gguf" Q4_K_M \
    2>&1 | tee "$TASK_DEPLOYMENT/finetuned-quantize.log"
  test -s "$TASK_DEPLOYMENT/finetuned-q4_k_m.gguf"
  test "$TASK_DEPLOYMENT/work/merged-hf" = \
    "$TASK_ROOT/deployments/$TASK_ATTEMPT_ID/$TASK_ROUTE_ATTEMPT/work/merged-hf"
  rm -rf -- "$TASK_DEPLOYMENT/work/merged-hf"
  rm -f -- "$TASK_DEPLOYMENT/work/finetuned-f16.gguf"
fi
rmdir "$TASK_DEPLOYMENT/work"

"$TASK_CONVERSION_PYTHON" \
  "$TASK_CONVERSION_TOOLS/bin/conversion_tooling.py" write-operations \
  --contract "$TASK_CONVERSION_TOOLS/contracts/conversion-tool-contract-v1.json" \
  --tool-bundle "$TASK_CONVERSION_TOOLS" \
  --output "$TASK_DEPLOYMENT" \
  --training-receipt "$TASK_FORMAL_OUTPUT/training-receipt.json" \
  --route "$TASK_ROUTE" \
  --base-snapshot "$TASK_BASE_DIR" \
  --formal-output "$TASK_FORMAL_OUTPUT" \
  --conversion-python "$TASK_CONVERSION_PYTHON" \
  --training-python "$TASK_TRAINING_PYTHON"
```

Create the exact route manifest and receipt. Hashing is streamed in 1 MiB
chunks, so multi-gigabyte GGUFs are never read into memory at once. The receipt
binds the already-completed training receipt and its adapter tree.

```bash
set -euo pipefail
umask 077
. "$TASK_ROOT/conversion-venv/bin/activate"
python - "$TASK_DEPLOYMENT" "$TASK_ROUTE" <<'PY'
import importlib.metadata as metadata
import json
import pathlib
import platform
import sys
import torch

output = pathlib.Path(sys.argv[1])
route = sys.argv[2]
names = ("numpy", "sentencepiece", "transformers", "protobuf",
         "huggingface-hub", "safetensors", "tqdm", "PyYAML", "requests")
value = {
    "schema_version": 1,
    "version": "rondo_local_approval_l6_conversion_dependency_identity_v1",
    "packages": {name: metadata.version(name) for name in names},
    "python": platform.python_version(),
    "torch": torch.__version__,
    "cuda": torch.version.cuda,
    "container_image": "runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404",
    "route": route,
}
(output / "conversion-dependency-identity.json").write_text(
    json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
)
PY

python - "$TASK_DEPLOYMENT" "$TASK_CONVERSION_TOOLS" "$TASK_ROUTE" \
  "$TASK_FORMAL_OUTPUT/training-receipt.json" <<'PY'
import hashlib
import json
import os
import pathlib
import stat
import sys

output = pathlib.Path(sys.argv[1])
tools = pathlib.Path(sys.argv[2])
route = sys.argv[3]
training_path = pathlib.Path(sys.argv[4])
contract_raw = (tools / "contracts/conversion-tool-contract-v1.json").read_bytes()
contract = json.loads(contract_raw)
allowed = set(contract["output_allowlists"][route])

def identity(path):
    info = os.lstat(path)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise SystemExit(f"non_regular_conversion_output:{path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return {"size_bytes": info.st_size, "sha256": digest.hexdigest()}

observed = {
    path.relative_to(output).as_posix()
    for path in output.rglob("*") if not path.is_dir()
}
expected = allowed - {"conversion-files-manifest.json", "conversion-receipt.json"}
if observed != expected:
    raise SystemExit("conversion_output_allowlist_mismatch")
files = {name: identity(output / name) for name in sorted(observed)}
manifest = {
    "schema_version": 1,
    "version": "rondo_local_approval_l6_conversion_files_v1",
    "route": route,
    "files": files,
}
manifest_raw = (
    json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
).encode()
(output / "conversion-files-manifest.json").write_bytes(manifest_raw)
training_raw = training_path.read_bytes()
training = json.loads(training_raw)
receipt = {
    "schema_version": 1,
    "version": "rondo_local_approval_l6_conversion_receipt_v1",
    "status": "completed",
    "route": route,
    "base_model": contract["base_model"],
    "quantization": "Q4_K_M",
    "source_adapter_tree_sha256": training["artifacts"]["adapter"]["tree_sha256"],
    "training_receipt_sha256": hashlib.sha256(training_raw).hexdigest(),
    "conversion_contract_sha256": hashlib.sha256(contract_raw).hexdigest(),
    "tool_bundle_manifest_sha256": hashlib.sha256(
        (tools / "conversion-tool-bundle-manifest.json").read_bytes()
    ).hexdigest(),
    "dependency_identity_sha256": files["conversion-dependency-identity.json"]["sha256"],
    "operations_sha256": files["conversion-operations.json"]["sha256"],
    "files_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
    "deployed_outputs": {
        name: files[name] for name in sorted(files) if name.endswith(".gguf")
    },
    "temporary_f16_and_merged_hf_removed": True,
}
(output / "conversion-receipt.json").write_text(
    json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
)
PY
chmod 600 "$TASK_DEPLOYMENT"/*.json "$TASK_DEPLOYMENT"/*.log \
  "$TASK_DEPLOYMENT"/*.gguf \
  "$TASK_DEPLOYMENT/tooling/convert_hf_to_gguf.py"
if test "$TASK_ROUTE" = adapter_on_off; then
  chmod 600 "$TASK_DEPLOYMENT/tooling/convert_lora_to_gguf.py"
else
  chmod 600 "$TASK_DEPLOYMENT/tooling/merge_adapter.py"
fi
chmod 700 "$TASK_DEPLOYMENT/tooling/llama-quantize"
python "$TASK_CONVERSION_TOOLS/bin/conversion_tooling.py" verify-output \
  --contract "$TASK_CONVERSION_TOOLS/contracts/conversion-tool-contract-v1.json" \
  --tool-bundle "$TASK_CONVERSION_TOOLS" \
  --output "$TASK_DEPLOYMENT" \
  --training-receipt "$TASK_FORMAL_OUTPUT/training-receipt.json"
test "$(df -B1 --output=avail /workspace | tail -n1 | tr -d ' ')" \
  -ge 20000000000
```

If the preferred adapter converter itself proves incompatible before it can
produce a verified receipt, preserve `adapter-on-off-01` and use the still
running same Pod for the fallback; an ordinary missing dependency or wrong path
must be fixed instead of being mislabeled incompatibility. Below `$10`, set the
following overrides and rerun only I's conversion/receipt/remote
`verify-output` blocks. They write a distinct directory and never invoke
training:

```bash
export TASK_ROUTE=paired_gguf
export TASK_ROUTE_ATTEMPT=paired-gguf-01
# Re-run I's conversion, receipt and remote verify-output blocks only.
test -f "/workspace/rondo-l6/deployments/attempt-01/$TASK_ROUTE_ATTEMPT/conversion-receipt.json"
```

Recover deployment artifacts separately and run the same streaming verifier on
the local copy before Pod deletion:

```bash
set -euo pipefail
TASK_ROUTE="${TASK_ROUTE:-adapter_on_off}"
case "$TASK_ROUTE" in
  adapter_on_off) TASK_ROUTE_ATTEMPT="${TASK_ROUTE_ATTEMPT:-adapter-on-off-01}" ;;
  paired_gguf) TASK_ROUTE_ATTEMPT="${TASK_ROUTE_ATTEMPT:-paired-gguf-01}" ;;
  *) echo 'conversion_route_invalid' >&2; exit 2 ;;
esac
TASK_LOCAL_DEPLOYMENTS="$TASK_LOCAL_RECOVERY-deployments"
TASK_LOCAL_DEPLOYMENT="$TASK_LOCAL_DEPLOYMENTS/$TASK_ROUTE_ATTEMPT"
test ! -e "$TASK_LOCAL_DEPLOYMENT"
install -d -m 700 "$TASK_LOCAL_DEPLOYMENTS"
install -d -m 700 "$TASK_LOCAL_DEPLOYMENT"
scp -r -o IdentitiesOnly=yes -i "$TASK_SSH_KEY" \
  -P "$TASK_SSH_PORT" \
  root@"$TASK_SSH_HOST":/workspace/rondo-l6/deployments/"$TASK_ATTEMPT_ID"/"$TASK_ROUTE_ATTEMPT"/. \
  "$TASK_LOCAL_DEPLOYMENT"/
cd "$TASK_WORKTREE"
PYTHONDONTWRITEBYTECODE=1 python3 -B \
  training/local-approval-l6/conversion_tooling.py verify-output \
  --contract training/local-approval-l6/conversion-tool-contract-v1.json \
  --tool-bundle "$TASK_CONVERSION_TOOL_BUNDLE" \
  --output "$TASK_LOCAL_DEPLOYMENT" \
  --training-receipt "$TASK_LOCAL_RECOVERY/training-receipt.json"
sha256sum "$TASK_LOCAL_DEPLOYMENT/conversion-files-manifest.json" \
  "$TASK_LOCAL_DEPLOYMENT/conversion-receipt.json"
```

No HF object is created during stage-2A. The owner confirms the personal
account's included 100 GB is unused and grants standing permission to use HF
features only while their incremental cost remains exactly `$0`. The default
success path still uses local SCP. If a later plan change makes a private HF
artifact mirror materially useful, the active executor may first add and run
an exact staging allowlist/verifier, then use the free private storage without
another ordinary technical approval. Staging is limited to selected
adapter/checkpoint or GGUF, actual configuration/dependency identities,
aggregate metrics, manifests and receipts; it must reject logs, tool
source/binaries, datasets, projections and per-sample outputs. HF compute stays
forbidden because RunPod is the sole training/conversion backend. Any PRO,
pay-as-you-go, paid storage/compute or public asset still requires new explicit
authorization.

## J. Stop the task Pod and run local compatibility smoke

After local training and the preferred deployment both verify, stop the same
Pod before loading the model locally. This ends GPU billing while retaining the
100 GB Pod volume, frozen BF16 cache and completed training output for one
evidence-backed `paired_gguf` fallback. Do not delete it yet.

```bash
set -euo pipefail
runpodctl pod stop "$TASK_POD_ID"
for TASK_STOP_POLL in $(seq 1 40); do
  TASK_RUNTIME_STATUS="$(runpodctl pod get "$TASK_POD_ID" -o json | jq -er .runtimeStatus)"
  test "$TASK_RUNTIME_STATUS" = stopped && break
  sleep 15
done
test "$TASK_RUNTIME_STATUS" = stopped
runpodctl user
runpodctl billing pods --bucket-size hour --start-time "$TASK_START_UTC" \
  --grouping podId --pod-id "$TASK_POD_ID"
```

Record the stopped-volume timestamp and current task spend. The 100 GB stopped
volume remains billable; do not leave it stopped while doing unrelated work.
At `$10`, do not restart it for conversion. At `$12`, delete it immediately.

Now materialize the selected deployment pair beside the two verified local
downloads using same-filesystem hard links. This avoids duplicating the 5-12 GB
GGUF payload while keeping both recovered manifests immutable. Retain the
source directory with the private evidence: the locator rehashes every source
object on each use.

```bash
set -euo pipefail
umask 077
TASK_WORKTREE=/home/sjc/desktop/RONDO/.claude/worktrees/037-l6-first-lora-paired-artifacts
TASK_LOCAL_RECOVERY='/home/sjc/desktop/RONDO/eval-data/local-approval/l6/plan037-stage2/<FORMAL_RUN_ID>'
TASK_ROUTE="${TASK_ROUTE:-adapter_on_off}"
case "$TASK_ROUTE" in
  adapter_on_off) TASK_ROUTE_ATTEMPT="${TASK_ROUTE_ATTEMPT:-adapter-on-off-01}" ;;
  paired_gguf) TASK_ROUTE_ATTEMPT="${TASK_ROUTE_ATTEMPT:-paired-gguf-01}" ;;
  *) echo 'conversion_route_invalid' >&2; exit 2 ;;
esac
TASK_LOCAL_DEPLOYMENT="$TASK_LOCAL_RECOVERY-deployments/$TASK_ROUTE_ATTEMPT"
TASK_PAIR_ROOT="$TASK_LOCAL_RECOVERY-pairs/$TASK_ROUTE_ATTEMPT"
TASK_PAIR_SOURCE="$TASK_PAIR_ROOT/source"
TASK_PAIR_PRIVATE="$TASK_PAIR_ROOT/private"
TASK_PAIR_RUN="$TASK_PAIR_ROOT/journal"
TASK_PAIR_ID="l6-plan037-<FORMAL_RUN_ID_NORMALIZED>-$TASK_ROUTE_ATTEMPT"
TASK_C_AVAILABLE_BYTES="$(df -B1 --output=avail /mnt/c | tail -n1 | tr -d ' ')"
test "$TASK_C_AVAILABLE_BYTES" -ge 85899345920
if pgrep -x cargo >/dev/null || pgrep -x rustc >/dev/null; then
  echo 'refuse: heavy Cargo work is active' >&2
  exit 2
fi
TASK_RUNNING_CONTAINERS="$(docker container ls -q)"
if test -n "$TASK_RUNNING_CONTAINERS"; then
  echo 'refuse: a Docker container is active' >&2
  exit 2
fi
if pgrep -x llama-server >/dev/null; then
  echo 'refuse: another local model server is active' >&2
  exit 2
fi
TASK_BUILD_LOCK="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/rondo-cargo-build.lock"
command -v flock >/dev/null
test ! -L "$TASK_BUILD_LOCK"
if test -e "$TASK_BUILD_LOCK"; then test -O "$TASK_BUILD_LOCK"; fi
exec 9>"$TASK_BUILD_LOCK"
if ! flock -n 9; then
  echo 'refuse: heavy Cargo build lock is held' >&2
  exit 2
fi
test ! -e "$TASK_PAIR_ROOT"
install -d -m 700 "$TASK_PAIR_SOURCE" "$TASK_PAIR_PRIVATE" "$TASK_PAIR_RUN"

cd "$TASK_WORKTREE"
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=eval python3 -B - \
  "$TASK_LOCAL_RECOVERY" "$TASK_LOCAL_DEPLOYMENT" "$TASK_PAIR_SOURCE" <<'PY'
import json
import os
import pathlib
import shutil
import sys

from rondo_eval.local_approval import cross_eval, paired_outputs

recovery = pathlib.Path(sys.argv[1])
deployment = pathlib.Path(sys.argv[2])
target = pathlib.Path(sys.argv[3])
receipt = json.loads((recovery / "training-receipt.json").read_text())
conversion = json.loads((deployment / "conversion-receipt.json").read_text())
route = conversion["route"]
if route not in {"adapter_on_off", "paired_gguf"}:
    raise SystemExit("deployment_route_invalid")

shutil.copy2(recovery / "training-receipt.json", target / "training-receipt.json")
shutil.copytree(
    recovery / receipt["output_paths"]["adapter"],
    target / receipt["output_paths"]["adapter"],
    copy_function=os.link,
)
selected = {
    "base-q4_k_m.gguf",
    "conversion-operations.json",
    "tooling/llama-quantize",
}
selected.add(
    "adapter-f16.gguf" if route == "adapter_on_off"
    else "finetuned-q4_k_m.gguf"
)
for relative_name in sorted(selected):
    source = deployment / relative_name
    destination = target / "deployment" / relative_name
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.link(source, destination)

adapter_tree = receipt["artifacts"]["adapter"]["tree_sha256"]
converter = target / "deployment/conversion-operations.json"
quantizer = target / "deployment/tooling/llama-quantize"
base_gguf = target / "deployment/base-q4_k_m.gguf"
static_manifest = target / "local-static.deployment.json"
ft_manifest = target / "local-ft-static.deployment.json"
static = paired_outputs.build_b10333_deployment_manifest(
    deployment_id="plan037-local-static",
    manifest_path=static_manifest,
    deployment_mode=route,
    side="local-static",
    model_gguf=base_gguf,
    converter=converter,
    quantizer=quantizer,
    quantization="Q4_K_M",
)
ft = paired_outputs.build_b10333_deployment_manifest(
    deployment_id="plan037-local-ft-static",
    manifest_path=ft_manifest,
    deployment_mode=route,
    side="local-ft-static",
    model_gguf=(
        base_gguf if route == "adapter_on_off"
        else target / "deployment/finetuned-q4_k_m.gguf"
    ),
    converter=converter,
    quantizer=quantizer,
    quantization="Q4_K_M",
    deployed_adapter_files=(
        {"plan037-lora": target / "deployment/adapter-f16.gguf"}
        if route == "adapter_on_off" else None
    ),
    source_adapter_tree_sha256=adapter_tree,
)
cross_eval._write_exclusive(
    static_manifest, cross_eval._json_file_bytes(static), mode=0o600
)
cross_eval._write_exclusive(
    ft_manifest, cross_eval._json_file_bytes(ft), mode=0o600
)
PY

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=eval python3 -B \
  -m rondo_eval.local_approval.l6_b10333_pair prepare-evidence \
  --pair-id "$TASK_PAIR_ID" \
  --base-model training/local-approval-l6/model-contract-v1.json \
  --local-static-deployment "$TASK_PAIR_SOURCE/local-static.deployment.json" \
  --local-ft-deployment "$TASK_PAIR_SOURCE/local-ft-static.deployment.json" \
  --training-receipt "$TASK_PAIR_SOURCE/training-receipt.json" \
  --runtime-lock eval/locks/llama-cpp-b10333-cuda-linux-x64.json \
  --chat-template eval/templates/local-approval/ministral-3-8b-instruct-2512-chat-template.jinja \
  --pair-contract eval/templates/cross-eval-judge/local-m4-l6-pair-contract-v1.json \
  --blind-identity-marker artifact-037-a \
  --blind-identity-marker artifact-037-b \
  --private-dir "$TASK_PAIR_PRIVATE"
```

Verify the frozen CUDA runtime, display the exact server commands, then run the
separate deterministic two-sample structural smoke. Its status is `passed`
when both deployments load with the bound identity, both serial side sessions
complete, every request records a legal terminal, and both processes are
cleaned up. Decision counts and terminal-status counts are diagnostic only;
typed structured-output, timeout or refusal terminals stay honest in the 0600
receipt and do not block formal execution. It never writes the formal journal
and never selects a recipe or checkpoint.

```bash
set -euo pipefail
TASK_PAIR_EVIDENCE="$TASK_PAIR_PRIVATE/l6-pair-evidence.json"
TASK_RUNTIME_BINARY=/home/sjc/desktop/RONDO/eval-data/tools/llama-b10333-cuda-linux-x64/llama-server
TASK_PAIR_PORT=18437
test "$(sha256sum eval/locks/llama-cpp-b10333-cuda-linux-x64.json | cut -d' ' -f1)" \
  = 299440bb261f9dbc6641e81fa995ca88af84e4e05530978fe9c46a9716107b75
test "$(sha256sum "$TASK_RUNTIME_BINARY" | cut -d' ' -f1)" \
  = 97a6b083ea34fea7e4e4440a0ddb734e1a2f6b775f4b31ef68ba5f998a9eeabd
if ss -H -ltn "sport = :$TASK_PAIR_PORT" | grep -q .; then
  echo 'refuse: selected loopback port is already listening' >&2
  exit 2
fi

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=eval python3 -B \
  -m rondo_eval.local_approval.l6_b10333_pair show-commands \
  --worktree-root "$TASK_WORKTREE" \
  --pair-evidence-source "$TASK_PAIR_EVIDENCE" \
  --runtime-binary "$TASK_RUNTIME_BINARY" --port "$TASK_PAIR_PORT"
TASK_SMOKE_RESULT="$(PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=eval python3 -B \
  -m rondo_eval.local_approval.l6_b10333_pair smoke \
  --worktree-root "$TASK_WORKTREE" \
  --pair-evidence-source "$TASK_PAIR_EVIDENCE" \
  --runtime-binary "$TASK_RUNTIME_BINARY" --port "$TASK_PAIR_PORT" \
  --private-dir "$TASK_PAIR_PRIVATE" --sample-count 2)"
printf '%s\n' "$TASK_SMOKE_RESULT"
printf '%s\n' "$TASK_SMOKE_RESULT" | jq -e '.status == "passed"'
```

If this preferred-route smoke passes, skip directly to J.2. Do not choose a
route from the model decisions or validation quality. Zero decisions, typed
structured-output failures, timeouts or refusals are not fallback triggers. If
and only if the conversion logs or b10333 startup/identity logs prove that the
converted LoRA itself cannot be produced or loaded by the frozen runtime, keep
the stopped Pod and use the fallback below. Preserve the failed route's
deployment, private smoke receipt and server logs; do not rewrite them.

### J.1 Same-Pod `paired_gguf` compatibility fallback

The fallback is a deployment conversion, not another training recipe. It is
allowed only below the `$10` hard recovery line and while the conservative
total remains below `$12`. Start the same Pod ID, wait for its actual runtime
to become ready, and refresh SSH facts; do not create a replacement Pod while
this one exists:

```bash
set -euo pipefail
runpodctl user
runpodctl billing pods --bucket-size hour --start-time "$TASK_START_UTC" \
  --grouping podId --pod-id "$TASK_POD_ID"
TASK_ROUTE=paired_gguf
TASK_ROUTE_ATTEMPT=paired-gguf-01
runpodctl pod start "$TASK_POD_ID"
for TASK_START_POLL in $(seq 1 80); do
  TASK_RUNTIME_STATUS="$(runpodctl pod get "$TASK_POD_ID" -o json | jq -er .runtimeStatus)"
  test "$TASK_RUNTIME_STATUS" = running && break
  sleep 15
done
test "$TASK_RUNTIME_STATUS" = running
runpodctl pod get "$TASK_POD_ID"
runpodctl ssh info "$TASK_POD_ID"
export TASK_SSH_HOST='<CURRENT_SSH_HOST_FROM_SSH_INFO>'
export TASK_SSH_PORT='<CURRENT_SSH_PORT_FROM_SSH_INFO>'
ssh -o IdentitiesOnly=yes -i "$TASK_SSH_KEY" \
  -p "$TASK_SSH_PORT" root@"$TASK_SSH_HOST"
```

In the refreshed remote shell, set the following exact route variables and
rerun only the conversion/receipt/remote `verify-output` blocks in I. The
defaults in those blocks now preserve these overrides. Do not invoke
`runpod-stage2-entrypoint.sh`, `l6_training.py train`, or any optimizer step:

```bash
export TASK_ROUTE=paired_gguf
export TASK_ROUTE_ATTEMPT=paired-gguf-01
# Re-run I's conversion, receipt and remote verify-output blocks only.
test -f "/workspace/rondo-l6/deployments/attempt-01/$TASK_ROUTE_ATTEMPT/conversion-receipt.json"
```

Back on the local controller, retain the adapter attempt and select independent
fallback paths. Rerun I's deployment SCP/local `verify-output` block, then J's
Pod-stop block and pair-materialization/structural-smoke blocks with these
exports. They resolve to distinct remote deployment, local deployment, pair
source, private receipt, journal and server-log directories:

```bash
export TASK_ROUTE=paired_gguf
export TASK_ROUTE_ATTEMPT=paired-gguf-01
export TASK_LOCAL_DEPLOYMENT="$TASK_LOCAL_RECOVERY-deployments/$TASK_ROUTE_ATTEMPT"
export TASK_PAIR_ROOT="$TASK_LOCAL_RECOVERY-pairs/$TASK_ROUTE_ATTEMPT"
# Re-run I deployment SCP + local verify-output, then J stop + materialize + smoke.
test -f "$TASK_LOCAL_DEPLOYMENT/conversion-receipt.json"
test "$(jq -r .status "$TASK_PAIR_ROOT/private/l6-pair-structural-smoke.json")" = passed
```

If this second route cannot complete its local structural smoke, or the `$12`
cap is reached, delete the Pod, retain the already-local diagnostics and stop;
do not train again or invent a completed pair result. A replacement Pod is a
last resort only when the original Pod is actually gone, never concurrently,
and its cost remains in the same `$12` ledger.

### J.2 Delete after the selected route passes local smoke

For either route, require its local smoke receipt before deleting the same Pod.
Deletion permanently removes the retained volume and BF16 cache:

```bash
set -euo pipefail
test "$(jq -r .status "$TASK_PAIR_PRIVATE/l6-pair-structural-smoke.json")" = passed
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
exceed `$12`, and both local artifact manifests still verify. Record the final
billing result and deleted Pod ID without recording any credential.

Only after the selected route's structural smoke and Pod deletion, run 130
inputs × 2 local models = 260 new local
attempts. Assembly adds the existing 130 Sol-side rows, so the canonical import
contains exactly 390 rows. The two model servers run serially, and `run`
performs formal import verification internally; the explicit command repeats
that check.

```bash
set -euo pipefail
TASK_PAIR_RESULT="$(PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=eval python3 -B \
  -m rondo_eval.local_approval.l6_b10333_pair run \
  --worktree-root "$TASK_WORKTREE" \
  --pair-evidence-source "$TASK_PAIR_EVIDENCE" \
  --runtime-binary "$TASK_RUNTIME_BINARY" --port "$TASK_PAIR_PORT" \
  --run-dir "$TASK_PAIR_RUN" --private-dir "$TASK_PAIR_PRIVATE")"
printf '%s\n' "$TASK_PAIR_RESULT"
printf '%s\n' "$TASK_PAIR_RESULT" \
  | jq -e '.status == "complete" and .side_output_count == 390'

PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=eval python3 -B \
  -m rondo_eval.local_approval.cross_eval verify-import \
  --worktree-root "$TASK_WORKTREE" \
  --outputs "$TASK_PAIR_PRIVATE/three-side-outputs.jsonl" \
  --pair-receipt "$TASK_PAIR_PRIVATE/l6-pair-receipt.json" \
  --pair-evidence "$TASK_PAIR_PRIVATE/l6-pair-evidence.json" \
  | tee "$TASK_PAIR_PRIVATE/verify-import-result.json"
test "$(wc -l < "$TASK_PAIR_PRIVATE/three-side-outputs.jsonl")" -eq 390
chmod 600 "$TASK_PAIR_PRIVATE/verify-import-result.json"
sha256sum "$TASK_PAIR_PRIVATE/three-side-outputs.jsonl" \
  "$TASK_PAIR_PRIVATE/l6-pair-receipt.json" \
  "$TASK_PAIR_PRIVATE/l6-pair-evidence.json"
flock -u 9
exec 9>&-
```

If unexpected infrastructure interruption leaves one dangling journal
attempt, do not relabel it as a model terminal. Resolve exactly that attempt,
then rerun the exact `run` and `verify-import` commands; completed attempts are
reused:

```bash
set -euo pipefail
TASK_BUILD_LOCK="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/rondo-cargo-build.lock"
command -v flock >/dev/null
test ! -L "$TASK_BUILD_LOCK"
if test -e "$TASK_BUILD_LOCK"; then test -O "$TASK_BUILD_LOCK"; fi
exec 9>"$TASK_BUILD_LOCK"
if ! flock -n 9; then
  echo 'refuse: heavy Cargo build lock is held' >&2
  exit 2
fi
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=eval python3 -B \
  -m rondo_eval.local_approval.l6_b10333_pair resolve-interrupted \
  --worktree-root "$TASK_WORKTREE" \
  --pair-evidence-source "$TASK_PAIR_EVIDENCE" \
  --run-dir "$TASK_PAIR_RUN" \
  --failure-code '<TASK_SPECIFIC_INFRASTRUCTURE_FAILURE_CODE>'
```

Keep FD 9 held while rerunning the exact formal `run` and `verify-import`
commands above; their successful tail releases it. If recovery exits early,
the shell closing releases the lock without relabeling the interrupted attempt.

The runner owns and stops its two task processes. Require the port to be idle;
do not kill unrelated processes. Keep `source/`, `private/` and `journal/`
together as the verifiable pair evidence. Pod deletion already removed the
remote cache, temporary F16/merged weights, venvs and transferred bundles.

```bash
if ss -H -ltn "sport = :$TASK_PAIR_PORT" | grep -q .; then
  echo 'refuse completion: task llama-server still listening' >&2
  exit 2
fi
if pgrep -x llama-server >/dev/null; then
  echo 'refuse completion: a llama-server process remains' >&2
  exit 2
fi
nvidia-smi
du -sh "$TASK_PAIR_ROOT" "$TASK_LOCAL_RECOVERY" "$TASK_LOCAL_DEPLOYMENT"
```

Official command references: [RunPod Pod CLI](https://docs.runpod.io/runpodctl/reference/runpodctl-pod),
[RunPod SSH](https://docs.runpod.io/pods/configuration/use-ssh),
[RunPod file transfer](https://docs.runpod.io/pods/storage/transfer-files),
[RunPod billing CLI](https://docs.runpod.io/runpodctl/reference/runpodctl-billing),
and [HF CLI download](https://huggingface.co/docs/huggingface_hub/guides/cli#hf-download).
