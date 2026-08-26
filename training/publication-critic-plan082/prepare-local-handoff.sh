#!/usr/bin/env bash
set -eu
umask 077

script_root="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)"
source_root="$(realpath -e -- "$script_root/../..")"
common_dir="$(git -C "$source_root" rev-parse --path-format=absolute --git-common-dir)"
physical_root="$(dirname -- "$common_dir")"
venv="${RONDO_PLAN082_HANDOFF_VENV:-$physical_root/eval-data/publication-critic/plan082/handoff-runtime-v1/venv}"
requirements="$script_root/handoff-dependencies-v1.txt"

case "$venv" in "$physical_root"/eval-data/publication-critic/plan082/*) ;; *) exit 2 ;; esac
mkdir -m 700 -p "$(dirname -- "$venv")"
if [ ! -x "$venv/bin/python" ]; then
  python3 -B -m venv "$venv"
fi
"$venv/bin/python" -B -m pip install --disable-pip-version-check \
  --upgrade-strategy only-if-needed -r "$requirements"
"$venv/bin/python" -B -m pip check
printf '%s\n' "$venv/bin/python"
