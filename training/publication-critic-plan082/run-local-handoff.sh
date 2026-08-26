#!/usr/bin/env bash
set -eu
umask 077

script_root="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
source_root="$(realpath -e -- "$script_root/../..")"
common_dir="$(git -C "$source_root" rev-parse --path-format=absolute --git-common-dir)"
physical_root="$(dirname -- "$common_dir")"
venv="${RONDO_PLAN082_HANDOFF_VENV:-$physical_root/eval-data/publication-critic/plan082/handoff-runtime-v1/venv}"
requirements="$script_root/handoff-dependencies-v1.txt"

dry_run=0
if [ "${1:-}" = "--dry-run" ]; then
  dry_run=1
  shift
fi
if [ "$#" -ne 3 ] || [ "$2" != "--binding" ]; then exit 2; fi
operation="$1"
binding="$(realpath -e -- "$3")"
case "$operation" in inventory|download) ;; *) exit 2 ;; esac
case "$venv" in "$physical_root"/eval-data/publication-critic/plan082/*) ;; *) exit 2 ;; esac
if [ ! -x "$venv/bin/python" ]; then exit 2; fi

cd -- "$source_root"
if [ "$dry_run" -eq 1 ]; then
  exec env PYTHONPATH="$source_root/eval" "$venv/bin/python" -B -P -m \
    rondo_eval.publication_critic.full_model_training.plan082_cli \
    handoff-preflight --operation "$operation" --binding "$binding" \
    --requirements "$requirements"
fi
exec env PYTHONPATH="$source_root/eval" "$venv/bin/python" -B -P -m \
  rondo_eval.publication_critic.full_model_training.plan082_cli \
  "handoff-$operation" --binding "$binding"
