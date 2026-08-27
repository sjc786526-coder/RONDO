#!/usr/bin/env bash
# Serialize heavy builds and supervise their disk, memory, swap, and PSI usage.
#
# The wrapper is intentionally fail-closed. A heavy build is not started unless
# the machine-global lock, systemd cgroup, and live counters are all available.
# This guarantees that main and worktrees cannot compile concurrently through
# the supported just recipes, while a direct external Cargo build causes the
# supervised build to stop immediately.
#
# Usage: with-build-lock.sh <command> [args...]
#
# Normal defaults are fixed for the current 28 GB RAM / 10 GB swap WSL2 host.
# Independent host-memory, swap, PSI, and non-reclaimable-memory stops retain
# machine-wide headroom while the scope can use reclaimable file cache.
#
# Explicit overrides:
#   RONDO_PROJECT_ROOT=<path>
#   RONDO_BUILD_LOCK=<path>                 (0 disables only the lock)
#   RONDO_BUILD_WATCHDOG=0                  (disables cgroup/watchdog explicitly)
#   RONDO_BUILD_MEMORY_HIGH=<size>          (default 21G)
#   RONDO_BUILD_MEMORY_MAX=<size>           (default 22G)
#   RONDO_BUILD_SWAP_MAX=<size>             (default 5G)
#   RONDO_BUILD_CARGO_PRODUCT=rondo-local|rondo-multi
#   RONDO_BUILD_PROJECT_WARN_BYTES=<bytes>  (default 350 GB decimal)
#   RONDO_BUILD_PROJECT_STOP_BYTES=<bytes>  (default 365 GB decimal)
#   RONDO_BUILD_PROJECT_MAX_BYTES=<bytes>   (default 370 GB decimal)
#   RONDO_BUILD_WINDOWS_C_FREE_STOP_BYTES=<bytes> (default 50 GB decimal)
#   RONDO_BUILD_RESIDUAL_GRACE_SECONDS=<s>  (default 5)
#   RONDO_BUILD_METRICS_DIR=<path>
set -uo pipefail

if [[ "$#" -eq 0 ]]; then
  echo "with-build-lock.sh: expected a command to run" >&2
  exit 64
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if ! source "${script_dir}/build-watchdog-lib.sh"; then
  echo "[rondo] cannot load build watchdog helpers" >&2
  exit 71
fi

command_args=("$@")
command_name="$(basename -- "$1")"
uid="${UID:-$(id -u 2>/dev/null || true)}"
if [[ -z "$uid" ]] || [[ ! "$uid" =~ ^[0-9]+$ ]]; then
  echo "[rondo] cannot determine the current uid; refusing a heavy build" >&2
  exit 65
fi

project_root="${RONDO_PROJECT_ROOT:-}"
worktree_root="$(git rev-parse --show-toplevel 2>/dev/null || true)"
if [[ -z "$project_root" ]]; then
  project_root="$(rondo_git_common_root "$worktree_root" || true)"
  if [[ -z "$project_root" ]]; then
    echo "[rondo] cannot resolve the shared RONDO repository root" >&2
    exit 66
  fi
fi
project_root="$(realpath -e -- "$project_root" 2>/dev/null || true)"
worktree_root="$(realpath -e -- "$worktree_root" 2>/dev/null || true)"
if [[ -z "$project_root" ]] || [[ ! -d "$project_root" ]] \
  || [[ -z "$worktree_root" ]] || [[ ! -d "$worktree_root" ]]; then
  echo "[rondo] invalid RONDO_PROJECT_ROOT" >&2
  exit 67
fi

cargo_product="${RONDO_BUILD_CARGO_PRODUCT:-}"
canonical_product_target=""
export_cargo_target=0
if [[ -n "$cargo_product" ]]; then
  canonical_product_target="$(
    rondo_product_cargo_target "$worktree_root" "$cargo_product" 2>/dev/null || true
  )"
  if [[ -z "$canonical_product_target" ]]; then
    echo "[rondo] invalid RONDO_BUILD_CARGO_PRODUCT" >&2
    exit 82
  fi
fi
if [[ -n "${CARGO_TARGET_DIR:-}" ]]; then
  target_dir="$CARGO_TARGET_DIR"
  export_cargo_target=1
elif [[ -n "$canonical_product_target" ]]; then
  target_dir="$canonical_product_target"
  export_cargo_target=1
else
  target_dir="${PWD}/target"
fi
unset RONDO_BUILD_CARGO_PRODUCT
if [[ "$target_dir" != /* ]]; then
  target_dir="${PWD}/${target_dir}"
fi
target_dir="$(realpath -m -- "$target_dir" 2>/dev/null || true)"
if [[ -z "$target_dir" ]] || [[ "$target_dir" != "${project_root}/"* ]]; then
  echo "[rondo] CARGO_TARGET_DIR must stay inside the monitored RONDO project root" >&2
  exit 82
fi
if ((export_cargo_target == 1)); then
  export CARGO_TARGET_DIR="$target_dir"
fi

runtime_dir="/run/user/${uid}"
if [[ -L "$runtime_dir" ]] || [[ ! -d "$runtime_dir" ]] || [[ ! -O "$runtime_dir" ]] || [[ ! -w "$runtime_dir" ]]; then
  runtime_dir="/tmp/rondo-runtime-${uid}"
  umask 077
  if [[ -L "$runtime_dir" ]] || ! mkdir -p -- "$runtime_dir" \
    || ! chmod 700 -- "$runtime_dir" || [[ ! -O "$runtime_dir" ]]; then
    echo "[rondo] no safe runtime directory is available" >&2
    exit 68
  fi
fi

lock_path="${RONDO_BUILD_LOCK:-${runtime_dir}/rondo-cargo-build.lock}"
if [[ "$lock_path" != "0" ]]; then
  if ! command -v flock >/dev/null 2>&1; then
    echo "[rondo] flock is unavailable; refusing an unlocked heavy build" >&2
    exit 69
  fi
  if [[ -L "$lock_path" ]] || [[ -e "$lock_path" && ! -O "$lock_path" ]]; then
    echo "[rondo] build lock path is unsafe: ${lock_path}" >&2
    exit 70
  fi
  umask 077
  exec 199>"$lock_path" || exit 70
  chmod 600 -- "$lock_path" 2>/dev/null || true
  if ! flock --nonblock 199; then
    echo "[rondo] waiting for the active heavy build (lock: ${lock_path})" >&2
    if ! flock 199; then
      echo "[rondo] cannot acquire the heavy build lock: ${lock_path}" >&2
      exit 70
    fi
  fi

  for required_guard_command in systemctl awk; do
    if ! command -v "$required_guard_command" >/dev/null 2>&1; then
      echo "[rondo] ${required_guard_command} is unavailable; cannot observe prior heavy scopes" >&2
      exit 84
    fi
  done
  active_heavy_scopes=""
  if ! active_heavy_scopes="$(rondo_active_heavy_scopes "$uid")"; then
    echo "[rondo] cannot verify that no prior RONDO heavy scope is populated; refusing payload start" >&2
    exit 84
  fi
  if [[ -n "$active_heavy_scopes" ]]; then
    echo "[rondo] canonical lock conflicts with populated RONDO heavy scope(s): ${active_heavy_scopes//$'\n'/,}; refusing payload start" >&2
    exit 84
  fi
fi

if [[ "${RONDO_BUILD_WATCHDOG:-1}" == "0" ]]; then
  echo "[rondo] build watchdog explicitly disabled" >&2
  exec "$@"
fi

for required in systemd-run systemctl du df awk find grep pgrep sha256sum tail; do
  if ! command -v "$required" >/dev/null 2>&1; then
    echo "[rondo] ${required} is unavailable; refusing an unsupervised heavy build" >&2
    exit 71
  fi
done

for proc_name in cargo rustc rust-lld cargo-nextest nextest; do
  if pgrep -x "$proc_name" >/dev/null 2>&1; then
    echo "[rondo] another ${proc_name} process is already active; refusing a second build" >&2
    exit 72
  fi
done

memory_high="${RONDO_BUILD_MEMORY_HIGH:-21G}"
memory_max="${RONDO_BUILD_MEMORY_MAX:-22G}"
swap_max="${RONDO_BUILD_SWAP_MAX:-5G}"
project_warn_bytes="${RONDO_BUILD_PROJECT_WARN_BYTES:-350000000000}"
project_stop_bytes="${RONDO_BUILD_PROJECT_STOP_BYTES:-365000000000}"
project_max_bytes="${RONDO_BUILD_PROJECT_MAX_BYTES:-370000000000}"
windows_c_free_stop_bytes="${RONDO_BUILD_WINDOWS_C_FREE_STOP_BYTES:-50000000000}"
nonreclaimable_stop_bytes="${RONDO_BUILD_NONRECLAIMABLE_STOP_BYTES:-20401094656}"
swap_sustained_stop_bytes="${RONDO_BUILD_SWAP_SUSTAINED_STOP_BYTES:-4294967296}"
swap_emergency_stop_bytes="${RONDO_BUILD_SWAP_EMERGENCY_STOP_BYTES:-5100273664}"
swap_stop_seconds="${RONDO_BUILD_SWAP_STOP_SECONDS:-20}"
host_available_stop_kb="${RONDO_BUILD_HOST_AVAILABLE_STOP_KB:-3670016}"
psi_full_stop_bp="${RONDO_BUILD_PSI_FULL_STOP_BP:-1500}"
psi_stop_seconds="${RONDO_BUILD_PSI_STOP_SECONDS:-20}"
disk_sample_interval="${RONDO_BUILD_DISK_SAMPLE_INTERVAL:-5}"
residual_grace_seconds="${RONDO_BUILD_RESIDUAL_GRACE_SECONDS:-5}"

numeric_settings=(
  "$project_warn_bytes" "$project_stop_bytes" "$project_max_bytes"
  "$windows_c_free_stop_bytes" "$nonreclaimable_stop_bytes"
  "$swap_sustained_stop_bytes" "$swap_emergency_stop_bytes" "$swap_stop_seconds"
  "$host_available_stop_kb" "$psi_full_stop_bp" "$psi_stop_seconds"
  "$disk_sample_interval" "$residual_grace_seconds"
)
for setting in "${numeric_settings[@]}"; do
  if [[ ! "$setting" =~ ^[0-9]+$ ]]; then
    echo "[rondo] watchdog byte/count settings must be non-negative integers" >&2
    exit 73
  fi
done
if ! rondo_project_limits_are_valid \
  "$project_warn_bytes" "$project_stop_bytes" "$project_max_bytes" "$disk_sample_interval"; then
  echo "[rondo] invalid project warning/stop/max or sample interval ordering" >&2
  exit 74
fi

write_effective_run_summary_fields() {
  rondo_write_effective_run_summary_fields \
    "$project_root" "$cargo_product" "$target_dir" \
    "$project_warn_bytes" "$project_stop_bytes" "$project_max_bytes" \
    "$windows_c_free_stop_bytes"
}

read_windows_c_capacity() {
  local used=""
  local available=""

  [[ -d /mnt/c ]] || return 1
  read -r used available < <(
    LC_ALL=C df -B1 --output=used,avail -- /mnt/c | awk 'NR==2 {print $1, $2}'
  ) || return 1
  [[ "$used" =~ ^[0-9]+$ && "$available" =~ ^[0-9]+$ ]] || return 1
  printf '%s %s\n' "$used" "$available"
}

project_before="$(du -sx -B1 -- "$project_root" 2>/dev/null | awk '{print $1}')"
windows_c_used_before=""
windows_c_available_before=""
read -r windows_c_used_before windows_c_available_before < <(read_windows_c_capacity) || true
host_mem_available_before="$(awk '/^MemAvailable:/{print $2; exit}' /proc/meminfo)"
host_swap_free_before="$(awk '/^SwapFree:/{print $2; exit}' /proc/meminfo)"
if [[ ! "$project_before" =~ ^[0-9]+$ ]] \
  || [[ ! "$windows_c_used_before" =~ ^[0-9]+$ ]] \
  || [[ ! "$windows_c_available_before" =~ ^[0-9]+$ ]] \
  || [[ ! "$host_mem_available_before" =~ ^[0-9]+$ ]] \
  || [[ ! "$host_swap_free_before" =~ ^[0-9]+$ ]]; then
  echo "[rondo] resource preflight counters are unavailable" >&2
  exit 75
fi
if ((project_before >= project_stop_bytes)); then
  echo "[rondo] project is already at the ${project_stop_bytes}-byte proactive stop line" >&2
  exit 76
fi
if ((windows_c_available_before <= windows_c_free_stop_bytes)); then
  echo "[rondo] Windows C: free space is already below the safety floor" >&2
  exit 77
fi
if ((host_mem_available_before <= host_available_stop_kb)); then
  echo "[rondo] host available memory is already below the safety floor" >&2
  exit 78
fi
if ((host_swap_free_before <= 1048576)); then
  echo "[rondo] host free swap is already below 1 GiB" >&2
  exit 79
fi

metrics_parent="${RONDO_BUILD_METRICS_DIR:-${worktree_root}/.codex/build-watchdog}"
started_stamp="$(date '+%Y%m%d-%H%M%S')"
run_dir="${metrics_parent}/${started_stamp}-${uid}-$$"
umask 077
if [[ -L "$metrics_parent" ]] || ! mkdir -p -- "$metrics_parent" \
  || [[ ! -d "$metrics_parent" ]] || [[ ! -O "$metrics_parent" ]]; then
  echo "[rondo] cannot create a safe watchdog metrics parent: ${metrics_parent}" >&2
  exit 80
fi
if ! mkdir -- "$run_dir" || ! chmod 700 -- "$run_dir"; then
  echo "[rondo] cannot create the watchdog metrics directory: ${run_dir}" >&2
  exit 80
fi
metrics_file="${run_dir}/metrics.csv"
summary_file="${run_dir}/summary.env"
watchdog_heartbeat_file="${run_dir}/watchdog-heartbeat"
watchdog_wrapper_pid="$$"
watchdog_wrapper_start_ticks="$(awk '{print $22}' "/proc/${watchdog_wrapper_pid}/stat" 2>/dev/null || true)"
if [[ ! "$watchdog_wrapper_start_ticks" =~ ^[0-9]+$ ]]; then
  echo "[rondo] cannot identify the watchdog wrapper process" >&2
  exit 81
fi
umask 077
if ! : >"$watchdog_heartbeat_file" || ! chmod 600 -- "$watchdog_heartbeat_file"; then
  echo "[rondo] cannot create the watchdog heartbeat" >&2
  exit 81
fi
export RONDO_WATCHDOG_WRAPPER_PID="$watchdog_wrapper_pid"
export RONDO_WATCHDOG_WRAPPER_START_TICKS="$watchdog_wrapper_start_ticks"
export RONDO_WATCHDOG_HEARTBEAT_PATH="$watchdog_heartbeat_file"
export RONDO_WATCHDOG_SCRIPT_PATH="${script_dir}/with-build-lock.sh"

refresh_watchdog_heartbeat() {
  : >"$watchdog_heartbeat_file"
}

printf '%s\n' 'timestamp,elapsed_s,project_bytes,target_bytes,windows_c_used_bytes,windows_c_available_bytes,memory_current_bytes,memory_peak_bytes,memory_anon_bytes,memory_file_bytes,memory_kernel_bytes,memory_nonreclaimable_bytes,swap_current_bytes,swap_peak_bytes,cgroup_psi_full_avg10_bp,host_psi_full_avg10_bp,host_mem_available_kb,host_swap_free_kb,cargo_count,rustc_count,rust_lld_count,nextest_count' >"$metrics_file"

junit_expected=0
junit_status="not_applicable"
junit_profile=""
junit_path=""
junit_sha256=""
nextest_config=""
if [[ "${command_args[0]}" == "cargo" && "${command_args[1]:-}" == "nextest" \
  && "${command_args[2]:-}" == "run" ]]; then
  junit_profile="${NEXTEST_PROFILE:-}"
  unsupported_nextest_arg=""
  nextest_no_run=0
  for nextest_arg in "${command_args[@]:3}"; do
    case "$nextest_arg" in
      -P | -P?* | --profile | --profile=* | --config-file | --config-file=* \
        | --tool-config-file | --tool-config-file=*) unsupported_nextest_arg="$nextest_arg" ;;
      --no-run) nextest_no_run=1 ;;
    esac
  done
  if [[ "$junit_profile" != "local" || -n "$unsupported_nextest_arg" ]]; then
    junit_status="unsupported_invocation"
    {
      printf 'wrapper_status=preflight_failed\n'
      printf 'final_rc=83\n'
      printf 'junit_status=%s\n' "$junit_status"
      printf 'junit_profile=%s\n' "$junit_profile"
      printf 'junit_path=\n'
      printf 'junit_sha256=\n'
      write_effective_run_summary_fields
    } >"$summary_file"
    echo "[rondo] nextest evidence requires the local profile and no custom profile/config arguments" >&2
    exit 83
  fi
  if ((nextest_no_run == 0)); then
    junit_expected=1
    junit_status="pending"
    junit_path="${run_dir}/junit-local.xml"
    nextest_config="${run_dir}/nextest.toml"
    if ! rondo_prepare_nextest_config \
      "${PWD}/.config/nextest.toml" "$nextest_config" "$junit_path"; then
      junit_status="config_failed"
      {
        printf 'wrapper_status=preflight_failed\n'
        printf 'final_rc=83\n'
        printf 'junit_status=%s\n' "$junit_status"
        printf 'junit_profile=%s\n' "$junit_profile"
        printf 'junit_path=%s\n' "$junit_path"
        printf 'junit_sha256=\n'
        write_effective_run_summary_fields
      } >"$summary_file"
      echo "[rondo] cannot prepare the per-run nextest configuration" >&2
      exit 83
    fi
    command_args=(
      "${command_args[@]:0:3}"
      --config-file "$nextest_config"
      "${command_args[@]:3}"
    )
  fi
fi

{
  printf 'wrapper_status=starting\n'
  printf 'junit_status=%s\n' "$junit_status"
  printf 'junit_profile=%s\n' "$junit_profile"
  printf 'junit_path=%s\n' "$junit_path"
  printf 'junit_sha256=\n'
  write_effective_run_summary_fields
} >"$summary_file"

unit="rondo-build-${uid}-${started_stamp//[^0-9]/}-$$.scope"
echo "[rondo] watchdog metrics: ${run_dir}" >&2
echo "[rondo] limits: project warn/stop/max=${project_warn_bytes}/${project_stop_bytes}/${project_max_bytes} bytes, Windows C: free stop=${windows_c_free_stop_bytes} bytes, memory high/max=${memory_high}/${memory_max}, swap max=${swap_max}" >&2

cgroup_root=""
control_group=""
runner_pid=""

scope_population_state() {
  rondo_cgroup_population_state "$cgroup_root" "$runner_pid"
}

collect_junit_status() {
  junit_sha256=""
  if ((junit_expected == 0)); then
    junit_status="not_applicable"
    return 0
  fi
  IFS=$'\t' read -r junit_status junit_sha256 < <(
    rondo_inspect_junit_report "$junit_path"
  )
}

write_minimal_summary() {
  local wrapper_status="$1"
  local final_rc="$2"
  local command_rc="${3:-}"
  local summary_tmp="${summary_file}.tmp"

  collect_junit_status
  {
    printf 'unit=%s\n' "$unit"
    printf 'command_name=%s\n' "$command_name"
    printf 'wrapper_status=%s\n' "$wrapper_status"
    printf 'run_rc=%s\n' "$command_rc"
    printf 'final_rc=%s\n' "$final_rc"
    printf 'junit_status=%s\n' "$junit_status"
    printf 'junit_profile=%s\n' "$junit_profile"
    printf 'junit_path=%s\n' "$junit_path"
    printf 'junit_sha256=%s\n' "$junit_sha256"
    write_effective_run_summary_fields
  } >"$summary_tmp"
  mv -f -- "$summary_tmp" "$summary_file"
}

terminate_scope() {
  local reason="$1"
  local poll=0
  local population_state=""
  local systemd_kill_failed=0

  # Freezing is best-effort. Only a failed SIGKILL request means the D-Bus path
  # cannot terminate the scope and requires the direct cgroup fallback.
  systemctl --user kill --kill-whom=all --signal=SIGSTOP "$unit" >/dev/null 2>&1 || true
  systemctl --user kill --kill-whom=all --signal=SIGKILL "$unit" >/dev/null 2>&1 \
    || systemd_kill_failed=1
  if ((systemd_kill_failed == 1)) && ! kill_scope_without_dbus; then
    echo "[rondo] ${reason}: systemd and direct cgroup kill paths are unavailable; continuing supervision" >&2
  fi
  for ((poll = 0; poll < 10; poll++)); do
    population_state="$(scope_population_state)"
    if [[ "$population_state" == "gone" ]]; then
      return 0
    fi
    sleep 0.1
  done

  echo "[rondo] ${reason}: scope ${unit} is ${population_state} after a kill round; continuing supervision" >&2
  return 1
}

kill_scope_without_dbus() {
  [[ -n "$control_group" && "$control_group" == /* && "$control_group" != "/" ]] || return 1
  [[ -n "$cgroup_root" && "$cgroup_root" == "/sys/fs/cgroup${control_group}" ]] || return 1
  [[ "$cgroup_root" == /sys/fs/cgroup/* && "$cgroup_root" != "/sys/fs/cgroup" ]] || return 1

  rondo_kill_cgroup_subtree "$cgroup_root" "$control_group"
}

# Keeps calling `terminate_scope` until the cgroup subtree is confirmed empty.
#
# Each `terminate_scope` round is bounded, but this loop deliberately is not: giving up
# would hand control back while an unsupervised workload is still holding memory and disk.
# The `cgroup.events` populated bit covers descendants and remains authoritative if user D-Bus
# becomes unavailable. `MemoryMax` still caps the workload while this loop reports and retries.
terminate_scope_until_gone() {
  local reason="$1"
  local started_at="$SECONDS"
  local next_report="$((SECONDS + 30))"
  local elapsed=0
  local direct_members="unknown"
  local population_state="unknown"

  while true; do
    population_state="$(scope_population_state)"
    if [[ "$population_state" == "gone" ]]; then
      return 0
    fi
    if terminate_scope "$reason"; then
      return 0
    fi
    if ((SECONDS >= next_report)); then
      elapsed="$((SECONDS - started_at))"
      direct_members="$(rondo_cgroup_direct_member_count "$cgroup_root")"
      echo "[rondo] ${reason}: scope ${unit} remains ${population_state} after ${elapsed}s of kill attempts (direct_members=${direct_members}); still supervising" >&2
      next_report="$((SECONDS + 30))"
    fi
    sleep 0.1
  done
}

handle_exit() {
  local exit_rc=$?
  local population_state=""

  trap - EXIT INT TERM HUP
  population_state="$(scope_population_state)"
  if [[ "$population_state" != "gone" ]]; then
    echo "[rondo] wrapper exited while ${unit} was ${population_state}; stopping the supervised scope" >&2
    terminate_scope_until_gone "unexpected_wrapper_exit"
    if [[ -n "$runner_pid" ]]; then
      wait "$runner_pid" >/dev/null 2>&1 || true
    fi
  fi
  write_minimal_summary "unexpected_exit" "$exit_rc"
  exit "$exit_rc"
}

handle_signal() {
  local signal_name="$1"
  local signal_rc="$2"

  echo "[rondo] wrapper received ${signal_name}; stopping supervised scope ${unit}" >&2
  terminate_scope_until_gone "signal_${signal_name}"
  if [[ -n "$runner_pid" ]]; then
    wait "$runner_pid" >/dev/null 2>&1 || true
  fi
  write_minimal_summary "signal_${signal_name}" "$signal_rc"
  trap - EXIT INT TERM HUP
  exit "$signal_rc"
}

trap 'handle_exit' EXIT
trap 'handle_signal INT 130' INT
trap 'handle_signal TERM 143' TERM
trap 'handle_signal HUP 129' HUP

if ! refresh_watchdog_heartbeat; then
  trap - EXIT INT TERM HUP
  write_minimal_summary "watchdog_heartbeat_failed" 81
  exit 81
fi
systemd-run --user --scope --quiet --unit="$unit" \
  -p KillMode=control-group \
  -p MemoryHigh="$memory_high" \
  -p MemoryMax="$memory_max" \
  -p MemorySwapMax="$swap_max" \
  -- "${command_args[@]}" &
runner_pid=$!

for _ in $(seq 1 100); do
  control_group="$(systemctl --user show "$unit" -p ControlGroup --value 2>/dev/null || true)"
  [[ -n "$control_group" ]] && break
  if ! kill -0 "$runner_pid" 2>/dev/null; then
    break
  fi
  sleep 0.1
done
if [[ -z "$control_group" ]]; then
  run_rc=0
  terminate_scope_until_gone "watchdog_attach_failed"
  wait "$runner_pid" || run_rc=$?
  trap - EXIT INT TERM HUP
  echo "[rondo] failed to create or inspect the build cgroup; command status=${run_rc}" >&2
  write_minimal_summary "watchdog_attach_failed" 81 "$run_rc"
  exit 81
fi

cgroup_root="/sys/fs/cgroup${control_group}"
for counter in cgroup.events cgroup.procs memory.current memory.peak memory.stat memory.swap.current memory.swap.peak memory.pressure memory.events; do
  if [[ ! -r "${cgroup_root}/${counter}" ]]; then
    echo "[rondo] cgroup counter ${counter} is unavailable; stopping fail-closed" >&2
    terminate_scope_until_gone "missing_initial_counter_${counter}"
    wait "$runner_pid" >/dev/null 2>&1 || true
    trap - EXIT INT TERM HUP
    write_minimal_summary "missing_initial_counter_${counter}" 81
    exit 81
  fi
done

read_counter() {
  local path="$1"
  local value=""
  [[ -r "$path" ]] || return 1
  read -r value <"$path" 2>/dev/null || return 1
  [[ "$value" =~ ^[0-9]+$ ]] || return 1
  printf '%s' "$value"
}

read_keyed_counter() {
  local path="$1"
  local field="$2"
  awk -v field="$field" '$1 == field && $2 ~ /^[0-9]+$/ {print $2; found=1; exit} END {if (!found) exit 1}' \
    "$path" 2>/dev/null
}

read_psi_full_bp() {
  local path="$1"
  awk '$1 == "full" {for (i=2; i<=NF; i++) {split($i, pair, "="); if (pair[1] == "avg10" && pair[2] ~ /^[0-9]+([.][0-9]+)?$/) {printf "%d\n", pair[2] * 100; found=1; exit}}} END {if (!found) exit 1}' \
    "$path" 2>/dev/null
}

stop_reason="none"
cleanup_reason="none"
warning_emitted=0
peak_project="$project_before"
peak_target=0
peak_memory=0
peak_memory_nonreclaimable=0
peak_swap=0
peak_cgroup_psi_full_bp=0
peak_host_psi_full_bp=0
swap_over_since=0
psi_over_since=0
project_bytes="$project_before"
if [[ -d "$target_dir" ]]; then
  target_bytes="$(du -sx -B1 -- "$target_dir" 2>/dev/null | awk '{print $1}')"
else
  target_bytes=0
fi
started_seconds="$SECONDS"
next_progress_report="$((SECONDS + 30))"
sample=0
runner_done=0
runner_done_since=0
run_rc=0

while true; do
  population_state="$(scope_population_state)"
  if [[ "$population_state" == "gone" ]]; then
    break
  fi
  if [[ "$population_state" == "unknown" ]]; then
    stop_reason="cgroup_population_unknown"
    echo "[rondo] proactive stop: ${stop_reason}" >&2
    terminate_scope_until_gone "$stop_reason"
    break
  fi
  if ! refresh_watchdog_heartbeat; then
    stop_reason="watchdog_heartbeat_unavailable"
    echo "[rondo] proactive stop: ${stop_reason}" >&2
    terminate_scope_until_gone "$stop_reason"
    break
  fi
  now_seconds="$SECONDS"
  elapsed="$((now_seconds - started_seconds))"
  if ((sample % disk_sample_interval == 0)); then
    project_bytes="$(du -sx -B1 -- "$project_root" 2>/dev/null | awk '{print $1}')"
    if [[ -d "$target_dir" ]]; then
      target_bytes="$(du -sx -B1 -- "$target_dir" 2>/dev/null | awk '{print $1}')"
    else
      target_bytes=0
    fi
  fi
  windows_c_used=""
  windows_c_available=""
  read -r windows_c_used windows_c_available < <(read_windows_c_capacity) || true
  memory_current="$(read_counter "${cgroup_root}/memory.current" || true)"
  memory_peak="$(read_counter "${cgroup_root}/memory.peak" || true)"
  memory_anon="$(read_keyed_counter "${cgroup_root}/memory.stat" anon || true)"
  memory_file="$(read_keyed_counter "${cgroup_root}/memory.stat" file || true)"
  memory_kernel="$(read_keyed_counter "${cgroup_root}/memory.stat" kernel || true)"
  swap_current="$(read_counter "${cgroup_root}/memory.swap.current" || true)"
  swap_peak="$(read_counter "${cgroup_root}/memory.swap.peak" || true)"
  cgroup_psi_full_bp="$(read_psi_full_bp "${cgroup_root}/memory.pressure" || true)"
  host_psi_full_bp="$(read_psi_full_bp /proc/pressure/memory || true)"
  host_mem_available="$(awk '/^MemAvailable:/{print $2; exit}' /proc/meminfo)"
  host_swap_free="$(awk '/^SwapFree:/{print $2; exit}' /proc/meminfo)"
  oom_kill_count="$(read_keyed_counter "${cgroup_root}/memory.events" oom_kill || true)"
  cargo_count="$(pgrep -cx cargo || true)"
  rustc_count="$(pgrep -cx rustc || true)"
  rust_lld_count="$(pgrep -cx rust-lld || true)"
  nextest_count="$(( $(pgrep -cx cargo-nextest || true) + $(pgrep -cx nextest || true) ))"

  invalid_sample=""
  sample_values=(
    "project_bytes:${project_bytes}" "target_bytes:${target_bytes}"
    "windows_c_used:${windows_c_used}" "windows_c_available:${windows_c_available}"
    "memory_current:${memory_current}" "memory_peak:${memory_peak}"
    "memory_anon:${memory_anon}" "memory_file:${memory_file}" "memory_kernel:${memory_kernel}"
    "swap_current:${swap_current}" "swap_peak:${swap_peak}"
    "cgroup_psi_full_bp:${cgroup_psi_full_bp}" "host_psi_full_bp:${host_psi_full_bp}"
    "host_mem_available:${host_mem_available}" "host_swap_free:${host_swap_free}"
    "oom_kill_count:${oom_kill_count}" "cargo_count:${cargo_count}"
    "rustc_count:${rustc_count}" "rust_lld_count:${rust_lld_count}"
    "nextest_count:${nextest_count}"
  )
  for sample_value in "${sample_values[@]}"; do
    if [[ "${sample_value#*:}" =~ ^[0-9]+$ ]]; then
      continue
    fi
    invalid_sample="${sample_value%%:*}"
    break
  done
  if [[ -n "$invalid_sample" ]]; then
    # The cgroup can disappear between the population check and a counter read.
    # That is a normal short-command teardown race. While the unit is still
    # active, however, losing any safety counter must stop the workload.
    population_state="$(scope_population_state)"
    if [[ "$population_state" == "gone" ]]; then
      break
    fi
    stop_reason="resource_counter_unavailable_${invalid_sample}"
    echo "[rondo] proactive stop: ${stop_reason}" >&2
    terminate_scope_until_gone "$stop_reason"
    break
  fi
  memory_nonreclaimable="$((memory_anon + memory_kernel))"

  # A timed-out test can leave grandchildren in the scope after Cargo/nextest has
  # already returned. Do not wait forever or let those descendants keep network,
  # memory, and file descriptors alive: retain the real command status, allow a
  # short normal-cleanup grace period, then kill only this supervised scope.
  if ((runner_done == 0)) && ! kill -0 "$runner_pid" 2>/dev/null; then
    wait "$runner_pid" || run_rc=$?
    runner_done=1
    runner_done_since="$now_seconds"
  fi

  ((project_bytes > peak_project)) && peak_project="$project_bytes"
  ((target_bytes > peak_target)) && peak_target="$target_bytes"
  ((memory_peak > peak_memory)) && peak_memory="$memory_peak"
  ((memory_nonreclaimable > peak_memory_nonreclaimable)) && peak_memory_nonreclaimable="$memory_nonreclaimable"
  ((swap_peak > peak_swap)) && peak_swap="$swap_peak"
  ((cgroup_psi_full_bp > peak_cgroup_psi_full_bp)) && peak_cgroup_psi_full_bp="$cgroup_psi_full_bp"
  ((host_psi_full_bp > peak_host_psi_full_bp)) && peak_host_psi_full_bp="$host_psi_full_bp"

  if ((project_bytes >= project_warn_bytes && warning_emitted == 0)); then
    echo "[rondo] warning: project storage reached ${project_bytes} bytes" >&2
    warning_emitted=1
  fi
  if ((swap_current >= swap_sustained_stop_bytes)); then
    ((swap_over_since == 0)) && swap_over_since="$now_seconds"
  else
    swap_over_since=0
  fi
  if ((cgroup_psi_full_bp >= psi_full_stop_bp || host_psi_full_bp >= psi_full_stop_bp)); then
    ((psi_over_since == 0)) && psi_over_since="$now_seconds"
  else
    psi_over_since=0
  fi

  printf '%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' \
    "$(date --iso-8601=seconds)" "$elapsed" "$project_bytes" "$target_bytes" \
    "$windows_c_used" "$windows_c_available" "$memory_current" "$memory_peak" \
    "$memory_anon" "$memory_file" "$memory_kernel" "$memory_nonreclaimable" \
    "$swap_current" "$swap_peak" "$cgroup_psi_full_bp" "$host_psi_full_bp" \
    "$host_mem_available" "$host_swap_free" "$cargo_count" "$rustc_count" \
    "$rust_lld_count" "$nextest_count" >>"$metrics_file"

  external_build=""
  for proc_name in cargo rustc rust-lld cargo-nextest nextest; do
    while read -r pid; do
      [[ -n "$pid" ]] || continue
      process_group="$(awk -F: '$1 == "0" {print $3}' "/proc/${pid}/cgroup" 2>/dev/null || true)"
      [[ -n "$process_group" ]] || continue
      if [[ "$process_group" != "$control_group" && "$process_group" != "${control_group}/"* ]]; then
        external_build="${proc_name}:${pid}"
        break 2
      fi
    done < <(pgrep -x "$proc_name" || true)
  done

  if [[ -n "$external_build" ]]; then
    stop_reason="external_build_${external_build}"
  elif ((project_bytes >= project_max_bytes)); then
    stop_reason="project_reached_absolute_max"
  elif ((project_bytes >= project_stop_bytes)); then
    stop_reason="project_reached_proactive_stop"
  elif ((windows_c_available <= windows_c_free_stop_bytes)); then
    stop_reason="windows_c_free_below_floor"
  elif ((oom_kill_count > 0)); then
    stop_reason="cgroup_reported_oom_kill"
  elif ((memory_nonreclaimable >= nonreclaimable_stop_bytes)); then
    stop_reason="cgroup_nonreclaimable_memory_above_limit"
  elif ((swap_current >= swap_emergency_stop_bytes)); then
    stop_reason="cgroup_swap_above_emergency_limit"
  elif ((swap_over_since > 0 && now_seconds - swap_over_since >= swap_stop_seconds)); then
    stop_reason="cgroup_swap_sustained_above_limit"
  elif ((host_mem_available <= host_available_stop_kb)); then
    stop_reason="host_mem_available_below_floor"
  elif ((psi_over_since > 0 && now_seconds - psi_over_since >= psi_stop_seconds)); then
    stop_reason="memory_full_psi_sustained_above_limit"
  elif ((runner_done == 1 \
    && now_seconds - runner_done_since >= residual_grace_seconds)); then
    cleanup_reason="residual_processes_after_command"
  fi

  if [[ "$stop_reason" != "none" ]]; then
    echo "[rondo] proactive stop: ${stop_reason}" >&2
    terminate_scope_until_gone "$stop_reason"
    break
  fi
  if [[ "$cleanup_reason" != "none" ]]; then
    echo "[rondo] cleanup: ${cleanup_reason}" >&2
    terminate_scope_until_gone "$cleanup_reason"
    break
  fi

  sample=$((sample + 1))
  if ((SECONDS >= next_progress_report)); then
    echo "[rondo] command=${command_name} elapsed=${elapsed}s project=${project_bytes} target=${target_bytes} memory=${memory_current} anon=${memory_anon} file=${memory_file} swap=${swap_current} host_available_kb=${host_mem_available}" >&2
    next_progress_report="$((SECONDS + 30))"
  fi
  sleep 1
done

if ((runner_done == 0)); then
  wait "$runner_pid" || run_rc=$?
fi
trap - EXIT INT TERM HUP
project_after="$(du -sx -B1 -- "$project_root" 2>/dev/null | awk '{print $1}')"
if [[ -d "$target_dir" ]]; then
  target_after="$(du -sx -B1 -- "$target_dir" 2>/dev/null | awk '{print $1}')"
else
  target_after=0
fi
windows_c_used_after=""
windows_c_available_after=""
read -r windows_c_used_after windows_c_available_after < <(read_windows_c_capacity) || true
if [[ "$stop_reason" == "none" ]] \
  && { [[ ! "$windows_c_used_after" =~ ^[0-9]+$ ]] \
    || [[ ! "$windows_c_available_after" =~ ^[0-9]+$ ]]; }; then
  stop_reason="resource_counter_unavailable_windows_c_after"
fi

collect_junit_status
wrapper_status="complete"
final_rc="$run_rc"
if [[ "$stop_reason" != "none" ]]; then
  wrapper_status="proactive_stop"
  final_rc=125
elif ((junit_expected == 1 && run_rc == 0)) && [[ "$junit_status" != "retained" ]]; then
  wrapper_status="evidence_failed"
  final_rc=83
  echo "[rondo] nextest completed without a retained per-run JUnit report (${junit_status})" >&2
fi

summary_tmp="${summary_file}.tmp"
{
  printf 'unit=%s\n' "$unit"
  printf 'command_name=%s\n' "$command_name"
  printf 'wrapper_status=%s\n' "$wrapper_status"
  printf 'run_rc=%s\n' "$run_rc"
  printf 'final_rc=%s\n' "$final_rc"
  printf 'stop_reason=%s\n' "$stop_reason"
  printf 'cleanup_reason=%s\n' "$cleanup_reason"
  printf 'junit_status=%s\n' "$junit_status"
  printf 'junit_profile=%s\n' "$junit_profile"
  printf 'junit_path=%s\n' "$junit_path"
  printf 'junit_sha256=%s\n' "$junit_sha256"
  printf 'project_before_bytes=%s\n' "$project_before"
  printf 'project_after_bytes=%s\n' "$project_after"
  printf 'project_peak_sampled_bytes=%s\n' "$peak_project"
  printf 'target_after_bytes=%s\n' "$target_after"
  printf 'target_peak_sampled_bytes=%s\n' "$peak_target"
  printf 'windows_c_used_before_bytes=%s\n' "$windows_c_used_before"
  printf 'windows_c_used_after_bytes=%s\n' "$windows_c_used_after"
  printf 'windows_c_available_before_bytes=%s\n' "$windows_c_available_before"
  printf 'windows_c_available_after_bytes=%s\n' "$windows_c_available_after"
  printf 'memory_peak_sampled_bytes=%s\n' "$peak_memory"
  printf 'memory_nonreclaimable_peak_sampled_bytes=%s\n' "$peak_memory_nonreclaimable"
  printf 'swap_peak_sampled_bytes=%s\n' "$peak_swap"
  printf 'cgroup_psi_full_avg10_peak_bp=%s\n' "$peak_cgroup_psi_full_bp"
  printf 'host_psi_full_avg10_peak_bp=%s\n' "$peak_host_psi_full_bp"
  printf 'memory_high=%s\n' "$memory_high"
  printf 'memory_max=%s\n' "$memory_max"
  printf 'swap_max=%s\n' "$swap_max"
  write_effective_run_summary_fields
} >"$summary_tmp"
mv -f -- "$summary_tmp" "$summary_file"

if [[ "$junit_status" == "retained" ]]; then
  echo "[rondo] retained local junit report: ${junit_path}" >&2
fi

systemctl --user reset-failed "$unit" >/dev/null 2>&1 || true
echo "[rondo] finished status=${final_rc} command_status=${run_rc} stop=${stop_reason} cleanup=${cleanup_reason} project=${project_after} target=${target_after}; summary=${summary_file}" >&2

if rondo_payload_was_confirmed_oom_killed "$run_rc" "$stop_reason"; then
  echo "[rondo] the command was OOM-killed inside its ${memory_max} cgroup" >&2
fi
exit "$final_rc"
