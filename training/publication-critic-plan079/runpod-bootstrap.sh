#!/usr/bin/env bash
set -eu

: "${RONDO_PLAN079_TASK_ROOT:?set persistent task root}"
: "${RONDO_PLAN079_SOURCE_ROOT:?set extracted source root}"
: "${RONDO_PLAN079_SOURCE_ARCHIVE:?set uploaded source archive}"
: "${RONDO_PLAN079_SOURCE_SHA256:?set source archive hash}"
: "${RONDO_PLAN079_VALIDATION_ARCHIVE:?set uploaded validation archive}"
: "${RONDO_PLAN079_VALIDATION_SHA256:?set validation archive hash}"
: "${RONDO_PLAN079_IMAGE_ID:?set observed image identity}"
: "${RONDO_PLAN079_STATUS:?set unique status path}"
case "$RONDO_PLAN079_SOURCE_SHA256" in *[!0-9a-f]*) exit 2 ;; esac
case "$RONDO_PLAN079_VALIDATION_SHA256" in *[!0-9a-f]*) exit 2 ;; esac
if [ "${#RONDO_PLAN079_SOURCE_SHA256}" -ne 64 ] || [ "${#RONDO_PLAN079_VALIDATION_SHA256}" -ne 64 ]; then exit 2; fi
case "$RONDO_PLAN079_TASK_ROOT" in /workspace/*) ;; *) exit 2 ;; esac
task_root="$(realpath -e -- "$RONDO_PLAN079_TASK_ROOT")"
case "$task_root" in /workspace/*) ;; *) exit 2 ;; esac
require_task_path() {
  candidate="$(realpath -m -- "$1")" || return 1
  case "$candidate" in "$task_root"/*) printf '%s\n' "$candidate" ;; *) return 1 ;; esac
}
source_root="$(require_task_path "$RONDO_PLAN079_SOURCE_ROOT")" || exit 2
source_archive="$(require_task_path "$RONDO_PLAN079_SOURCE_ARCHIVE")" || exit 2
validation_archive="$(require_task_path "$RONDO_PLAN079_VALIDATION_ARCHIVE")" || exit 2
status="$(require_task_path "$RONDO_PLAN079_STATUS")" || exit 2
case "$status" in "$task_root"/controller/*.json) ;; *) exit 2 ;; esac
if [ -e "$status" ] || [ -L "$status" ]; then exit 2; fi

umask 077
write_status() {
  rc=$?
  trap - EXIT
  temporary="$status.tmp.$$"
  if [ "$rc" -eq 0 ]; then
    printf '%s\n' '{"status":"completed","mode":"bootstrap"}' > "$temporary"
  else
    printf '{"status":"failed","mode":"bootstrap","exit_code":%s}\n' "$rc" > "$temporary"
  fi
  mv "$temporary" "$status"
  exit "$rc"
}
trap write_status EXIT

printf '%s  %s\n' "$RONDO_PLAN079_SOURCE_SHA256" "$source_archive" | sha256sum --check --status
printf '%s  %s\n' "$RONDO_PLAN079_VALIDATION_SHA256" "$validation_archive" | sha256sum --check --status
bundle="$task_root/validation-bundle"
if [ ! -d "$bundle" ]; then
  bundle_staging="$task_root/validation-bundle.extracting.$$"
  if [ -e "$bundle_staging" ] || [ -L "$bundle_staging" ]; then exit 2; fi
  mkdir -m 700 "$bundle_staging"
  tar --no-same-owner --no-same-permissions -xf "$validation_archive" -C "$bundle_staging"
  mv -T "$bundle_staging" "$bundle"
fi

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$source_root/eval"
source_receipts="$task_root/source-receipts"
mkdir -m 700 -p "$source_receipts"
if [ -L "$source_receipts" ] || [ ! -d "$source_receipts" ]; then exit 2; fi
source_receipt="$source_receipts/$RONDO_PLAN079_SOURCE_SHA256.json"
source_receipt_candidate="$source_receipts/$RONDO_PLAN079_SOURCE_SHA256.candidate.$$.json"
"${RONDO_PLAN079_BOOTSTRAP_PYTHON:-python3}" -B -P \
  -m rondo_eval.publication_critic.base_quality verify-source \
  --source-archive "$source_archive" \
  --source-root "$source_root" \
  --exact-tree \
  --output "$source_receipt_candidate"
if [ -e "$source_receipt" ] || [ -L "$source_receipt" ]; then
  if [ -L "$source_receipt" ] || ! cmp -s "$source_receipt" "$source_receipt_candidate"; then
    exit 2
  fi
  rm -f "$source_receipt_candidate"
else
  mv "$source_receipt_candidate" "$source_receipt"
fi
python3 -B -P -m rondo_eval.publication_critic.full_model_training verify-bundle \
  --bundle "$bundle"
venv="$task_root/venv"
if [ ! -x "$venv/bin/python" ]; then
  python3 -B -m venv --system-site-packages "$venv"
fi
"$venv/bin/python" -B -m pip install --disable-pip-version-check \
  --upgrade-strategy only-if-needed -r \
  "$source_root/training/publication-critic-plan079/dependencies-v1.txt"
"$venv/bin/python" -B -m pip check

unset HF_TOKEN HUGGING_FACE_HUB_TOKEN HUGGINGFACEHUB_API_TOKEN
export HF_HOME="$task_root/hf-home"
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_HUB_DISABLE_TELEMETRY=1
# Some RunPod base images enable the legacy hf_transfer fast path globally
# without installing its Python package.  The frozen Plan 079 environment uses
# the supported Hub client path and must not inherit that image-local toggle.
export HF_HUB_ENABLE_HF_TRANSFER=0
model="$task_root/model-fd958fef"
"$venv/bin/hf" download Skywork/Skywork-Reward-V2-Qwen3-4B \
  .gitattributes README.md added_tokens.json assets/skywork_logo.png \
  chat_template.jinja config.json merges.txt \
  model-00001-of-00002.safetensors model-00002-of-00002.safetensors \
  model.safetensors.index.json special_tokens_map.json tokenizer.json \
  tokenizer_config.json vocab.json \
  --revision fd958fef475f323f4e6b195930e3dd918485c668 \
  --local-dir "$model"
snapshot_receipt="$task_root/snapshot-receipt.json"
snapshot_receipt_candidate="$task_root/snapshot-receipt.candidate.$$.json"
"$venv/bin/python" -B -P -m rondo_eval.publication_critic.base_quality verify-snapshot \
  --snapshot "$model" \
  --model-lock "$source_root/eval/model-locks/publication-critic/skywork-reward-v2-qwen3-4b-fd958fef.json" \
  --output "$snapshot_receipt_candidate"
if [ -e "$snapshot_receipt" ] || [ -L "$snapshot_receipt" ]; then
  if [ -L "$snapshot_receipt" ] || ! cmp -s "$snapshot_receipt" "$snapshot_receipt_candidate"; then
    exit 2
  fi
  rm -f "$snapshot_receipt_candidate"
else
  mv "$snapshot_receipt_candidate" "$snapshot_receipt"
fi
dependency_freeze="$task_root/dependency-freeze-observed.txt"
dependency_freeze_candidate="$task_root/dependency-freeze-observed.candidate.$$.txt"
"$venv/bin/python" -B -m pip freeze --all > "$dependency_freeze_candidate"
chmod 600 "$dependency_freeze_candidate"
if [ -e "$dependency_freeze" ] || [ -L "$dependency_freeze" ]; then
  if [ -L "$dependency_freeze" ] || ! cmp -s "$dependency_freeze" "$dependency_freeze_candidate"; then
    exit 2
  fi
  rm -f "$dependency_freeze_candidate"
else
  mv "$dependency_freeze_candidate" "$dependency_freeze"
fi
gpu_runtime="$task_root/gpu-runtime-observed.txt"
gpu_runtime_candidate="$task_root/gpu-runtime-observed.candidate.$$.txt"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader \
  > "$gpu_runtime_candidate"
chmod 600 "$gpu_runtime_candidate"
if [ -e "$gpu_runtime" ] || [ -L "$gpu_runtime" ]; then
  if [ -L "$gpu_runtime" ] || ! cmp -s "$gpu_runtime" "$gpu_runtime_candidate"; then
    exit 2
  fi
  rm -f "$gpu_runtime_candidate"
else
  mv "$gpu_runtime_candidate" "$gpu_runtime"
fi
runtime_receipt="$task_root/runtime-receipt.json"
runtime_receipt_candidate="$task_root/runtime-receipt.candidate.$$.json"
"$venv/bin/python" -B -P -m rondo_eval.publication_critic.base_quality observe-runtime \
  --image-id "$RONDO_PLAN079_IMAGE_ID" \
  --dependency-freeze "$dependency_freeze" \
  --environment-lock "$source_root/eval/environments/publication-critic-plan068/uv.lock" \
  --output "$runtime_receipt_candidate"
if [ -e "$runtime_receipt" ] || [ -L "$runtime_receipt" ]; then
  if [ -L "$runtime_receipt" ] || ! cmp -s "$runtime_receipt" "$runtime_receipt_candidate"; then
    exit 2
  fi
  rm -f "$runtime_receipt_candidate"
else
  mv "$runtime_receipt_candidate" "$runtime_receipt"
fi
printf '%s\n' '{"status":"ready","model":"exact_two_shard_revision_verified"}'
