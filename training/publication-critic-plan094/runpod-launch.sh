#!/usr/bin/env bash
set -eu
umask 077

if [ "${RONDO_PLAN094_STAGE_B_APPROVED:-}" != "1" ]; then exit 2; fi
: "${RONDO_PLAN094_TASK_ROOT:?set task root}"
: "${RONDO_PLAN094_SOURCE_ROOT:?set verified source root}"
: "${RONDO_PLAN094_IMAGE_IDENTITY:?set the exact approved container image identity}"
: "${RONDO_PLAN094_LAUNCH_NAME:?set unique launch name}"
: "${RONDO_PLAN094_MAX_SECONDS:?set a finite command timeout}"
: "${RONDO_PLAN094_BUDGET_SNAPSHOT:?set a fresh task-owned budget snapshot}"
: "${RONDO_PLAN094_COMPUTE_RATE_USD_PER_HOUR:?set the verified compute rate}"
: "${RONDO_PLAN094_STORAGE_RATE_USD_PER_HOUR:?set the verified storage rate}"
if [ "$#" -lt 2 ] || [ "$1" != "--" ]; then exit 2; fi
shift
case "$RONDO_PLAN094_TASK_ROOT" in /workspace/*) ;; *) exit 2 ;; esac
case "$RONDO_PLAN094_LAUNCH_NAME" in ''|*[!a-zA-Z0-9._-]*) exit 2 ;; esac
case "$RONDO_PLAN094_MAX_SECONDS" in ''|*[!0-9]*) exit 2 ;; esac
if [ "$RONDO_PLAN094_MAX_SECONDS" -le 0 ]; then exit 2; fi
task_root="$(realpath -e -- "$RONDO_PLAN094_TASK_ROOT")"
case "$task_root" in /workspace/rondo-plan094-*) ;; *) exit 2 ;; esac
source_root="$(realpath -e -- "$RONDO_PLAN094_SOURCE_ROOT")"
case "$source_root" in "$task_root"/*) ;; *) exit 2 ;; esac
budget_snapshot="$(realpath -e -- "$RONDO_PLAN094_BUDGET_SNAPSHOT")"
case "$budget_snapshot" in "$task_root"/*) ;; *) exit 2 ;; esac
controller="$task_root/controller"
mkdir -m 700 -p "$controller"
status="$controller/$RONDO_PLAN094_LAUNCH_NAME.status.json"
log="$controller/$RONDO_PLAN094_LAUNCH_NAME.log"
pidfile="$controller/$RONDO_PLAN094_LAUNCH_NAME.pid"
authorization="$controller/$RONDO_PLAN094_LAUNCH_NAME.authorization.json"
for path in "$status" "$log" "$pidfile" "$authorization"; do
  if [ -e "$path" ] || [ -L "$path" ]; then exit 2; fi
done

worker="$source_root/training/publication-critic-plan094/runpod-worker.sh"
if [ ! -f "$worker" ] || [ -L "$worker" ]; then exit 2; fi
python="$task_root/venv/bin/python"
if [ ! -x "$python" ] || [ -L "$python" ]; then exit 2; fi
authorization_tmp="$authorization.tmp.$$"
trap 'rm -f -- "$authorization_tmp"' EXIT
PYTHONPATH="$source_root/eval" "$python" -B -P -m \
  rondo_eval.publication_critic.full_model_training.plan094_cli \
  authorize-segment --snapshot "$RONDO_PLAN094_BUDGET_SNAPSHOT" \
  --maximum-seconds "$RONDO_PLAN094_MAX_SECONDS" \
  --compute-rate-usd-per-hour "$RONDO_PLAN094_COMPUTE_RATE_USD_PER_HOUR" \
  --storage-rate-usd-per-hour "$RONDO_PLAN094_STORAGE_RATE_USD_PER_HOUR" \
  > "$authorization_tmp"
chmod 600 "$authorization_tmp"
mv "$authorization_tmp" "$authorization"
active_lock="$controller/active.lock"
exec 9> "$active_lock"
if ! flock -n 9; then exit 2; fi
nohup setsid bash "$worker" "$status" \
  timeout --signal=TERM --kill-after=60s "$RONDO_PLAN094_MAX_SECONDS" \
  "$@" > "$log" 2>&1 </dev/null 9>&9 &
pid=$!
printf '%s\n' "$pid" > "$pidfile.tmp.$$"
mv "$pidfile.tmp.$$" "$pidfile"
exec 9>&-
printf '{"status":"launched","launch_name":"%s","pid":%s}\n' \
  "$RONDO_PLAN094_LAUNCH_NAME" "$pid"
