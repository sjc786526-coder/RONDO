# 065 Root Thread Writer 复用补充验收

日期：2026-08-24 ｜ 验收对象：`worktree-065-durable-workspace-runtime-planning`

## 结论

**复用方向通过，但当前 WBS 暂不通过最终验收。** 冻结 Codex `v0.147.0` 的 per-Thread active-writer ownership 可以作为
Durable Team Session 的跨进程单写者基础；RONDO 只需证明当前进程持有该 Team 的 Root Thread writer，不需要建设 Team 专用锁、
lease、writer registry 或强制接管。

本轮仍发现 1 项高等级恢复缺口和 1 项中等级并发读取合同缺口。二者都可通过窄的 M4-A/S1/S2 合同修订闭合，不改变总体架构，
也不需要现在运行 Cargo、Docker、真实 API、模型、训练或测评。

## 已验证事实

- `LocalThreadStore` 的 create/resume 按当前 `ThreadId` 获取 OS 文件锁，竞争 acquisition 返回 active-writer conflict；成功
  shutdown/discard 从 live-recorder map 移除 writer guard（`codex-source-code/codex-rs/thread-store/src/local/live_writer.rs:25-110,144-188`）。
- writer guard 的 drop 关闭锁文件并清理路径；新进程首次 acquisition 会清理已经没有 OS lock 的残留文件
  （`codex-source-code/codex-rs/thread-store/src/local/writer_lock.rs:39-87,118-189`）。
- 两个真实 app-server 子进程的 legacy/paginated 回归覆盖竞争 resume 被拒绝，以及原写者成功 shutdown 后另一进程可以 resume
  （`codex-source-code/codex-rs/app-server/tests/suite/v2/thread_resume.rs:261-341`）。
- read/list 不取得 active-writer ownership；read 可能短暂读取进程内 live-recorder map 来定位活动 rollout，因此准确边界是
  “不要求 writer ownership”，不是完全无内部同步。
- 原生锁只按单个 ThreadId 生效。当前 WBS 已正确要求 child mutation 额外证明本进程持有 Root Thread writer；child 自身 writer
  不能冒充 Root ownership。这是资格接缝，不是第二套锁。

## Findings

### F065-RW-01（高）：失败 shutdown 或 session task 崩溃会在存活 daemon 内遗留 writer

`WriterLockGuard` 由 `LocalThreadStore.live_recorders` 持有，只有成功 shutdown/discard 才被移除。rollout drain 失败时 writer
按设计继续存活以便重试，但 session shutdown handler 在该失败后仍发送 `ShutdownComplete` 并返回成功；manager 随后可以把 thread
当作 completed 移除。session-loop `JoinError` 也被吞掉，task 异常退出不等于 OS 进程退出。结果是同一 app-server 进程内 writer
guard 仍在，后续 resume 会持续收到 duplicate live writer/conflict，直到整个进程退出。

证据：

- `codex-source-code/codex-rs/rollout/src/recorder.rs:1064-1088`
- `codex-source-code/codex-rs/core/src/session/handlers.rs:622-666,861-870`
- `codex-source-code/codex-rs/core/src/session/mod.rs:919-927`
- `multidev/codex-rs/core/src/thread_manager.rs:1078-1123`

窄修订要求：WBS 区分“完整进程退出”和“存活进程内 session/shutdown 失败”；只有 writer 已成功释放才能报告关闭完成。失败时保持
failed/closing 且可重试；若显式 discard，必须诚实声明放弃未持久数据。S2 加一条相应回归。不得以此为理由引入 Team lock、抢锁或
无条件强制接管。

### F065-RW-02（中）：非 owner 并发只读缺少最小原子性合同

WBS 允许其他进程在 Root writer 活跃时读取权威 Team 状态，但 active-writer lock 只排斥第二个 writer，不会自动替未来 Team
持久层定义读一致性。当前最小持久合同没有明确读者应看到完整已提交 revision，还是可能读到 mutation 的中间组合。

窄修订要求：只读查询必须返回一个完整已提交 Team revision，或明确返回 stale/unknown/unavailable；不得返回跨 revision 的撕裂
状态。用一条 writer mutation 与并发 read 的 deterministic/fake 回归验证即可，不新增 Team read lock、snapshot 平台或审计设施。

## 代用户作出的决策

- **接受 Root Thread active-writer 复用方向。** 不采纳“因为 child lock 独立，所以必须新增 Team Session lease”的扩大化方案；正确
  接缝是所有 Team mutation 都证明当前进程持有既有 Root Thread writer。
- **不接受当前版本最终 PASS。** F065-RW-01 与 F065-RW-02 需先进入权威 WBS，再做一次窄复验。
- **V1 不建设跨进程 mutation 转发平台。** 非 owner 控制面可以只读；mutation 未连接到 owner app-server 时返回 conflict/
  unavailable，由调用者连接已加载 Root Session 的进程，不新增 daemon、queue 或 IPC router。
- **TUI snapshot 仍按就近 `AGENTS.md` 的影响范围执行。** 仅用户可见 TUI 变化运行对应 snapshot，不把纯 S/W 或 writer backport
  拖入无关门禁；本项不作为本轮新增 finding。
- **不运行重型验证。** 本轮源码和既有测试定义足以确认规划缺口；未运行 Cargo、Docker、真实模型/API、训练或测评。
- **不代行提交或合并。** 本报告不授权 commit、merge、push 或启动 M4-A。
