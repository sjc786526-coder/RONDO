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
if [ -e "$bootstrap_source" ] || [ -L "$bootstrap_source" ]; then exit 2; fi
mkdir -m 700 "$bootstrap_source"
tar --extract --file "$source_archive" --directory "$bootstrap_source" \
  --no-same-owner --no-same-permissions
PYTHONPATH="$bootstrap_source/eval" python3 -B -P -m \
  rondo_eval.publication_critic.full_model_training.plan099_cli \
  assemble-execution-root --source-archive "$source_archive" \
  --data-archive "$data_archive" --source-sha256 "$RONDO_PLAN099_SOURCE_SHA256" \
  --data-sha256 "$RONDO_PLAN099_DATA_SHA256" --commit "$RONDO_PLAN099_SOURCE_COMMIT" \
  --output "$source_root"

python3 -m venv "$task_root/venv"
"$task_root/venv/bin/python" -m pip install --disable-pip-version-check \
  --requirement "$source_root/training/publication-critic-plan099/dependencies-v1.txt"
PYTHONPATH="$source_root/eval" "$task_root/venv/bin/python" -B -P -m \
  rondo_eval.publication_critic.full_model_training.plan099_cli validate-freeze
