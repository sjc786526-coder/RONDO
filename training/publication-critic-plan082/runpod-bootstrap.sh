#!/usr/bin/env bash
set -eu
umask 077

: "${RONDO_PLAN082_TASK_ROOT:?set the mounted Plan 082 task root}"
: "${RONDO_PLAN082_SOURCE_ROOT:?set a new extracted source root}"
: "${RONDO_PLAN082_SOURCE_ARCHIVE:?set the uploaded source archive}"
: "${RONDO_PLAN082_SOURCE_SHA256:?set the source archive SHA-256}"
: "${RONDO_PLAN082_SOURCE_COMMIT:?set the frozen 40-hex source commit}"
: "${RONDO_PLAN082_DATA_ARCHIVE:?set the uploaded data archive}"
: "${RONDO_PLAN082_DATA_SHA256:?set the data archive SHA-256}"

case "$RONDO_PLAN082_TASK_ROOT" in /workspace/*) ;; *) exit 2 ;; esac
task_root="$(realpath -e -- "$RONDO_PLAN082_TASK_ROOT")"
case "$task_root" in /workspace/*) ;; *) exit 2 ;; esac
source_root="$(realpath -m -- "$RONDO_PLAN082_SOURCE_ROOT")"
source_archive="$(realpath -e -- "$RONDO_PLAN082_SOURCE_ARCHIVE")"
data_archive="$(realpath -e -- "$RONDO_PLAN082_DATA_ARCHIVE")"
for path in "$source_root" "$source_archive" "$data_archive"; do
  case "$path" in "$task_root"/*) ;; *) exit 2 ;; esac
done
for digest in "$RONDO_PLAN082_SOURCE_SHA256" "$RONDO_PLAN082_DATA_SHA256"; do
  case "$digest" in *[!0-9a-f]*) exit 2 ;; esac
  if [ "${#digest}" -ne 64 ]; then exit 2; fi
done
case "$RONDO_PLAN082_SOURCE_COMMIT" in *[!0-9a-f]*) exit 2 ;; esac
if [ "${#RONDO_PLAN082_SOURCE_COMMIT}" -ne 40 ]; then exit 2; fi

printf '%s  %s\n' "$RONDO_PLAN082_SOURCE_SHA256" "$source_archive" | sha256sum --check --status
printf '%s  %s\n' "$RONDO_PLAN082_DATA_SHA256" "$data_archive" | sha256sum --check --status
export PYTHONDONTWRITEBYTECODE=1
receipt_dir="$task_root/receipts"
mkdir -m 700 -p "$receipt_dir"
source_receipt="$receipt_dir/source-${RONDO_PLAN082_SOURCE_SHA256}.json"
receipt_tmp="$source_receipt.tmp.$$"
bootstrap_root="$task_root/.source-bootstrap-${RONDO_PLAN082_SOURCE_SHA256}-$$"
cleanup() {
  rm -f -- "$receipt_tmp"
  if [ -d "$bootstrap_root" ] && [ ! -L "$bootstrap_root" ]; then
    rm -rf -- "$bootstrap_root"
  fi
}
trap cleanup EXIT

if [ -e "$source_root" ] || [ -L "$source_root" ]; then
  if [ ! -d "$source_root" ] || [ -L "$source_root" ]; then exit 2; fi
  export PYTHONPATH="$source_root/eval"
  python3 -B -P -m rondo_eval.publication_critic.full_model_training.plan082_cli \
    verify-source-archive --archive "$source_archive" \
    --source-root "$source_root" --exact-tree \
    --expected-commit "$RONDO_PLAN082_SOURCE_COMMIT" > "$receipt_tmp"
else
  mkdir -m 700 "$bootstrap_root"
  tar --no-same-owner --no-same-permissions -xf "$source_archive" \
    -C "$bootstrap_root"
  export PYTHONPATH="$bootstrap_root/eval"
  python3 -B -P -m rondo_eval.publication_critic.full_model_training.plan082_cli \
    verify-source-archive --archive "$source_archive" \
    --source-root "$bootstrap_root" --exact-tree \
    --expected-commit "$RONDO_PLAN082_SOURCE_COMMIT" > /dev/null
  python3 -B -P -m rondo_eval.publication_critic.full_model_training.plan082_cli \
    extract-source-archive --archive "$source_archive" \
    --expected-sha256 "$RONDO_PLAN082_SOURCE_SHA256" \
    --expected-commit "$RONDO_PLAN082_SOURCE_COMMIT" \
    --output "$source_root" > "$receipt_tmp"
  export PYTHONPATH="$source_root/eval"
fi
if [ -e "$source_receipt" ] || [ -L "$source_receipt" ]; then
  if [ ! -f "$source_receipt" ] || [ -L "$source_receipt" ]; then exit 2; fi
  cmp --silent -- "$source_receipt" "$receipt_tmp" || exit 2
  rm -f -- "$receipt_tmp"
else
  chmod 600 "$receipt_tmp"
  mv "$receipt_tmp" "$source_receipt"
fi

data_root="$task_root/data-${RONDO_PLAN082_DATA_SHA256}"
if [ -e "$data_root" ] || [ -L "$data_root" ]; then
  if [ ! -d "$data_root" ] || [ -L "$data_root" ]; then exit 2; fi
  python3 -B -P -m rondo_eval.publication_critic.full_model_training.plan082_cli \
    verify-data --bundle "$data_root" > /dev/null
else
  python3 -B -P -m rondo_eval.publication_critic.full_model_training.plan082_cli \
    extract-data-archive --archive "$data_archive" \
    --expected-sha256 "$RONDO_PLAN082_DATA_SHA256" --output "$data_root" \
    > /dev/null
fi

venv="$task_root/venv"
if [ ! -x "$venv/bin/python" ]; then
  python3 -B -m venv --system-site-packages "$venv"
fi
"$venv/bin/python" -B -m pip install --disable-pip-version-check \
  --upgrade-strategy only-if-needed -r \
  "$source_root/training/publication-critic-plan082/dependencies-v1.txt"
"$venv/bin/python" -B -m pip check
"$venv/bin/python" -B -c 'import torch; assert torch.__version__.split("+", 1)[0] == "2.8.0"'

unset HF_TOKEN HUGGING_FACE_HUB_TOKEN HUGGINGFACEHUB_API_TOKEN
export HF_HOME="$task_root/hf-home"
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_HUB_DISABLE_TELEMETRY=1
export HF_HUB_ENABLE_HF_TRANSFER=0
model="$task_root/model-e51ea3e0"
"$venv/bin/hf" download Skywork/Skywork-Reward-V2-Qwen3-1.7B \
  .gitattributes README.md added_tokens.json assets/skywork_logo.png \
  chat_template.jinja config.json merges.txt model.safetensors \
  special_tokens_map.json tokenizer.json tokenizer_config.json vocab.json \
  --revision e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc \
  --local-dir "$model"
"$venv/bin/python" -B -P -m \
  rondo_eval.publication_critic.full_model_training.plan082_cli verify-snapshot \
  --snapshot "$model" \
  --model-lock "$source_root/eval/model-locks/publication-critic/skywork-reward-v2-qwen3-1.7b-e51ea3e0.json"
printf '{"status":"ready","source_receipt":"%s","data_root":"%s","model_root":"%s"}\n' \
  "$source_receipt" "$data_root" "$model"
