# Plan 069 第四轮 correctness 修复

第四轮独立复验的四项中等级 finding 均确认存在，并在 Plan 069 原边界内关闭：

- durable Root close generation 登记预期 typed `SessionMeta` marker；local writer 在 recorder shutdown/materialization 后、移除 live
  owner 前完成最终复核。marker 失败不发 `ShutdownComplete`，close abort 保留同一 Root authority；live entry 记录 recorder 已 prepared，
  marker 恢复后的 close retry 不重复关闭已停止的 writer channel。
- 已有 `Unknown(N)` 在任何 reconcile 失败后保持 N/N+1 恢复窗口，直到成功读取并判断 committed snapshot；typed mismatch 不再错误收窄为
  `Unavailable(N)`。
- wait resolve 成功后保留 Team guard，timeout、mailbox 或 Team activity 任一正常分支胜出后、发出 Completed 前再次复核 durable state。
- blocking SessionMeta head reader 对解压后的 plain/zstd 输入累计限制 16 MiB 和 10 条非空记录，使用 limit+1 读取并以 `InvalidData`
  fail-closed；合法首行仍在损坏 tail 前停止。

close 采用现有 close generation + live entry prepared 状态，而未新增通用 prepare/finalize ThreadStore API。最初认为 recorder shutdown 可直接重试，
聚焦测试证实成功 Shutdown 会关闭 channel；随后以 prepared 状态修正并保留测试，没有削弱失败合同。

验证：

- `UV_CACHE_DIR=/home/sjc/desktop/RONDO/eval-data/uv-cache just fmt`、`git diff --check`：通过。首次默认 UV cache 位于只读目录，两个
  Python formatter 失败；Rust formatter 已执行，改用项目缓存后完整配方通过。
- core close/blocked-wait 产品回归：2/2 通过；watchdog
  `.codex/build-watchdog/20260825-003940-1000-1652243`，`complete`、退出码 0、`stop_reason=none`。
- team-state durable、thread-store authority/close、rollout blocking 邻近回归：29/29 通过；watchdog
  `.codex/build-watchdog/20260825-004009-1000-1653453`，`complete`、退出码 0、`stop_reason=none`。
- 调试失败不计入通过证据：首轮 close 领域测试发现 recorder channel 不可重复 Shutdown；首轮 core close fixture 因 delegating wrapper 使
  configured rollout path 不可见。两者均窄修后从失败切片重跑，并在上述合并正式轮通过。沙箱内 watchdog 因 systemd bus 不可用的 81
  退出未启动 Cargo，随后使用 canonical 宿主 cgroup/watchdog 正常执行。
- 按复验决定未重跑完整 workspace 或 clippy；未使用 Docker、真实模型或 GPU。

状态：`IMPLEMENTATION_COMPLETE / PREACCEPTANCE_REVIEW_PENDING / FINAL_PASS_BLOCKED_BY_#37198`。未进入阶段 E、未同步 main、未处理
`#37198`、未合并或推送。069 重型 Cargo 进程与 GPU compute 均已释放。
