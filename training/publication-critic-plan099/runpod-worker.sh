#!/usr/bin/env bash
set -eu
umask 077

if [ "${RONDO_PLAN099_STAGE_B_APPROVED:-}" != "1" ]; then exit 2; fi
: "${RONDO_PLAN099_TASK_ROOT:?set the verified task root}"
: "${RONDO_PLAN099_SOURCE_ROOT:?set the verified source root}"
: "${RONDO_PLAN099_SEGMENT_AUTHORIZATION:?set the fresh paid-segment authorization}"
: "${RONDO_PLAN099_RESOURCE_RECEIPT:?set the verified live resource receipt}"
: "${RONDO_PLAN099_LIFECYCLE_AUTHORIZATION:?set the Pod lifecycle authorization}"
: "${RONDO_PLAN099_IMAGE_IDENTITY:?set the exact approved image identity}"
: "${RONDO_PLAN099_MAX_SECONDS:?set a finite worker timeout}"
if [ "$#" -lt 1 ]; then exit 2; fi

task_root="$(realpath -e -- "$RONDO_PLAN099_TASK_ROOT")"
source_root="$(realpath -e -- "$RONDO_PLAN099_SOURCE_ROOT")"
segment="$(realpath -e -- "$RONDO_PLAN099_SEGMENT_AUTHORIZATION")"
resource="$(realpath -e -- "$RONDO_PLAN099_RESOURCE_RECEIPT")"
lifecycle="$(realpath -e -- "$RONDO_PLAN099_LIFECYCLE_AUTHORIZATION")"
runtime_root="/run/rondo-plan099-z1z3m7n90nz4xr/runtime-control"
case "$task_root" in /workspace/rondo-plan099-*) ;; *) exit 2 ;; esac
case "$source_root" in "$task_root"/*) ;; *) exit 2 ;; esac
case "$segment" in "$runtime_root/segment/"*.json) ;; *) exit 2 ;; esac
case "$resource" in "$runtime_root/live-resource/"*.json) ;; *) exit 2 ;; esac
case "$lifecycle" in "$runtime_root/lifecycle/"*.json) ;; *) exit 2 ;; esac
case "$RONDO_PLAN099_MAX_SECONDS" in ''|*[!0-9]*) exit 2 ;; esac
if [ "$RONDO_PLAN099_MAX_SECONDS" -le 0 ] || [ "$RONDO_PLAN099_MAX_SECONDS" -gt 10380 ]; then
  exit 2
fi

python="$task_root/venv/bin/python"
if [ ! -x "$python" ] || [ -L "$python" ]; then exit 2; fi
export PYTHONPATH="$source_root/eval"
exec timeout --signal=TERM --kill-after=60s "$RONDO_PLAN099_MAX_SECONDS" \
  "$python" -B -P -m \
  rondo_eval.publication_critic.full_model_training.plan099_cli "$@" \
  --segment-authorization "$segment" --resource-receipt "$resource" \
  --lifecycle-authorization "$lifecycle"
