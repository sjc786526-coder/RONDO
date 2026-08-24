#!/usr/bin/env bash
set -eu

# Run only inside the one separately authorized Plan 060 Pod. The caller owns
# logging and supplies the immutable image identity observed from the control
# plane. This script never reads a repository env file or performs HF login.
: "${RONDO_PLAN060_BUNDLE:?set the verified unpacked bundle root}"
: "${RONDO_PLAN060_TASK_ROOT:?set the persistent task root}"
: "${RONDO_PLAN060_IMAGE_ID:?set the observed image name or digest}"
: "${RONDO_PLAN060_STATUS:?set a unique bootstrap status file}"

case "$RONDO_PLAN060_TASK_ROOT" in
  /workspace/*) ;;
  *) echo '{"status":"failed","code":"task_root_outside_workspace"}' >&2; exit 2 ;;
esac
if ! command -v realpath >/dev/null 2>&1; then
  echo '{"status":"failed","code":"realpath_missing"}' >&2
  exit 2
fi
task_root="$(realpath -e -- "$RONDO_PLAN060_TASK_ROOT")" || {
  echo '{"status":"failed","code":"task_root_invalid"}' >&2; exit 2
}
case "$task_root" in
  /workspace/*) ;;
  *) echo '{"status":"failed","code":"task_root_outside_workspace"}' >&2; exit 2 ;;
esac
require_persistent_path() {
  candidate="$(realpath -m -- "$1")" || return 1
  case "$candidate" in
    "$task_root"/*) printf '%s\n' "$candidate" ;;
    *) return 1 ;;
  esac
}

bundle="$RONDO_PLAN060_BUNDLE"
bundle="$(require_persistent_path "$bundle")" || {
  echo '{"status":"failed","code":"bundle_outside_task_root"}' >&2; exit 2
}
status="$RONDO_PLAN060_STATUS"
status="$(require_persistent_path "$status")" || {
  echo '{"status":"failed","code":"status_outside_task_root"}' >&2; exit 2
}
venv="$task_root/venv"
wheels="$task_root/wheels"
model="$task_root/model"
contracts="$bundle/training/publication-critic-plan060"

umask 077
export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$task_root" "$wheels"
case "$status" in
  "$task_root"/controller/*.json) ;;
  *) echo '{"status":"failed","code":"bootstrap_status_outside_controller"}' >&2; exit 2 ;;
esac
if [ -e "$status" ] || [ -L "$status" ]; then
  echo '{"status":"failed","code":"bootstrap_status_already_exists"}' >&2
  exit 2
fi

write_bootstrap_status() {
  rc=$?
  trap - EXIT
  temporary="$status.tmp.$$"
  if [ "$rc" -eq 0 ]; then
    printf '%s\n' '{"status":"completed","mode":"bootstrap"}' > "$temporary"
  else
    printf '{"status":"failed","mode":"bootstrap","exit_code":%s}\n' "$rc" \
      > "$temporary"
  fi
  mv "$temporary" "$status"
  exit "$rc"
}
trap write_bootstrap_status EXIT

PYTHONPATH="$bundle/eval" python3 -B -P -m \
  rondo_eval.publication_critic.full_model_training verify-bundle \
  --bundle "$bundle"

if [ ! -x "$venv/bin/python" ]; then
  python3 -B -m venv --system-site-packages "$venv"
fi

"$venv/bin/python" -B -m pip install --disable-pip-version-check \
  --upgrade-strategy only-if-needed \
  'huggingface-hub[cli]==0.36.2' \
  'safetensors==0.5.3' \
  'transformers==4.52.3'

flash_wheel="$wheels/flashoptim-0.1.4-py3-none-any.whl"
if [ ! -f "$flash_wheel" ]; then
  "$venv/bin/python" -B -m pip download --disable-pip-version-check \
    --no-deps --only-binary=:all: --dest "$wheels" 'flashoptim==0.1.4'
fi
printf '%s  %s\n' \
  '8a4a3f2528fbda419d4f4dd0c9debb3de22bd0a45969bee2eb5a58185d3bd451' \
  "$flash_wheel" | sha256sum --check --status
"$venv/bin/python" -B -m pip install --disable-pip-version-check \
  --no-deps "$flash_wheel"
"$venv/bin/python" -B -m pip check

unset HF_TOKEN HUGGING_FACE_HUB_TOKEN HUGGINGFACEHUB_API_TOKEN
export HF_HOME="$task_root/hf-home"
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_HUB_DISABLE_TELEMETRY=1

"$venv/bin/hf" download \
  Skywork/Skywork-Reward-V2-Qwen3-1.7B \
  added_tokens.json chat_template.jinja config.json merges.txt \
  model.safetensors special_tokens_map.json tokenizer.json \
  tokenizer_config.json vocab.json \
  --revision e51ea3e08fb81326c3b812a7ff0cb9cee83e59cc \
  --local-dir "$model"

(cd "$model" && sha256sum --check --strict \
  "$contracts/model-download-sha256.txt")

"$venv/bin/python" -B -m pip freeze --all \
  > "$task_root/dependency-freeze-observed.txt"
chmod 600 "$task_root/dependency-freeze-observed.txt"

PYTHONPATH="$bundle/eval" "$venv/bin/python" -B -P -m \
  rondo_eval.publication_critic.full_model_training capture-dependencies \
  --bundle "$bundle" \
  --container-image "$RONDO_PLAN060_IMAGE_ID" \
  --status commissioning_observed \
  --output "$task_root/dependency-identity-observed.json"

printf '%s\n' '{"status":"ready","model":"exact_revision_verified"}'
