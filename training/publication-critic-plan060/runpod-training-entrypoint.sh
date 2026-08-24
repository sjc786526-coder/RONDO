#!/usr/bin/env bash
set -eu

# Run one training phase in one OS process inside the task's only Pod. The
# controller launches this script separately for start and resume and owns
# nohup/PID/log monitoring.
: "${RONDO_PLAN060_TASK_ROOT:?set persistent task root}"
: "${RONDO_PLAN060_STATUS:?set unique phase status file}"

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
RONDO_PLAN060_TASK_ROOT="$task_root"
require_persistent_path() {
  candidate="$(realpath -m -- "$1")" || return 1
  case "$candidate" in
    "$task_root"/*) printf '%s\n' "$candidate" ;;
    *) return 1 ;;
  esac
}
RONDO_PLAN060_STATUS="$(require_persistent_path "$RONDO_PLAN060_STATUS")" || {
  echo '{"status":"failed","code":"status_outside_task_root"}' >&2; exit 2
}

case "$RONDO_PLAN060_STATUS" in
  "$RONDO_PLAN060_TASK_ROOT"/controller/*.json) ;;
  *) echo '{"status":"failed","code":"status_outside_controller"}' >&2; exit 2 ;;
esac
if [ -e "$RONDO_PLAN060_STATUS" ] || [ -L "$RONDO_PLAN060_STATUS" ]; then
  echo '{"status":"failed","code":"status_already_exists"}' >&2
  exit 2
fi

umask 077
write_training_status() {
  rc=$?
  trap - EXIT
  mode="${RONDO_PLAN060_MODE:-unknown}"
  temporary="$RONDO_PLAN060_STATUS.tmp.$$"
  if [ "$rc" -eq 0 ]; then
    printf '{"status":"completed","mode":"%s"}\n' "$mode" > "$temporary"
  else
    printf '{"status":"failed","mode":"%s","exit_code":%s}\n' \
      "$mode" "$rc" > "$temporary"
  fi
  mv "$temporary" "$RONDO_PLAN060_STATUS"
  exit "$rc"
}
trap write_training_status EXIT

: "${RONDO_PLAN060_BUNDLE:?set verified unpacked bundle root}"
: "${RONDO_PLAN060_IMAGE_ID:?set observed image identity}"
: "${RONDO_PLAN060_MODE:?set commission-start, commission-resume, formal-start, or formal-resume}"
: "${RONDO_PLAN060_OUTPUT:?set phase output directory}"
: "${RONDO_PLAN060_WINNER_LOCK:?set immutable winner lock}"
RONDO_PLAN060_MAX_SECONDS="${RONDO_PLAN060_MAX_SECONDS:-3600}"

case "$RONDO_PLAN060_MAX_SECONDS" in
  ''|*[!0-9]*) echo '{"status":"failed","code":"invalid_timeout"}' >&2; exit 2 ;;
esac
if [ "$RONDO_PLAN060_MAX_SECONDS" -le 0 ]; then
  echo '{"status":"failed","code":"invalid_timeout"}' >&2
  exit 2
fi

bundle="$RONDO_PLAN060_BUNDLE"
bundle="$(require_persistent_path "$bundle")" || {
  echo '{"status":"failed","code":"bundle_outside_task_root"}' >&2; exit 2
}
RONDO_PLAN060_OUTPUT="$(require_persistent_path "$RONDO_PLAN060_OUTPUT")" || {
  echo '{"status":"failed","code":"output_outside_task_root"}' >&2; exit 2
}
RONDO_PLAN060_WINNER_LOCK="$(require_persistent_path "$RONDO_PLAN060_WINNER_LOCK")" || {
  echo '{"status":"failed","code":"winner_lock_outside_task_root"}' >&2; exit 2
}
python="$task_root/venv/bin/python"
model="${RONDO_PLAN060_MODEL_SNAPSHOT:-$task_root/model}"
model="$(require_persistent_path "$model")" || {
  echo '{"status":"failed","code":"model_outside_task_root"}' >&2; exit 2
}
recipe="${RONDO_PLAN060_RECIPE:-$bundle/training/publication-critic-plan060/recipe-candidate-v1.json}"
recipe="$(require_persistent_path "$recipe")" || {
  echo '{"status":"failed","code":"recipe_outside_task_root"}' >&2; exit 2
}

if [ ! -x "$python" ]; then
  echo '{"status":"failed","code":"training_python_missing"}' >&2
  exit 2
fi

export PYTHONDONTWRITEBYTECODE=1
mkdir -p "$RONDO_PLAN060_TASK_ROOT/triton-cache"
export PYTHONPATH="$bundle/eval"
export TRITON_CACHE_DIR="$RONDO_PLAN060_TASK_ROOT/triton-cache"
export HF_HOME="$RONDO_PLAN060_TASK_ROOT/hf-home"
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_HUB_DISABLE_TELEMETRY=1
unset HF_TOKEN HUGGING_FACE_HUB_TOKEN HUGGINGFACEHUB_API_TOKEN

"$python" -B -P -m rondo_eval.publication_critic.full_model_training \
  verify-bundle --bundle "$bundle"

set -- "$RONDO_PLAN060_MODE" \
  --bundle "$bundle" \
  --model-snapshot "$model" \
  --output "$RONDO_PLAN060_OUTPUT" \
  --recipe "$recipe" \
  --winner-lock "$RONDO_PLAN060_WINNER_LOCK" \
  --container-image "$RONDO_PLAN060_IMAGE_ID"

case "$RONDO_PLAN060_MODE" in
  commission-start) ;;
  commission-resume)
    : "${RONDO_PLAN060_CHECKPOINT:?commission-resume requires checkpoint}"
    RONDO_PLAN060_CHECKPOINT="$(require_persistent_path "$RONDO_PLAN060_CHECKPOINT")" || {
      echo '{"status":"failed","code":"checkpoint_outside_task_root"}' >&2; exit 2
    }
    set -- "$@" --checkpoint "$RONDO_PLAN060_CHECKPOINT"
    ;;
  formal-start)
    : "${RONDO_PLAN060_DEPENDENCY_IDENTITY:?formal-start requires dependency identity}"
    : "${RONDO_PLAN060_DEPENDENCY_FREEZE:?formal-start requires dependency freeze}"
    RONDO_PLAN060_DEPENDENCY_IDENTITY="$(require_persistent_path "$RONDO_PLAN060_DEPENDENCY_IDENTITY")" || {
      echo '{"status":"failed","code":"dependency_identity_outside_task_root"}' >&2; exit 2
    }
    RONDO_PLAN060_DEPENDENCY_FREEZE="$(require_persistent_path "$RONDO_PLAN060_DEPENDENCY_FREEZE")" || {
      echo '{"status":"failed","code":"dependency_freeze_outside_task_root"}' >&2; exit 2
    }
    set -- "$@" \
      --dependency-identity "$RONDO_PLAN060_DEPENDENCY_IDENTITY" \
      --dependency-freeze "$RONDO_PLAN060_DEPENDENCY_FREEZE"
    ;;
  formal-resume)
    : "${RONDO_PLAN060_CHECKPOINT:?formal-resume requires checkpoint}"
    : "${RONDO_PLAN060_DEPENDENCY_IDENTITY:?formal-resume requires dependency identity}"
    : "${RONDO_PLAN060_DEPENDENCY_FREEZE:?formal-resume requires dependency freeze}"
    RONDO_PLAN060_CHECKPOINT="$(require_persistent_path "$RONDO_PLAN060_CHECKPOINT")" || {
      echo '{"status":"failed","code":"checkpoint_outside_task_root"}' >&2; exit 2
    }
    RONDO_PLAN060_DEPENDENCY_IDENTITY="$(require_persistent_path "$RONDO_PLAN060_DEPENDENCY_IDENTITY")" || {
      echo '{"status":"failed","code":"dependency_identity_outside_task_root"}' >&2; exit 2
    }
    RONDO_PLAN060_DEPENDENCY_FREEZE="$(require_persistent_path "$RONDO_PLAN060_DEPENDENCY_FREEZE")" || {
      echo '{"status":"failed","code":"dependency_freeze_outside_task_root"}' >&2; exit 2
    }
    set -- "$@" \
      --checkpoint "$RONDO_PLAN060_CHECKPOINT" \
      --dependency-identity "$RONDO_PLAN060_DEPENDENCY_IDENTITY" \
      --dependency-freeze "$RONDO_PLAN060_DEPENDENCY_FREEZE"
    ;;
  *) echo '{"status":"failed","code":"invalid_mode"}' >&2; exit 2 ;;
esac

set +e
timeout --signal=TERM --kill-after=120 "$RONDO_PLAN060_MAX_SECONDS" \
  "$python" -B -P -m rondo_eval.publication_critic.full_model_training "$@"
exit_code=$?
set -e
exit "$exit_code"
