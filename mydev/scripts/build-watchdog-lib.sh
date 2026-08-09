#!/usr/bin/env bash

# Pure helpers shared by the build watchdog and its lightweight tests.

rondo_cgroup_population_state() {
  local cgroup_root="$1"
  local runner_pid="${2:-}"
  local populated=""

  if [[ -n "$cgroup_root" && -r "${cgroup_root}/cgroup.events" ]]; then
    populated="$(awk '$1 == "populated" && $2 ~ /^[01]$/ {print $2; found=1; exit} END {if (!found) exit 1}' \
      "${cgroup_root}/cgroup.events" 2>/dev/null || true)"
    case "$populated" in
      1) printf '%s' active ;;
      0) printf '%s' gone ;;
      *) printf '%s' unknown ;;
    esac
    return 0
  fi

  if [[ -z "$runner_pid" ]]; then
    printf '%s' gone
  elif [[ ! -e "$cgroup_root" ]] && ! kill -0 "$runner_pid" 2>/dev/null; then
    printf '%s' gone
  else
    printf '%s' unknown
  fi
}

rondo_cgroup_direct_member_count() {
  local cgroup_root="$1"

  if [[ -z "$cgroup_root" || ! -r "${cgroup_root}/cgroup.procs" ]]; then
    printf '%s' unknown
    return 0
  fi
  awk 'NF {count += 1} END {print count + 0}' "${cgroup_root}/cgroup.procs" 2>/dev/null \
    || printf '%s' unknown
}

rondo_prepare_nextest_config() {
  local source_config="$1"
  local output_config="$2"
  local junit_path="$3"

  [[ -f "$source_config" && ! -L "$source_config" ]] || return 1
  [[ "$junit_path" == /* ]] || return 1
  if [[ "$junit_path" == *$'\n'* || "$junit_path" == *$'\r'* \
    || "$junit_path" == *\"* || "$junit_path" == *\\* ]]; then
    return 1
  fi
  if grep -Eq '^\[profile[.]local[.]junit\][[:space:]]*$' "$source_config"; then
    return 1
  fi
  cp -- "$source_config" "$output_config" || return 1
  {
    printf '\n[profile.local.junit]\n'
    printf 'path = "%s"\n' "$junit_path"
  } >>"$output_config"
}

rondo_inspect_junit_report() {
  local junit_path="$1"
  local junit_sha256=""

  if [[ -L "$junit_path" || ( -e "$junit_path" && ! -f "$junit_path" ) ]]; then
    printf 'unreadable\t\n'
    return 0
  fi
  if [[ ! -f "$junit_path" ]]; then
    printf 'absent\t\n'
    return 0
  fi
  if [[ ! -r "$junit_path" ]]; then
    printf 'unreadable\t\n'
    return 0
  fi
  if ! tail -n 1 -- "$junit_path" 2>/dev/null \
    | grep -Eq '^[[:space:]]*</testsuites>[[:space:]]*$'; then
    printf 'invalid\t\n'
    return 0
  fi
  junit_sha256="$(sha256sum -- "$junit_path" 2>/dev/null | awk '{print $1}')"
  if [[ ! "$junit_sha256" =~ ^[0-9a-f]{64}$ ]]; then
    printf 'hash_failed\t\n'
    return 0
  fi
  printf 'retained\t%s\n' "$junit_sha256"
}
