#!/usr/bin/env bash
set -eu

: "${RONDO_PLAN066_TASK_ROOT:?set persistent task root}"
: "${RONDO_PLAN066_STATUS:?set unique phase status file}"
: "${RONDO_PLAN066_BUNDLE:?set verified bundle root}"
: "${RONDO_PLAN066_IMAGE_ID:?set observed image identity}"
: "${RONDO_PLAN066_MODE:?set a Plan 066 training mode}"
: "${RONDO_PLAN066_OUTPUT:?set output root}"
: "${RONDO_PLAN066_WINNER_LOCK:?set winner lock}"
RONDO_PLAN066_MAX_SECONDS="${RONDO_PLAN066_MAX_SECONDS:-7200}"

case "$RONDO_PLAN066_TASK_ROOT" in /workspace/*) ;; *) exit 2 ;; esac
case "$RONDO_PLAN066_MAX_SECONDS" in ''|*[!0-9]*) exit 2 ;; esac
if [ "$RONDO_PLAN066_MAX_SECONDS" -le 0 ]; then exit 2; fi
task_root="$(realpath -e -- "$RONDO_PLAN066_TASK_ROOT")"
case "$task_root" in /workspace/*) ;; *) exit 2 ;; esac
require_task_path() {
  candidate="$(realpath -m -- "$1")" || return 1
  case "$candidate" in "$task_root"/*) printf '%s\n' "$candidate" ;; *) return 1 ;; esac
}
bundle="$(require_task_path "$RONDO_PLAN066_BUNDLE")" || exit 2
output="$(require_task_path "$RONDO_PLAN066_OUTPUT")" || exit 2
winner="$(require_task_path "$RONDO_PLAN066_WINNER_LOCK")" || exit 2
status="$(require_task_path "$RONDO_PLAN066_STATUS")" || exit 2
case "$status" in "$task_root"/controller/*.json) ;; *) exit 2 ;; esac
if [ -e "$status" ] || [ -L "$status" ]; then exit 2; fi

umask 077
write_status() {
  rc=$?
  trap - EXIT
  temporary="$status.tmp.$$"
  if [ "$rc" -eq 0 ]; then
    printf '{"status":"completed","mode":"%s"}\n' "$RONDO_PLAN066_MODE" > "$temporary"
  else
    printf '{"status":"failed","mode":"%s","exit_code":%s}\n' "$RONDO_PLAN066_MODE" "$rc" > "$temporary"
  fi
  mv "$temporary" "$status"
  exit "$rc"
}
trap write_status EXIT

python="$task_root/venv/bin/python"
model="$(require_task_path "${RONDO_PLAN066_MODEL_SNAPSHOT:-$task_root/model}")" || exit 2
recipe="$(require_task_path "${RONDO_PLAN066_RECIPE:-$bundle/training/publication-critic-plan066/recipe-v1.json}")" || exit 2
if [ ! -x "$python" ]; then exit 2; fi
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$bundle/eval"
export TRITON_CACHE_DIR="$task_root/triton-cache"
export HF_HOME="$task_root/hf-home"
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_HUB_DISABLE_TELEMETRY=1
unset HF_TOKEN HUGGING_FACE_HUB_TOKEN HUGGINGFACEHUB_API_TOKEN

"$python" -B -P -m rondo_eval.publication_critic.full_model_training verify-bundle --bundle "$bundle"
set -- "$RONDO_PLAN066_MODE" --bundle "$bundle" --model-snapshot "$model" \
  --output "$output" --recipe "$recipe" --winner-lock "$winner" \
  --container-image "$RONDO_PLAN066_IMAGE_ID"
case "$RONDO_PLAN066_MODE" in
  plan066-commission-start) ;;
  plan066-commission-resume)
    checkpoint="$(require_task_path "${RONDO_PLAN066_CHECKPOINT:?set checkpoint}")" || exit 2
    set -- "$@" --checkpoint "$checkpoint"
    ;;
  plan066-formal-start)
    dependency="$(require_task_path "${RONDO_PLAN066_DEPENDENCY_IDENTITY:?set dependency identity}")" || exit 2
    freeze="$(require_task_path "${RONDO_PLAN066_DEPENDENCY_FREEZE:?set dependency freeze}")" || exit 2
    set -- "$@" --dependency-identity "$dependency" --dependency-freeze "$freeze"
    ;;
  plan066-formal-resume)
    checkpoint="$(require_task_path "${RONDO_PLAN066_CHECKPOINT:?set checkpoint}")" || exit 2
    dependency="$(require_task_path "${RONDO_PLAN066_DEPENDENCY_IDENTITY:?set dependency identity}")" || exit 2
    freeze="$(require_task_path "${RONDO_PLAN066_DEPENDENCY_FREEZE:?set dependency freeze}")" || exit 2
    set -- "$@" --checkpoint "$checkpoint" --dependency-identity "$dependency" --dependency-freeze "$freeze"
    ;;
  *) exit 2 ;;
esac
set +e
timeout --signal=TERM --kill-after=120 "$RONDO_PLAN066_MAX_SECONDS" \
  "$python" -B -P -m rondo_eval.publication_critic.full_model_training "$@"
rc=$?
set -e
exit "$rc"
