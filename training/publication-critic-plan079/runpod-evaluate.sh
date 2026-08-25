#!/usr/bin/env bash
set -eu

: "${RONDO_PLAN079_TASK_ROOT:?set persistent task root}"
: "${RONDO_PLAN079_SOURCE_ROOT:?set verified source root}"
: "${RONDO_PLAN079_RUN_SPEC:?set frozen run spec}"
: "${RONDO_PLAN079_RELEASE:?set frozen validation release}"
: "${RONDO_PLAN079_SOURCE_ARCHIVE:?set frozen source archive}"
: "${RONDO_PLAN079_VALIDATION_BUNDLE:?set verified validation bundle}"
: "${RONDO_PLAN079_RUNS_ROOT:?set run root}"
: "${RONDO_PLAN079_ATTEMPT_ID:?set attempt id}"
: "${RONDO_PLAN079_STATUS:?set unique status path}"
RONDO_PLAN079_MAX_SECONDS="${RONDO_PLAN079_MAX_SECONDS:-7200}"
case "$RONDO_PLAN079_TASK_ROOT" in /workspace/*) ;; *) exit 2 ;; esac
case "$RONDO_PLAN079_MAX_SECONDS" in ''|*[!0-9]*) exit 2 ;; esac
task_root="$(realpath -e -- "$RONDO_PLAN079_TASK_ROOT")"
case "$task_root" in /workspace/*) ;; *) exit 2 ;; esac
require_task_path() {
  candidate="$(realpath -m -- "$1")" || return 1
  case "$candidate" in "$task_root"/*) printf '%s\n' "$candidate" ;; *) return 1 ;; esac
}
source_root="$(require_task_path "$RONDO_PLAN079_SOURCE_ROOT")" || exit 2
run_spec="$(require_task_path "$RONDO_PLAN079_RUN_SPEC")" || exit 2
release="$(require_task_path "$RONDO_PLAN079_RELEASE")" || exit 2
source_archive="$(require_task_path "$RONDO_PLAN079_SOURCE_ARCHIVE")" || exit 2
bundle="$(require_task_path "$RONDO_PLAN079_VALIDATION_BUNDLE")" || exit 2
runs_root="$(require_task_path "$RONDO_PLAN079_RUNS_ROOT")" || exit 2
status="$(require_task_path "$RONDO_PLAN079_STATUS")" || exit 2
case "$status" in "$task_root"/controller/*.json) ;; *) exit 2 ;; esac
if [ -e "$status" ] || [ -L "$status" ]; then exit 2; fi

umask 077
write_status() {
  rc=$?
  trap - EXIT
  temporary="$status.tmp.$$"
  if [ "$rc" -eq 0 ]; then
    printf '%s\n' '{"status":"completed","mode":"evaluate"}' > "$temporary"
  else
    printf '{"status":"failed","mode":"evaluate","exit_code":%s}\n' "$rc" > "$temporary"
  fi
  mv "$temporary" "$status"
  exit "$rc"
}
trap write_status EXIT

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$source_root/eval"
export HF_HOME="$task_root/hf-home"
export HF_HUB_CACHE="$HF_HOME/hub"
export HF_HUB_DISABLE_TELEMETRY=1
export RONDO_PLAN079_CLOUD_RUN=1
unset HF_TOKEN HUGGING_FACE_HUB_TOKEN HUGGINGFACEHUB_API_TOKEN
python="$task_root/venv/bin/python"
timeout --signal=TERM --kill-after=120 "$RONDO_PLAN079_MAX_SECONDS" \
  "$python" -B -P -m rondo_eval.publication_critic.base_quality run \
  --run-spec "$run_spec" \
  --release "$release" \
  --snapshot "$task_root/model-fd958fef" \
  --model-lock "$source_root/eval/model-locks/publication-critic/skywork-reward-v2-qwen3-4b-fd958fef.json" \
  --source-archive "$source_archive" \
  --environment-lock "$source_root/eval/environments/publication-critic-plan068/uv.lock" \
  --bundle "$bundle" \
  --runs-root "$runs_root" \
  --repo-root "$source_root" \
  --attempt-id "$RONDO_PLAN079_ATTEMPT_ID"
