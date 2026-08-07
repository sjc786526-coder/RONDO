#!/usr/bin/env bash
# Serialize heavy cargo builds and run them under a hard memory cap.
#
# Two independent protections, because they fail differently:
#
# 1. Mutual exclusion (flock). `.cargo/config.toml` caps a single build at
#    `build.jobs` rustc processes, but two agents (Claude Code in the main
#    workspace, Codex in a worktree, ...) each staying under that cap still add
#    up to twice the memory peak. Only one heavy build compiles at a time.
#
# 2. A cgroup memory cap (systemd transient scope). The 2026-08-08 incident was
#    not "a build died" -- it was that the *global* OOM killer picked systemd
#    and sd-pam and took the whole login session, VS Code Server and every agent
#    with it. Running the build inside a scope with MemoryMax means the kernel
#    kills processes *inside that scope* instead: the build fails with exit 137,
#    the machine and the sessions stay up. This is the protection that does not
#    depend on `build.jobs` having been estimated correctly.
#
# Usage: with-build-lock.sh <command> [args...]
#
# The lock is machine-global on purpose: per-worktree locks would not protect
# against the multi-worktree case. It is held by the wrapped process itself, so
# it is always released on exit, crash, or kill -- no stale-lock recovery
# needed.
#
# Escape hatches:
#   RONDO_BUILD_LOCK=<path>        use a different lock file
#   RONDO_BUILD_LOCK=0             skip locking entirely
#   RONDO_BUILD_MEMORY_MAX=<size>  hard cap for the build (default 16G)
#   RONDO_BUILD_SWAP_MAX=<size>    swap allowance for the build (default 2G)
#   RONDO_BUILD_CGROUP=0           skip the memory cap entirely
set -euo pipefail

lock_path="${RONDO_BUILD_LOCK:-${TMPDIR:-/tmp}/rondo-cargo-build.lock}"
mem_max="${RONDO_BUILD_MEMORY_MAX:-16G}"
swap_max="${RONDO_BUILD_SWAP_MAX:-2G}"

if [[ "$#" -eq 0 ]]; then
  echo "with-build-lock.sh: expected a command to run" >&2
  exit 1
fi

# --- 1. mutual exclusion -----------------------------------------------------
if [[ "${lock_path}" != "0" ]] && command -v flock >/dev/null 2>&1; then
  exec 9>"${lock_path}"
  if ! flock --nonblock 9; then
    echo "[rondo] waiting for another heavy cargo build to finish (lock: ${lock_path})" >&2
    flock 9
  fi
  # fd 9 stays open across exec and through the systemd scope, and is closed by
  # the kernel when the build exits.
fi

# --- 2. hard memory cap ------------------------------------------------------
# Needs systemd as PID 1, cgroup v2, and the memory controller delegated to the
# user slice. Probe once instead of guessing, and degrade to an uncapped run
# rather than refusing to build.
use_scope=0
if [[ "${RONDO_BUILD_CGROUP:-1}" != "0" ]] && command -v systemd-run >/dev/null 2>&1; then
  if systemd-run --user --scope --quiet --collect -p MemoryMax=1G -- true >/dev/null 2>&1; then
    use_scope=1
  else
    echo "[rondo] systemd user scope unavailable; running without a memory cap" >&2
  fi
fi

if ((use_scope == 0)); then
  exec "$@"
fi

rc=0
systemd-run --user --scope --quiet --collect \
  -p MemoryMax="${mem_max}" -p MemorySwapMax="${swap_max}" \
  -- "$@" || rc=$?

if ((rc == 137)); then
  echo "[rondo] the build was OOM-killed inside its ${mem_max} cgroup (MemorySwapMax=${swap_max})." >&2
  echo "[rondo] the host and your session were protected on purpose. Lower build.jobs in" >&2
  echo "[rondo] .cargo/config.toml, or raise RONDO_BUILD_MEMORY_MAX if the host has headroom." >&2
  echo "[rondo] See doc/development-environment.md section 3.5." >&2
fi

exit "${rc}"
