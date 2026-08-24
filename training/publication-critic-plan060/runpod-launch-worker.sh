#!/usr/bin/env bash
set +e

# Internal worker for runpod-launch.sh. Keeping this as a file avoids nesting
# shell source and JSON quoting inside `bash -c` while preserving exact argv.
if [ "$#" -lt 3 ]; then
  exit 2
fi
status=$1
mode=$2
shift 2
if [ -z "$status" ] || [ -z "$mode" ] || [ -L "$status" ]; then
  exit 2
fi

"$@"
rc=$?
if [ ! -e "$status" ] && [ ! -L "$status" ]; then
  umask 077
  fallback="$status.fallback.$$"
  if printf '{"status":"failed","mode":"%s","exit_code":%s,"code":"target_status_missing"}\n' \
    "$mode" "$rc" > "$fallback"; then
    mv "$fallback" "$status" 2>/dev/null || true
  fi
fi
exit "$rc"
