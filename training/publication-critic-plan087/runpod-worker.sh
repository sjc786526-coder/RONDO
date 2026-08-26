#!/usr/bin/env bash
set -eu
umask 077

if [ "$#" -lt 2 ]; then exit 2; fi
status="$1"
shift
if [ -e "$status" ] || [ -L "$status" ] || [ ! -d "$(dirname -- "$status")" ]; then
  exit 2
fi
temporary="$status.tmp.$$"
if [ -e "$temporary" ] || [ -L "$temporary" ]; then exit 2; fi
finish() {
  rc=$?
  trap - EXIT
  if [ "$rc" -eq 0 ]; then
    printf '{"status":"completed"}\n' > "$temporary"
  else
    printf '{"status":"failed","exit_code":%s}\n' "$rc" > "$temporary"
  fi
  chmod 600 "$temporary"
  mv "$temporary" "$status"
  exit "$rc"
}
trap finish EXIT
"$@"
