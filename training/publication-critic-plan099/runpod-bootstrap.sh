#!/usr/bin/env bash
set -eu
umask 077

if [ "${RONDO_PLAN099_STAGE_B_APPROVED:-}" != "1" ]; then exit 2; fi
: "${RONDO_PLAN099_TASK_ROOT:?set the verified task root}"
: "${RONDO_PLAN099_SOURCE_ROOT:?set the new assembled source root}"
: "${RONDO_PLAN099_SOURCE_ARCHIVE:?set the uploaded source archive}"
: "${RONDO_PLAN099_DATA_ARCHIVE:?set the uploaded data archive}"
: "${RONDO_PLAN099_SOURCE_SHA256:?set the source archive sha256}"
: "${RONDO_PLAN099_DATA_SHA256:?set the data archive sha256}"
: "${RONDO_PLAN099_SOURCE_COMMIT:?set the exact source commit}"
: "${RONDO_PLAN099_SEGMENT_AUTHORIZATION:?set the paid segment authorization}"
: "${RONDO_PLAN099_RESOURCE_RECEIPT:?set the live resource receipt}"
: "${RONDO_PLAN099_LIFECYCLE_AUTHORIZATION:?set the lifecycle authorization}"
: "${RONDO_PLAN099_VALIDATED_ACTUAL_POD_ID:?set the verified actual Pod id}"
: "${RONDO_PLAN099_VALIDATED_ACTUAL_POD_NAME:?set the verified actual Pod name}"
: "${RONDO_PLAN099_IMAGE_IDENTITY:?set the exact image identity}"
: "${RONDO_PLAN099_MAX_SECONDS:?set the paid segment maximum seconds}"
: "${RONDO_PLAN099_REVIEWER_APPROVAL_PHRASE:?set the exact reviewer approval phrase}"
case "$RONDO_PLAN099_MAX_SECONDS" in ''|*[!0-9]*) exit 2 ;; esac
if [ "$RONDO_PLAN099_MAX_SECONDS" -le 0 ] || [ "$RONDO_PLAN099_MAX_SECONDS" -gt 10380 ]; then
  exit 2
fi
task_root="$(realpath -e -- "$RONDO_PLAN099_TASK_ROOT")"
source_archive="$(realpath -e -- "$RONDO_PLAN099_SOURCE_ARCHIVE")"
data_archive="$(realpath -e -- "$RONDO_PLAN099_DATA_ARCHIVE")"
case "$task_root" in /workspace/rondo-plan099-*) ;; *) exit 2 ;; esac
case "$source_archive" in "$task_root"/*) ;; *) exit 2 ;; esac
case "$data_archive" in "$task_root"/*) ;; *) exit 2 ;; esac
source_root="$RONDO_PLAN099_SOURCE_ROOT"
case "$source_root" in "$task_root"/*) ;; *) exit 2 ;; esac
if [ -e "$source_root" ] || [ -L "$source_root" ]; then exit 2; fi
if [ -e "$task_root/venv" ] || [ -L "$task_root/venv" ]; then exit 2; fi

printf '%s  %s\n' "$RONDO_PLAN099_SOURCE_SHA256" "$source_archive" | sha256sum -c -
printf '%s  %s\n' "$RONDO_PLAN099_DATA_SHA256" "$data_archive" | sha256sum -c -
bootstrap_source="$task_root/bootstrap-source"
if [ "${RONDO_PLAN099_BOOTSTRAP_INNER:-}" != "1" ]; then
  if [ -e "$bootstrap_source" ] || [ -L "$bootstrap_source" ]; then exit 2; fi
  mkdir -m 700 "$bootstrap_source"
  tar --extract --file "$source_archive" --directory "$bootstrap_source" \
    --no-same-owner --no-same-permissions
  inner="$bootstrap_source/training/publication-critic-plan099/runpod-bootstrap.sh"
  if [ ! -f "$inner" ] || [ -L "$inner" ]; then exit 2; fi
  exec timeout --signal=TERM --kill-after=60s "$RONDO_PLAN099_MAX_SECONDS" \
    env RONDO_PLAN099_BOOTSTRAP_INNER=1 bash "$inner"
fi
PYTHONPATH="$bootstrap_source/eval" python3 -B -P -m \
  rondo_eval.publication_critic.full_model_training.plan099_cli \
  validate-runtime-controls \
  --segment-authorization "$RONDO_PLAN099_SEGMENT_AUTHORIZATION" \
  --resource-receipt "$RONDO_PLAN099_RESOURCE_RECEIPT" \
  --lifecycle-authorization "$RONDO_PLAN099_LIFECYCLE_AUTHORIZATION" \
  --validated-actual-pod-id "$RONDO_PLAN099_VALIDATED_ACTUAL_POD_ID" \
  --validated-actual-pod-name "$RONDO_PLAN099_VALIDATED_ACTUAL_POD_NAME" \
  --reviewer-approval-phrase "$RONDO_PLAN099_REVIEWER_APPROVAL_PHRASE"
runtime_local="$task_root/runtime-local"
mkdir -m 700 "$runtime_local"
PYTHONPATH="$bootstrap_source/eval" python3 -B -P -m \
  rondo_eval.publication_critic.full_model_training.plan099_cli \
  assemble-execution-root --source-archive "$source_archive" \
  --data-archive "$data_archive" --source-sha256 "$RONDO_PLAN099_SOURCE_SHA256" \
  --data-sha256 "$RONDO_PLAN099_DATA_SHA256" --commit "$RONDO_PLAN099_SOURCE_COMMIT" \
  --output "$source_root" --identity-output "$runtime_local/source-identity.json"

python3 -m venv --copies --system-site-packages "$task_root/venv"
"$task_root/venv/bin/python" -B -P -c \
  'import torch; assert torch.__version__ == "2.8.0+cu128"; assert torch.version.cuda == "12.8"'
"$task_root/venv/bin/python" -m pip install --disable-pip-version-check \
  --no-cache-dir \
  --requirement "$source_root/training/publication-critic-plan099/dependencies-v1.txt"
"$task_root/venv/bin/python" -B -P -c \
  'import sys, huggingface_hub, psutil, safetensors, tokenizers, torch, transformers; assert sys.version_info[:2] == (3, 12); assert torch.__version__ == "2.8.0+cu128"; assert torch.version.cuda == "12.8"; assert transformers.__version__ == "4.52.3"; assert tokenizers.__version__ == "0.21.4"; assert huggingface_hub.__version__ == "0.36.2"; assert safetensors.__version__ == "0.5.3"; assert psutil.__version__ == "7.0.0"'
"$task_root/venv/bin/python" -m pip check
PYTHONPATH="$source_root/eval" "$task_root/venv/bin/python" -B -P -m \
  rondo_eval.publication_critic.full_model_training.plan099_cli validate-freeze
