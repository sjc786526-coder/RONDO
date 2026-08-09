# 看门狗审查尾项与交付门禁

日期：2026-08-09

## 修改

- 开发环境不再把Bash `SECONDS`表述成单调时钟，明确它只用于记录真实经过秒数和减少`date`子进程。
- 补齐 `summary.env` 的九种 `junit_status`，区分启动期、preflight、非Nextest与最终报告状态。
- 为D-Bus终止失败增加内核侧兜底：优先写目标scope的 `cgroup.kill`，不可写时递归读取后代
  `cgroup.procs`，并在SIGKILL前通过 `/proc/<pid>/cgroup` 重新确认归属。直接路径只接受已校验的
  非根 `/sys/fs/cgroup<ControlGroup>`；失败后仍由 `cgroup.events: populated` 持续监督。
- 当前WBS切换到真实状态：上述设施与第一批测试维护已收口，39个严格失败和2个附加事项尚未实施。

## 验证

- `bash -n`：两个看门狗shell脚本通过。
- `python3 mydev/.github/scripts/test_build_watchdog_lib.py`：9/9通过，含原子 `cgroup.kill` 与递归
  PID归属复核两条新回归。
- `UV_CACHE_DIR=.uv-cache just fmt`、`just fmt-check`、`just test-github-scripts`：通过；脚本测试44/44。
- user D-Bus恢复后，`with-build-lock.sh /bin/sleep 0.2`：返回0，`stop_reason=none`、
  `cleanup_reason=none`、`junit_status=not_applicable`。
- skills ancestry定向 `just test`：1/1通过；JUnit直接留在本轮独占目录，
  `junit_status=retained`，summary SHA-256与重算一致，target历史路径未生成报告；cgroup内存峰值
  8,373,006,336 B、swap 0、资源停机原因均为none。
- 独立审查方在同一代码基线补跑三包Rust门禁：3,630运行/3,630通过，三包clippy退出0且零warning；
  其验证产物位于git-ignored目录，不纳入本提交。

完整workspace、其余包与Bazel未重跑；39+2仍是后续任务，不表述为通过。
