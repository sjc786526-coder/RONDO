#!/usr/bin/env bash
set -eu

# Small Pod-local detached launcher. It creates only task-scoped PID/log/status
# files; the bootstrap and training entrypoint own the completed status body.
: "${RONDO_PLAN060_BUNDLE:?set verified unpacked bundle root}"
: "${RONDO_PLAN060_TASK_ROOT:?set persistent task root}"
: "${RONDO_PLAN060_IMAGE_ID:?set observed image identity}"
: "${RONDO_PLAN060_MODE:?set bootstrap or one training mode}"
: "${RONDO_PLAN060_LAUNCH_NAME:?set a unique task-local launch name}"
RONDO_PLAN060_MAX_SECONDS="${RONDO_PLAN060_MAX_SECONDS:-1800}"

case "$RONDO_PLAN060_TASK_ROOT" in
  /workspace/*) ;;
  *) echo '{"status":"failed","code":"task_root_outside_workspace"}' >&2; exit 2 ;;
esac
case "$RONDO_PLAN060_LAUNCH_NAME" in
  ''|*[!a-zA-Z0-9._-]*) echo '{"status":"failed","code":"launch_name_invalid"}' >&2; exit 2 ;;
esac
case "$RONDO_PLAN060_MAX_SECONDS" in
  ''|*[!0-9]*) echo '{"status":"failed","code":"invalid_timeout"}' >&2; exit 2 ;;
esac
if [ "$RONDO_PLAN060_MAX_SECONDS" -le 0 ]; then
  echo '{"status":"failed","code":"invalid_timeout"}' >&2
  exit 2
fi
if ! command -v realpath >/dev/null 2>&1 \
  || ! command -v setsid >/dev/null 2>&1 \
  || ! command -v flock >/dev/null 2>&1; then
  echo '{"status":"failed","code":"launcher_runtime_missing"}' >&2
  exit 2
fi

task_root="$(realpath -e -- "$RONDO_PLAN060_TASK_ROOT")" || {
  echo '{"status":"failed","code":"task_root_invalid"}' >&2
  exit 2
}
if [ ! -d "$task_root" ]; then
  echo '{"status":"failed","code":"task_root_invalid"}' >&2
  exit 2
fi
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

bundle="$(realpath -e -- "$RONDO_PLAN060_BUNDLE")" || {
  echo '{"status":"failed","code":"bundle_path_invalid"}' >&2
  exit 2
}
bundle="$(require_persistent_path "$bundle")" || {
  echo '{"status":"failed","code":"bundle_outside_task_root"}' >&2
  exit 2
}
if [ ! -d "$bundle" ]; then
  echo '{"status":"failed","code":"bundle_path_invalid"}' >&2
  exit 2
fi
RONDO_PLAN060_BUNDLE="$bundle"

umask 077
controller="$RONDO_PLAN060_TASK_ROOT/controller"
mkdir -p "$controller"
status="$controller/$RONDO_PLAN060_LAUNCH_NAME.status.json"
log="$controller/$RONDO_PLAN060_LAUNCH_NAME.log"
pidfile="$controller/$RONDO_PLAN060_LAUNCH_NAME.pid"
for path in "$status" "$log" "$pidfile"; do
  if [ -e "$path" ] || [ -L "$path" ]; then
    echo '{"status":"failed","code":"launch_artifact_already_exists"}' >&2
    exit 2
  fi
done

set -- env \
  RONDO_PLAN060_BUNDLE="$RONDO_PLAN060_BUNDLE" \
  RONDO_PLAN060_TASK_ROOT="$RONDO_PLAN060_TASK_ROOT" \
  RONDO_PLAN060_IMAGE_ID="$RONDO_PLAN060_IMAGE_ID" \
  RONDO_PLAN060_STATUS="$status"

case "$RONDO_PLAN060_MODE" in
  bootstrap)
    target="$RONDO_PLAN060_BUNDLE/training/publication-critic-plan060/runpod-bootstrap.sh"
    ;;
  commission-start)
    : "${RONDO_PLAN060_OUTPUT:?training launch requires output}"
    : "${RONDO_PLAN060_WINNER_LOCK:?training launch requires winner lock}"
    RONDO_PLAN060_OUTPUT="$(require_persistent_path "$RONDO_PLAN060_OUTPUT")" || {
      echo '{"status":"failed","code":"output_outside_task_root"}' >&2; exit 2
    }
    RONDO_PLAN060_WINNER_LOCK="$(require_persistent_path "$RONDO_PLAN060_WINNER_LOCK")" || {
      echo '{"status":"failed","code":"winner_lock_outside_task_root"}' >&2; exit 2
    }
    set -- "$@" \
      RONDO_PLAN060_MODE="$RONDO_PLAN060_MODE" \
      RONDO_PLAN060_OUTPUT="$RONDO_PLAN060_OUTPUT" \
      RONDO_PLAN060_WINNER_LOCK="$RONDO_PLAN060_WINNER_LOCK" \
      RONDO_PLAN060_MAX_SECONDS="$RONDO_PLAN060_MAX_SECONDS"
    target="$RONDO_PLAN060_BUNDLE/training/publication-critic-plan060/runpod-training-entrypoint.sh"
    ;;
  commission-resume)
    : "${RONDO_PLAN060_OUTPUT:?training launch requires output}"
    : "${RONDO_PLAN060_CHECKPOINT:?commission-resume requires checkpoint}"
    : "${RONDO_PLAN060_WINNER_LOCK:?training launch requires winner lock}"
    RONDO_PLAN060_OUTPUT="$(require_persistent_path "$RONDO_PLAN060_OUTPUT")" || {
      echo '{"status":"failed","code":"output_outside_task_root"}' >&2; exit 2
    }
    RONDO_PLAN060_CHECKPOINT="$(require_persistent_path "$RONDO_PLAN060_CHECKPOINT")" || {
      echo '{"status":"failed","code":"checkpoint_outside_task_root"}' >&2; exit 2
    }
    RONDO_PLAN060_WINNER_LOCK="$(require_persistent_path "$RONDO_PLAN060_WINNER_LOCK")" || {
      echo '{"status":"failed","code":"winner_lock_outside_task_root"}' >&2; exit 2
    }
    set -- "$@" \
      RONDO_PLAN060_MODE="$RONDO_PLAN060_MODE" \
      RONDO_PLAN060_OUTPUT="$RONDO_PLAN060_OUTPUT" \
      RONDO_PLAN060_CHECKPOINT="$RONDO_PLAN060_CHECKPOINT" \
      RONDO_PLAN060_WINNER_LOCK="$RONDO_PLAN060_WINNER_LOCK" \
      RONDO_PLAN060_MAX_SECONDS="$RONDO_PLAN060_MAX_SECONDS"
    target="$RONDO_PLAN060_BUNDLE/training/publication-critic-plan060/runpod-training-entrypoint.sh"
    ;;
  formal-start)
    : "${RONDO_PLAN060_OUTPUT:?training launch requires output}"
    : "${RONDO_PLAN060_WINNER_LOCK:?training launch requires winner lock}"
    : "${RONDO_PLAN060_DEPENDENCY_IDENTITY:?formal-start requires dependency identity}"
    : "${RONDO_PLAN060_DEPENDENCY_FREEZE:?formal-start requires dependency freeze}"
    RONDO_PLAN060_OUTPUT="$(require_persistent_path "$RONDO_PLAN060_OUTPUT")" || {
      echo '{"status":"failed","code":"output_outside_task_root"}' >&2; exit 2
    }
    RONDO_PLAN060_DEPENDENCY_IDENTITY="$(require_persistent_path "$RONDO_PLAN060_DEPENDENCY_IDENTITY")" || {
      echo '{"status":"failed","code":"dependency_identity_outside_task_root"}' >&2; exit 2
    }
    RONDO_PLAN060_DEPENDENCY_FREEZE="$(require_persistent_path "$RONDO_PLAN060_DEPENDENCY_FREEZE")" || {
      echo '{"status":"failed","code":"dependency_freeze_outside_task_root"}' >&2; exit 2
    }
    RONDO_PLAN060_WINNER_LOCK="$(require_persistent_path "$RONDO_PLAN060_WINNER_LOCK")" || {
      echo '{"status":"failed","code":"winner_lock_outside_task_root"}' >&2; exit 2
    }
    set -- "$@" \
      RONDO_PLAN060_MODE="$RONDO_PLAN060_MODE" \
      RONDO_PLAN060_OUTPUT="$RONDO_PLAN060_OUTPUT" \
      RONDO_PLAN060_WINNER_LOCK="$RONDO_PLAN060_WINNER_LOCK" \
      RONDO_PLAN060_DEPENDENCY_IDENTITY="$RONDO_PLAN060_DEPENDENCY_IDENTITY" \
      RONDO_PLAN060_DEPENDENCY_FREEZE="$RONDO_PLAN060_DEPENDENCY_FREEZE" \
      RONDO_PLAN060_MAX_SECONDS="$RONDO_PLAN060_MAX_SECONDS"
    target="$RONDO_PLAN060_BUNDLE/training/publication-critic-plan060/runpod-training-entrypoint.sh"
    ;;
  formal-resume)
    : "${RONDO_PLAN060_OUTPUT:?training launch requires output}"
    : "${RONDO_PLAN060_CHECKPOINT:?formal-resume requires checkpoint}"
    : "${RONDO_PLAN060_WINNER_LOCK:?training launch requires winner lock}"
    : "${RONDO_PLAN060_DEPENDENCY_IDENTITY:?formal-resume requires dependency identity}"
    : "${RONDO_PLAN060_DEPENDENCY_FREEZE:?formal-resume requires dependency freeze}"
    RONDO_PLAN060_OUTPUT="$(require_persistent_path "$RONDO_PLAN060_OUTPUT")" || {
      echo '{"status":"failed","code":"output_outside_task_root"}' >&2; exit 2
    }
    RONDO_PLAN060_CHECKPOINT="$(require_persistent_path "$RONDO_PLAN060_CHECKPOINT")" || {
      echo '{"status":"failed","code":"checkpoint_outside_task_root"}' >&2; exit 2
    }
    RONDO_PLAN060_DEPENDENCY_IDENTITY="$(require_persistent_path "$RONDO_PLAN060_DEPENDENCY_IDENTITY")" || {
      echo '{"status":"failed","code":"dependency_identity_outside_task_root"}' >&2; exit 2
    }
    RONDO_PLAN060_DEPENDENCY_FREEZE="$(require_persistent_path "$RONDO_PLAN060_DEPENDENCY_FREEZE")" || {
      echo '{"status":"failed","code":"dependency_freeze_outside_task_root"}' >&2; exit 2
    }
    RONDO_PLAN060_WINNER_LOCK="$(require_persistent_path "$RONDO_PLAN060_WINNER_LOCK")" || {
      echo '{"status":"failed","code":"winner_lock_outside_task_root"}' >&2; exit 2
    }
    set -- "$@" \
      RONDO_PLAN060_MODE="$RONDO_PLAN060_MODE" \
      RONDO_PLAN060_OUTPUT="$RONDO_PLAN060_OUTPUT" \
      RONDO_PLAN060_CHECKPOINT="$RONDO_PLAN060_CHECKPOINT" \
      RONDO_PLAN060_WINNER_LOCK="$RONDO_PLAN060_WINNER_LOCK" \
      RONDO_PLAN060_DEPENDENCY_IDENTITY="$RONDO_PLAN060_DEPENDENCY_IDENTITY" \
      RONDO_PLAN060_DEPENDENCY_FREEZE="$RONDO_PLAN060_DEPENDENCY_FREEZE" \
      RONDO_PLAN060_MAX_SECONDS="$RONDO_PLAN060_MAX_SECONDS"
    target="$RONDO_PLAN060_BUNDLE/training/publication-critic-plan060/runpod-training-entrypoint.sh"
    ;;
  *) echo '{"status":"failed","code":"invalid_mode"}' >&2; exit 2 ;;
esac

if [ -n "${RONDO_PLAN060_RECIPE:-}" ] && [ "$RONDO_PLAN060_MODE" != bootstrap ]; then
  RONDO_PLAN060_RECIPE="$(require_persistent_path "$RONDO_PLAN060_RECIPE")" || {
    echo '{"status":"failed","code":"recipe_outside_task_root"}' >&2; exit 2
  }
  set -- "$@" RONDO_PLAN060_RECIPE="$RONDO_PLAN060_RECIPE"
fi
if [ -n "${RONDO_PLAN060_MODEL_SNAPSHOT:-}" ] && [ "$RONDO_PLAN060_MODE" != bootstrap ]; then
  RONDO_PLAN060_MODEL_SNAPSHOT="$(require_persistent_path "$RONDO_PLAN060_MODEL_SNAPSHOT")" || {
    echo '{"status":"failed","code":"model_outside_task_root"}' >&2; exit 2
  }
  set -- "$@" RONDO_PLAN060_MODEL_SNAPSHOT="$RONDO_PLAN060_MODEL_SNAPSHOT"
fi

if [ ! -f "$target" ] || [ -L "$target" ]; then
  echo '{"status":"failed","code":"launch_target_missing"}' >&2
  exit 2
fi
worker="$RONDO_PLAN060_BUNDLE/training/publication-critic-plan060/runpod-launch-worker.sh"
if [ ! -f "$worker" ] || [ -L "$worker" ]; then
  echo '{"status":"failed","code":"launch_worker_missing"}' >&2
  exit 2
fi
if [ "$RONDO_PLAN060_MODE" = bootstrap ]; then
  set -- "$@" timeout --signal=TERM --kill-after=120 \
    "$RONDO_PLAN060_MAX_SECONDS" bash "$target"
else
  set -- "$@" bash "$target"
fi
active_lock="$controller/active.lock"
active_pid="$controller/active.pid"
if [ -L "$active_lock" ] || [ -L "$active_pid" ]; then
  echo '{"status":"failed","code":"task_launch_state_unsafe"}' >&2
  exit 2
fi
exec 9> "$active_lock"
if ! flock -n 9; then
  echo '{"status":"failed","code":"task_launch_already_active"}' >&2
  exit 2
fi

nohup setsid bash "$worker" "$status" "$RONDO_PLAN060_MODE" "$@" \
  > "$log" 2>&1 </dev/null 9>&9 &
pid=$!
temporary="$pidfile.tmp.$$"
active_temporary="$active_pid.tmp.$$"
if ! printf '%s\n' "$pid" > "$temporary" \
  || ! mv "$temporary" "$pidfile" \
  || ! printf '%s\n' "$pid" > "$active_temporary" \
  || ! mv "$active_temporary" "$active_pid"; then
  kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null || true
  wait "$pid" 2>/dev/null || true
  exec 9>&-
  echo '{"status":"failed","code":"launch_pid_persist_failed"}' >&2
  exit 2
fi
exec 9>&-
printf '{"status":"launched","mode":"%s","launch_name":"%s"}\n' \
  "$RONDO_PLAN060_MODE" "$RONDO_PLAN060_LAUNCH_NAME"
