#!/usr/bin/env bash
set -eu

: "${RONDO_PLAN066_TASK_ROOT:?set task root}"
: "${RONDO_PLAN066_BUNDLE:?set bundle root}"
: "${RONDO_PLAN066_IMAGE_ID:?set image identity}"
: "${RONDO_PLAN066_MODE:?set training mode}"
: "${RONDO_PLAN066_LAUNCH_NAME:?set unique launch name}"
: "${RONDO_PLAN066_OUTPUT:?set output root}"
: "${RONDO_PLAN066_WINNER_LOCK:?set winner lock}"
RONDO_PLAN066_MAX_SECONDS="${RONDO_PLAN066_MAX_SECONDS:-7200}"
case "$RONDO_PLAN066_LAUNCH_NAME" in ''|*[!a-zA-Z0-9._-]*) exit 2 ;; esac
case "$RONDO_PLAN066_MAX_SECONDS" in ''|*[!0-9]*) exit 2 ;; esac
if [ "$RONDO_PLAN066_MAX_SECONDS" -le 0 ]; then exit 2; fi
case "$RONDO_PLAN066_TASK_ROOT" in /workspace/*) ;; *) exit 2 ;; esac
task_root="$(realpath -e -- "$RONDO_PLAN066_TASK_ROOT")"
case "$task_root" in /workspace/*) ;; *) exit 2 ;; esac
require_task_path() {
  candidate="$(realpath -m -- "$1")" || return 1
  case "$candidate" in "$task_root"/*) printf '%s\n' "$candidate" ;; *) return 1 ;; esac
}
bundle="$(realpath -e -- "$RONDO_PLAN066_BUNDLE")"
bundle="$(require_task_path "$bundle")" || exit 2
output="$(require_task_path "$RONDO_PLAN066_OUTPUT")" || exit 2
winner="$(require_task_path "$RONDO_PLAN066_WINNER_LOCK")" || exit 2
controller="$task_root/controller"
mkdir -p "$controller"
status="$controller/$RONDO_PLAN066_LAUNCH_NAME.status.json"
log="$controller/$RONDO_PLAN066_LAUNCH_NAME.log"
pidfile="$controller/$RONDO_PLAN066_LAUNCH_NAME.pid"
for path in "$status" "$log" "$pidfile"; do
  if [ -e "$path" ] || [ -L "$path" ]; then exit 2; fi
done
target="$bundle/training/publication-critic-plan066/runpod-training-entrypoint.sh"
worker="$bundle/training/publication-critic-plan066/runpod-launch-worker.sh"
if [ ! -f "$target" ] || [ -L "$target" ] || [ ! -f "$worker" ] || [ -L "$worker" ]; then exit 2; fi

set -- env RONDO_PLAN066_TASK_ROOT="$task_root" RONDO_PLAN066_BUNDLE="$bundle" \
  RONDO_PLAN066_IMAGE_ID="$RONDO_PLAN066_IMAGE_ID" RONDO_PLAN066_MODE="$RONDO_PLAN066_MODE" \
  RONDO_PLAN066_OUTPUT="$output" RONDO_PLAN066_WINNER_LOCK="$winner" \
  RONDO_PLAN066_STATUS="$status" RONDO_PLAN066_MAX_SECONDS="$RONDO_PLAN066_MAX_SECONDS"
if [ -n "${RONDO_PLAN066_CHECKPOINT:-}" ]; then
  value="$(require_task_path "$RONDO_PLAN066_CHECKPOINT")" || exit 2
  set -- "$@" "RONDO_PLAN066_CHECKPOINT=$value"
fi
if [ -n "${RONDO_PLAN066_DEPENDENCY_IDENTITY:-}" ]; then
  value="$(require_task_path "$RONDO_PLAN066_DEPENDENCY_IDENTITY")" || exit 2
  set -- "$@" "RONDO_PLAN066_DEPENDENCY_IDENTITY=$value"
fi
if [ -n "${RONDO_PLAN066_DEPENDENCY_FREEZE:-}" ]; then
  value="$(require_task_path "$RONDO_PLAN066_DEPENDENCY_FREEZE")" || exit 2
  set -- "$@" "RONDO_PLAN066_DEPENDENCY_FREEZE=$value"
fi
if [ -n "${RONDO_PLAN066_RECIPE:-}" ]; then
  value="$(require_task_path "$RONDO_PLAN066_RECIPE")" || exit 2
  set -- "$@" "RONDO_PLAN066_RECIPE=$value"
fi
if [ -n "${RONDO_PLAN066_MODEL_SNAPSHOT:-}" ]; then
  value="$(require_task_path "$RONDO_PLAN066_MODEL_SNAPSHOT")" || exit 2
  set -- "$@" "RONDO_PLAN066_MODEL_SNAPSHOT=$value"
fi
set -- "$@" bash "$target"

active_lock="$controller/active.lock"
active_pid="$controller/active.pid"
if [ -L "$active_lock" ] || [ -L "$active_pid" ]; then exit 2; fi
exec 9> "$active_lock"
if ! flock -n 9; then exit 2; fi
nohup setsid bash "$worker" "$status" "$RONDO_PLAN066_MODE" "$@" \
  > "$log" 2>&1 </dev/null 9>&9 &
pid=$!
printf '%s\n' "$pid" > "$pidfile.tmp.$$"
mv "$pidfile.tmp.$$" "$pidfile"
printf '%s\n' "$pid" > "$active_pid.tmp.$$"
mv "$active_pid.tmp.$$" "$active_pid"
exec 9>&-
printf '{"status":"launched","mode":"%s","launch_name":"%s"}\n' \
  "$RONDO_PLAN066_MODE" "$RONDO_PLAN066_LAUNCH_NAME"
