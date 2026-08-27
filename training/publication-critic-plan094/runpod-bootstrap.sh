#!/usr/bin/env bash
set -eu
umask 077

if [ "${RONDO_PLAN094_STAGE_B_APPROVED:-}" != "1" ]; then exit 2; fi
: "${RONDO_PLAN094_TASK_ROOT:?set the mounted Plan 094 task root}"
: "${RONDO_PLAN094_SOURCE_ROOT:?set a new extracted source root}"
: "${RONDO_PLAN094_SOURCE_ARCHIVE:?set the uploaded source archive}"
: "${RONDO_PLAN094_SOURCE_SHA256:?set the source archive SHA-256}"
: "${RONDO_PLAN094_SOURCE_COMMIT:?set the frozen 40-hex source commit}"
: "${RONDO_PLAN094_DATA_ARCHIVE:?set the uploaded data archive}"
: "${RONDO_PLAN094_DATA_SHA256:?set the data archive SHA-256}"
: "${RONDO_PLAN094_IMAGE_IDENTITY:?set the exact approved container image identity}"
: "${RONDO_PLAN094_LAUNCH_NAME:?set a unique bootstrap segment name}"
: "${RONDO_PLAN094_MAX_SECONDS:?set a finite bootstrap timeout}"
: "${RONDO_PLAN094_BUDGET_SNAPSHOT:?set a fresh task-owned budget snapshot}"
: "${RONDO_PLAN094_COMPUTE_RATE_USD_PER_HOUR:?set the verified compute rate}"
: "${RONDO_PLAN094_STORAGE_RATE_USD_PER_HOUR:?set the verified storage rate}"
case "$RONDO_PLAN094_LAUNCH_NAME" in ''|*[!a-zA-Z0-9._-]*) exit 2 ;; esac
case "$RONDO_PLAN094_MAX_SECONDS" in ''|*[!0-9]*) exit 2 ;; esac
if [ "$RONDO_PLAN094_MAX_SECONDS" -le 0 ]; then exit 2; fi
if [ "$#" -eq 0 ]; then
  exec timeout --signal=TERM --kill-after=60s "$RONDO_PLAN094_MAX_SECONDS" \
    bash "$0" --plan094-under-budget-timeout
fi
if [ "$#" -ne 1 ] || [ "$1" != "--plan094-under-budget-timeout" ]; then exit 2; fi
unset HF_TOKEN HUGGING_FACE_HUB_TOKEN HUGGINGFACEHUB_API_TOKEN

case "$RONDO_PLAN094_TASK_ROOT" in /workspace/*) ;; *) exit 2 ;; esac
task_root="$(realpath -e -- "$RONDO_PLAN094_TASK_ROOT")"
case "$task_root" in /workspace/rondo-plan094-*) ;; *) exit 2 ;; esac
source_root="$(realpath -m -- "$RONDO_PLAN094_SOURCE_ROOT")"
source_archive="$(realpath -e -- "$RONDO_PLAN094_SOURCE_ARCHIVE")"
data_archive="$(realpath -e -- "$RONDO_PLAN094_DATA_ARCHIVE")"
budget_snapshot="$(realpath -e -- "$RONDO_PLAN094_BUDGET_SNAPSHOT")"
for path in "$source_root" "$source_archive" "$data_archive" "$budget_snapshot"; do
  case "$path" in "$task_root"/*) ;; *) exit 2 ;; esac
done
export HF_HOME="$task_root/hf-home"
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_HUB_DISABLE_TELEMETRY=1
export HF_HUB_ENABLE_HF_TRANSFER=0
for digest in "$RONDO_PLAN094_SOURCE_SHA256" "$RONDO_PLAN094_DATA_SHA256"; do
  case "$digest" in *[!0-9a-f]*) exit 2 ;; esac
  if [ "${#digest}" -ne 64 ]; then exit 2; fi
done
case "$RONDO_PLAN094_SOURCE_COMMIT" in *[!0-9a-f]*) exit 2 ;; esac
if [ "${#RONDO_PLAN094_SOURCE_COMMIT}" -ne 40 ]; then exit 2; fi

printf '%s  %s\n' "$RONDO_PLAN094_SOURCE_SHA256" "$source_archive" | sha256sum --check --status
printf '%s  %s\n' "$RONDO_PLAN094_DATA_SHA256" "$data_archive" | sha256sum --check --status
export PYTHONDONTWRITEBYTECODE=1
receipt_dir="$task_root/receipts"
log_dir="$task_root/logs"
mkdir -m 700 -p "$receipt_dir" "$log_dir"
bootstrap_log="$log_dir/bootstrap-${RONDO_PLAN094_SOURCE_SHA256}-${RONDO_PLAN094_DATA_SHA256}.log"
exec 3>>"$bootstrap_log"
source_receipt="$receipt_dir/source-${RONDO_PLAN094_SOURCE_SHA256}.json"
receipt_tmp="$source_receipt.tmp.$$"
data_receipt_tmp=""
snapshot_receipt_tmp=""
authorization_tmp=""
bootstrap_root="$task_root/.source-bootstrap-${RONDO_PLAN094_SOURCE_SHA256}-$$"
cleanup() {
  rm -f -- "$receipt_tmp" "$data_receipt_tmp" "$snapshot_receipt_tmp" \
    "$authorization_tmp"
  if [ -d "$bootstrap_root" ] && [ ! -L "$bootstrap_root" ]; then
    rm -rf -- "$bootstrap_root"
  fi
}
trap cleanup EXIT

publish_candidate() {
  candidate="$1"
  destination="$2"
  if [ -e "$destination" ] || [ -L "$destination" ]; then
    if [ ! -f "$destination" ] || [ -L "$destination" ]; then exit 2; fi
    cmp --silent -- "$destination" "$candidate" || exit 2
    rm -f -- "$candidate"
  else
    chmod 600 "$candidate"
    mv "$candidate" "$destination"
  fi
}

if [ -e "$source_root" ] || [ -L "$source_root" ]; then
  if [ ! -d "$source_root" ] || [ -L "$source_root" ]; then exit 2; fi
  export PYTHONPATH="$source_root/eval"
  python3 -B -P -m rondo_eval.publication_critic.full_model_training.plan094_cli \
    verify-source-archive --archive "$source_archive" \
    --source-root "$source_root" --exact-tree \
    --expected-commit "$RONDO_PLAN094_SOURCE_COMMIT" > "$receipt_tmp"
else
  mkdir -m 700 "$bootstrap_root"
  tar --no-same-owner --no-same-permissions -xf "$source_archive" \
    -C "$bootstrap_root"
  export PYTHONPATH="$bootstrap_root/eval"
  python3 -B -P -m rondo_eval.publication_critic.full_model_training.plan094_cli \
    verify-source-archive --archive "$source_archive" \
    --source-root "$bootstrap_root" --exact-tree \
    --expected-commit "$RONDO_PLAN094_SOURCE_COMMIT" > /dev/null
  python3 -B -P -m rondo_eval.publication_critic.full_model_training.plan094_cli \
    extract-source-archive --archive "$source_archive" \
    --expected-sha256 "$RONDO_PLAN094_SOURCE_SHA256" \
    --expected-commit "$RONDO_PLAN094_SOURCE_COMMIT" \
    --output "$source_root" > "$receipt_tmp"
  export PYTHONPATH="$source_root/eval"
fi
publish_candidate "$receipt_tmp" "$source_receipt"

authorization="$receipt_dir/$RONDO_PLAN094_LAUNCH_NAME.authorization.json"
if [ -e "$authorization" ] || [ -L "$authorization" ]; then exit 2; fi
authorization_tmp="$authorization.tmp.$$"
python3 -B -P -m \
  rondo_eval.publication_critic.full_model_training.plan094_cli \
  authorize-segment --snapshot "$RONDO_PLAN094_BUDGET_SNAPSHOT" \
  --maximum-seconds "$RONDO_PLAN094_MAX_SECONDS" \
  --compute-rate-usd-per-hour "$RONDO_PLAN094_COMPUTE_RATE_USD_PER_HOUR" \
  --storage-rate-usd-per-hour "$RONDO_PLAN094_STORAGE_RATE_USD_PER_HOUR" \
  > "$authorization_tmp"
chmod 600 "$authorization_tmp"
mv "$authorization_tmp" "$authorization"
authorization_tmp=""

data_root="$task_root/data-${RONDO_PLAN094_DATA_SHA256}"
data_receipt="$receipt_dir/data-${RONDO_PLAN094_DATA_SHA256}.json"
data_receipt_tmp="$data_receipt.tmp.$$"
if [ -e "$data_root" ] || [ -L "$data_root" ]; then
  if [ ! -d "$data_root" ] || [ -L "$data_root" ]; then exit 2; fi
  python3 -B -P -m rondo_eval.publication_critic.full_model_training.plan094_cli \
    verify-data --bundle "$data_root" > "$data_receipt_tmp"
else
  python3 -B -P -m rondo_eval.publication_critic.full_model_training.plan094_cli \
    extract-data-archive --archive "$data_archive" \
    --expected-sha256 "$RONDO_PLAN094_DATA_SHA256" --output "$data_root" \
    > "$data_receipt_tmp"
fi
publish_candidate "$data_receipt_tmp" "$data_receipt"

venv="$task_root/venv"
if [ ! -x "$venv/bin/python" ]; then
  python3 -B -m venv --system-site-packages "$venv"
fi
"$venv/bin/python" -B -m pip install --disable-pip-version-check \
  --upgrade-strategy only-if-needed -r \
  "$source_root/training/publication-critic-plan094/dependencies-v1.txt" >&3 2>&3
"$venv/bin/python" -B -m pip check >&3 2>&3
"$venv/bin/python" -B -c 'import torch; assert torch.__version__ == "2.8.0+cu128"' >&3 2>&3

environment_receipt="$receipt_dir/environment-${RONDO_PLAN094_SOURCE_SHA256}.json"
"$venv/bin/python" -B -P -m \
  rondo_eval.publication_critic.full_model_training.plan094_cli \
  capture-environment --output "$environment_receipt" >&3 2>&3

existing_model="${RONDO_PLAN094_EXISTING_MODEL_ROOT:-}"
if [ -n "$existing_model" ]; then
  model="$(realpath -e -- "$existing_model")"
  case "$model" in
    /workspace/rondo-plan082-*|/workspace/rondo-plan087-*) ;;
    *) exit 2 ;;
  esac
else
  model="$task_root/model-e51ea3e0"
  "$venv/bin/hf" download Skywork/Skywork-Reward-V2-Qwen3-1.7B \
    .gitattributes README.md added_tokens.json assets/skywork_logo.png \
    chat_template.jinja config.json merges.txt model.safetensors \
    special_tokens_map.json tokenizer.json tokenizer_config.json vocab.json \
    --revision e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc \
    --local-dir "$model" >&3 2>&3
fi
snapshot_receipt="$receipt_dir/snapshot-e51ea3e0.json"
snapshot_receipt_tmp="$snapshot_receipt.tmp.$$"
"$venv/bin/python" -B -P -m \
  rondo_eval.publication_critic.full_model_training.plan094_cli verify-snapshot \
  --snapshot "$model" \
  --model-lock "$source_root/eval/model-locks/publication-critic/skywork-reward-v2-qwen3-1.7b-e51ea3e0.json" \
  > "$snapshot_receipt_tmp"
publish_candidate "$snapshot_receipt_tmp" "$snapshot_receipt"

ready_receipt="$receipt_dir/bootstrap-ready-${RONDO_PLAN094_SOURCE_SHA256}-${RONDO_PLAN094_DATA_SHA256}.json"
"$venv/bin/python" -B -P -m \
  rondo_eval.publication_critic.full_model_training.plan094_cli \
  publish-bootstrap-ready --source-receipt "$source_receipt" \
  --data-receipt "$data_receipt" --snapshot-receipt "$snapshot_receipt" \
  --environment-receipt "$environment_receipt" --source-root "$source_root" \
  --data-root "$data_root" --model-root "$model" --output "$ready_receipt"
