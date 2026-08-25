#!/usr/bin/env bash
set -eu

: "${RONDO_PLAN079_REPO_ROOT:?set the clean Plan 079 worktree root}"
: "${RONDO_PLAN079_SOURCE_OUTPUT:?set a new tar output path}"
: "${RONDO_PLAN079_SOURCE_COMMIT:?set the exact source commit}"

repo="$(realpath -e -- "$RONDO_PLAN079_REPO_ROOT")"
output="$(realpath -m -- "$RONDO_PLAN079_SOURCE_OUTPUT")"
case "$output" in "$repo"/*) exit 2 ;; esac
if [ -e "$output" ] || [ -L "$output" ]; then exit 2; fi
actual="$(git -C "$repo" rev-parse HEAD)"
if [ "$actual" != "$RONDO_PLAN079_SOURCE_COMMIT" ]; then exit 2; fi
if [ -n "$(git -C "$repo" status --porcelain --untracked-files=no)" ]; then exit 2; fi

umask 077
git -C "$repo" archive --format=tar --output="$output" "$actual" -- \
  eval/rondo_eval \
  eval/templates/publication-critic \
  eval/manifests/publication-critic \
  eval/model-locks/publication-critic/skywork-reward-v2-qwen3-1.7b-e51ea3e0.json \
  eval/model-locks/publication-critic/skywork-reward-v2-qwen3-4b-fd958fef.json \
  eval/environments/publication-critic-plan068/uv.lock \
  training/publication-critic-plan079
chmod 600 "$output"
sha256sum "$output"
