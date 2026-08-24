# Plan 058 与 Plan 054 共享重型资源互斥事件

## 事件

Plan 058 从 clean detached source `23567b668d8ce67f72dcaa320fec1dcb91e96c9c` 运行 Local legacy 与
code-mode companion 构建。两段均通过本 worktree 的 `scripts/with-build-lock.sh`、canonical
`/run/user/1000/rondo-cargo-build.lock` 和 systemd watchdog，分别在 `22m57s`、`19m46s` 后返回
`status=0`、`stop=none`、`cleanup=none`，swap 峰值为 `0`。

并行 Plan 054 随后报告：其 Skywork 模型校准期间检测到外部 Cargo PID `99438`，以
`external_build_cargo:99438` fail-closed 终止。仅凭跨任务 PID 不能在本进程命名空间内做确定归属，但事件时间与
Plan 058 Cargo 窗口高度重合，因此按高概率由本次构建触发处理，不把它静默归为普通锁等待。

## 判断与影响

- Plan 058 没有直接 Cargo、关闭锁或放宽 watchdog；本侧命令和 summary 均证明它使用了规定入口。
- 若 Plan 054 在完整模型生命周期持有同一 canonical 锁，Plan 058 应排队而不会启动。实际重叠说明当时的 Plan 054
  runner 没有覆盖完整模型生命周期、使用了不同 lease，或存在等价的共享互斥缺口；Plan 054 已把本次校准保留为
  infra failure 并计划修复后从冻结起点重跑。
- 资源互斥硬约束已被事实破坏，因此 `23567b6` 的构建即使字节与 source 可复验，也不作为 Plan 058 的合规
  commissioning build。尚未初始化 campaign、启动 Docker 或发送 API，Plan 058 费用仍为 `0.000000 USD`。
- 已终止只在等锁、尚未创建 companion bundle 的封装进程。只读确认 Plan 054 正式 measurement 终态，并等待
  canonical 锁实际释放后，通过 `binary_freeze cleanup` 删除 exact `23567b6` target；确认 clean HEAD 后注销 detached
  measurement worktree；核对 legacy manifest source/product/digest 与目录仅含 `codex + manifest.json` 后删除
  `1,260,206,189` bytes artifact。可再生成 target 终态为 `0`，build summaries 与本日志继续保留。

## 后续门禁

- Plan 058 的后续封装、Docker 和 Cargo 继续使用 canonical 共享锁；槽被占用时每三分钟轮询一次。
- 下一次实际 Cargo 前，除取得锁外，还要只读确认 Plan 054 正式 measurement 已终态/模型资源已释放，避免把瞬时
  空锁误认为完整空闲窗口；本次重建前双重门已满足。
- 不修改、清理或重解释 Plan 054 的 run、watchdog、模型、账本和失败证据；最终交付同时报告本事件、失效构建和
  重建证据。
