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
if [ ! -d "$source_root" ]; then
  mkdir -m 700 "$source_root"
  tar --no-same-owner --no-same-permissions -xf "$source_archive" -C "$source_root"
fi
bundle="$task_root/validation-bundle"
if [ ! -d "$bundle" ]; then
  mkdir -m 700 "$bundle"
  tar --no-same-owner --no-same-permissions -xf "$validation_archive" -C "$bundle"
fi

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$source_root/eval"
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
model="$task_root/model-fd958fef"
"$venv/bin/hf" download Skywork/Skywork-Reward-V2-Qwen3-4B \
  .gitattributes README.md added_tokens.json assets/skywork_logo.png \
  chat_template.jinja config.json merges.txt \
  model-00001-of-00002.safetensors model-00002-of-00002.safetensors \
  model.safetensors.index.json special_tokens_map.json tokenizer.json \
  tokenizer_config.json vocab.json \
  --revision fd958fef475f323f4e6b195930e3dd918485c668 \
  --local-dir "$model"
"$venv/bin/python" -B -P -m rondo_eval.publication_critic.base_quality verify-snapshot \
  --snapshot "$model" \
  --model-lock "$source_root/eval/model-locks/publication-critic/skywork-reward-v2-qwen3-4b-fd958fef.json" \
  --output "$task_root/snapshot-receipt.json"
"$venv/bin/python" -B -m pip freeze --all > "$task_root/dependency-freeze-observed.txt"
chmod 600 "$task_root/dependency-freeze-observed.txt"
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader \
  > "$task_root/gpu-runtime-observed.txt"
chmod 600 "$task_root/gpu-runtime-observed.txt"
printf '%s\n' '{"status":"ready","model":"exact_two_shard_revision_verified"}'
