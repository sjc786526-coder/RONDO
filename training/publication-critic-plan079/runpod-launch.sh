#!/usr/bin/env bash
set -eu

: "${RONDO_PLAN079_TASK_ROOT:?set the persistent task root}"
: "${RONDO_PLAN079_SOURCE_ROOT:?set the verified source root}"
: "${RONDO_PLAN079_MODE:?set bootstrap or evaluate}"
: "${RONDO_PLAN079_LAUNCH_NAME:?set a unique launch name}"
case "$RONDO_PLAN079_LAUNCH_NAME" in ''|*[!a-zA-Z0-9._-]*) exit 2 ;; esac
case "$RONDO_PLAN079_TASK_ROOT" in /workspace/*) ;; *) exit 2 ;; esac
task_root="$(realpath -e -- "$RONDO_PLAN079_TASK_ROOT")"
source_root="$(realpath -e -- "$RONDO_PLAN079_SOURCE_ROOT")"
case "$task_root" in /workspace/*) ;; *) exit 2 ;; esac
case "$source_root" in "$task_root"/*) ;; *) exit 2 ;; esac

controller="$task_root/controller"
mkdir -p "$controller"
status="$controller/$RONDO_PLAN079_LAUNCH_NAME.status.json"
log="$controller/$RONDO_PLAN079_LAUNCH_NAME.log"
pidfile="$controller/$RONDO_PLAN079_LAUNCH_NAME.pid"
for path in "$status" "$log" "$pidfile"; do
  if [ -e "$path" ] || [ -L "$path" ]; then exit 2; fi
done
worker="$source_root/training/publication-critic-plan079/runpod-launch-worker.sh"
case "$RONDO_PLAN079_MODE" in
  bootstrap) target="$source_root/training/publication-critic-plan079/runpod-bootstrap.sh" ;;
  evaluate) target="$source_root/training/publication-critic-plan079/runpod-evaluate.sh" ;;
  *) exit 2 ;;
esac
if [ ! -f "$worker" ] || [ -L "$worker" ] || [ ! -f "$target" ] || [ -L "$target" ]; then exit 2; fi

set -- env \
  RONDO_PLAN079_TASK_ROOT="$task_root" \
  RONDO_PLAN079_SOURCE_ROOT="$source_root" \
  RONDO_PLAN079_STATUS="$status" \
  RONDO_PLAN079_IMAGE_ID="${RONDO_PLAN079_IMAGE_ID:?set observed image identity}"
if [ "$RONDO_PLAN079_MODE" = bootstrap ]; then
  set -- "$@" \
    RONDO_PLAN079_SOURCE_ARCHIVE="${RONDO_PLAN079_SOURCE_ARCHIVE:?set source archive}" \
    RONDO_PLAN079_SOURCE_SHA256="${RONDO_PLAN079_SOURCE_SHA256:?set source hash}" \
    RONDO_PLAN079_VALIDATION_ARCHIVE="${RONDO_PLAN079_VALIDATION_ARCHIVE:?set validation archive}" \
    RONDO_PLAN079_VALIDATION_SHA256="${RONDO_PLAN079_VALIDATION_SHA256:?set validation hash}"
else
  set -- "$@" \
    RONDO_PLAN079_RUN_SPEC="${RONDO_PLAN079_RUN_SPEC:?set run spec}" \
    RONDO_PLAN079_RELEASE="${RONDO_PLAN079_RELEASE:?set validation release}" \
    RONDO_PLAN079_SOURCE_ARCHIVE="${RONDO_PLAN079_SOURCE_ARCHIVE:?set source archive}" \
    RONDO_PLAN079_VALIDATION_BUNDLE="${RONDO_PLAN079_VALIDATION_BUNDLE:?set validation bundle}" \
    RONDO_PLAN079_RUNS_ROOT="${RONDO_PLAN079_RUNS_ROOT:?set run root}" \
    RONDO_PLAN079_ATTEMPT_ID="${RONDO_PLAN079_ATTEMPT_ID:?set attempt id}" \
    RONDO_PLAN079_MAX_SECONDS="${RONDO_PLAN079_MAX_SECONDS:-7200}"
fi
set -- "$@" bash "$target"

active_lock="$controller/active.lock"
exec 9> "$active_lock"
if ! flock -n 9; then exit 2; fi
nohup setsid bash "$worker" "$status" "$RONDO_PLAN079_MODE" "$@" \
  > "$log" 2>&1 </dev/null 9>&9 &
pid=$!
printf '%s\n' "$pid" > "$pidfile.tmp.$$"
mv "$pidfile.tmp.$$" "$pidfile"
exec 9>&-
printf '{"status":"launched","mode":"%s","launch_name":"%s"}\n' \
  "$RONDO_PLAN079_MODE" "$RONDO_PLAN079_LAUNCH_NAME"
