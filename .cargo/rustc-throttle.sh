#!/usr/bin/env bash
# 机器级 rustc 并发闸门，挂在 cargo 的 build.rustc-wrapper 上。
#
# 为什么需要它：`build.jobs` 只约束"单次 cargo 调用"内部的并发。两个 agent 各自
# 直接敲 `cargo build`，就是 2 × jobs 个 rustc 同时跑，谁也没超自己的额度，合起来
# 却回到内存危险区。`with-build-lock.sh` 的互斥锁只挡得住经过 `just` 的入口，
# 直接调 cargo 就绕过去了——那是一条纪律，不是机制。
#
# 这个脚本把闸门下沉到 rustc 本身：cargo 每编译一个单元都会经过它，所以无论从
# `just`、裸 cargo、哪个 worktree、哪个 agent 发起，全机器同时运行的 rustc 数量
# 都被同一个信号量卡住。它是总并发兜底，不保证同一时刻只有一个 Cargo 构建；后者
# 仍由 `with-build-lock.sh` 的机器级锁负责。
#
# 两道控制：
#   1. 计数信号量：最多 RONDO_RUSTC_SLOTS 个 rustc 同时运行（flock 占位文件，
#      槽由 rustc 进程本身持有，退出/崩溃/被杀自动释放）。
#   2. 准入水位：可用内存低于 RONDO_RUSTC_MEM_FLOOR_MB 时不放新的 rustc 进来，
#      形成背压。已在跑的 rustc 数量由信号量封顶，所以总量有界。
#
# 任何一步出问题都明确告警并 fail-open 直接执行 rustc，绝不静默失效或把构建卡死。
#
# 逃生口：
#   RONDO_RUSTC_THROTTLE=0        完全关闭
#   RONDO_RUSTC_SLOTS=<n>         改并发槽数（默认 6，与 build.jobs 对齐）
#   RONDO_RUSTC_MEM_FLOOR_MB=<n>  改准入水位（默认 3072）
set -uo pipefail

if [[ "$#" -eq 0 ]]; then
  echo "rustc-throttle.sh: expected the rustc path as the first argument" >&2
  exit 1
fi

if [[ "${RONDO_RUSTC_THROTTLE:-1}" == "0" ]] || ! command -v flock >/dev/null 2>&1; then
  exec "$@"
fi

slots="${RONDO_RUSTC_SLOTS:-6}"
floor_mb="${RONDO_RUSTC_MEM_FLOOR_MB:-3072}"

if [[ ! "$slots" =~ ^[1-9][0-9]*$ ]] || [[ ! "$floor_mb" =~ ^[0-9]+$ ]]; then
  echo "[rondo] invalid rustc throttle settings; running rustc without the throttle" >&2
  exec "$@"
fi

# Do not derive this path from TMPDIR: different agents can have different temporary
# directories, which would split the supposedly machine-wide semaphore.
uid="${UID:-}"
if [[ -z "$uid" ]]; then
  uid="$(id -u 2>/dev/null || true)"
fi
runtime_dir="/run/user/${uid}"
if [[ -z "$uid" ]] || [[ ! -d "$runtime_dir" ]] || [[ ! -w "$runtime_dir" ]]; then
  runtime_dir="/tmp/rondo-runtime-${uid:-unknown}"
fi
slot_dir="${runtime_dir}/rondo-rustc-slots"

umask 077
if [[ -L "$runtime_dir" ]] || [[ -L "$slot_dir" ]] \
  || ! mkdir -p "$slot_dir" 2>/dev/null \
  || ! chmod 700 "$runtime_dir" "$slot_dir" 2>/dev/null \
  || [[ ! -d "$slot_dir" ]] || [[ ! -O "$slot_dir" ]]; then
  echo "[rondo] rustc throttle directory is unavailable or unsafe; running without the throttle" >&2
  exec "$@"
fi

# --- 1. 准入水位：可用内存不足时先不放进来（最多等 10 分钟，绝不无限阻塞） ---
waited=0
while ((waited < 600)); do
  avail=$(awk '/^MemAvailable:/{print int($2/1024); exit}' /proc/meminfo 2>/dev/null)
  [[ -z "${avail:-}" ]] && break
  ((avail >= floor_mb)) && break
  sleep 1
  waited=$((waited + 1))
done

# --- 2. 计数信号量：抢一个槽，抢到就 exec，槽随 rustc 进程一起释放 ---
while :; do
  for ((i = 1; i <= slots; i++)); do
    exec 8>"$slot_dir/$i" 2>/dev/null || exec "$@"
    if flock --nonblock 8; then
      exec "$@"
    fi
  done
  sleep 0.1
done
