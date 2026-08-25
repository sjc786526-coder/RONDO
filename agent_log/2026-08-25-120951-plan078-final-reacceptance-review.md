# Plan 078 M4-S2 外部复验

## 结论

- `ACCEPTANCE_PASS / TASK_GOAL_COMPLETE`。
- 复验范围为上一轮报告 `cd25449` 后的整改提交 `7014250`。上一轮 1 项 High、2 项 Medium 均已关闭；未发现整改引入的新 High、Medium 或需要修正的 Low correctness finding。
- 本轮只读审查源码、回归、JUnit/watchdog 保存物、资源和并行分支现状，并执行 `git diff --check cd25449..7014250`、`git show --check 7014250` 与只读 `git merge-tree`；未运行 Cargo、Docker、模型、API、训练、测评、CI 或 PR。

## Finding 关闭情况

1. **exact owner retirement：关闭。** `send_op` 保留实际 owner；`InternalAgentDied`、tree close、residency eviction、bounded shutdown、archive/delete prepare 和 running-resume override 均只移除捕获的 `Arc<CodexThread>`。`ExactThreadRetirement` 在同一 map write lease 内先验证整批 owner，再与 availability gate、residency、Agent registry 和 generation 一起收口；Missing/Replaced 保留 replacement 并返回失败/`superseded`，不再按 ID 误删。
2. **subtree admission race：关闭。** `close_agent` 在 descendant snapshot 前取得 root-scoped subtree guard；spawn、lazy reload 和显式 resume 共用同一 admission gate。guard 跨 shutdown、Closed edge 持久化和 exact retirement 存活，所有非 terminal 退出均自动重开；durable Root 仍只能走原生 Root shutdown lifecycle。
3. **永久 closing 标记：关闭。** app-server pending unload 改为 generation token。SubmitFailed 立即释放；TimedOut 把 token 交给 late observer；exact finalizer 在 owner removed、Missing/Replaced 或 permit closed 后只释放本次 generation。replacement 的 callback/watch/thread state 不会被旧 finalizer 清理，旧 token 也不能清除后继操作。

相邻检查未发现新的锁序、失败重试或功能关闭态回归。新增 token 与 subtree guard 都挂接既有 ThreadManager/AgentControl/app-server lifecycle，没有引入第二 registry、通用事务或审计设施。

## 验证证据

- core 聚焦 JUnit `20260825-115021-1000-485813` 为 8 tests、0 failure、0 error，覆盖 subtree/admission、exact retirement、stale `InternalAgentDied`、durable Root 拒绝、shutdown fence、bounded shutdown 和 V2 unload/reload；wrapper `run_rc=0/final_rc=0`。
- app-server token JUnit `20260825-115243-1000-498830` 为 1 test、0 failure、0 error；wrapper `run_rc=0/final_rc=0`。
- core/app-server scoped fix wrapper `20260825-115630-1000-514331`、`20260825-115932-1000-525630` 均完成且退出码 0；执行日志说明无 lint 输出。后续只有格式化与 diff check，不要求重复重型测试。
- 先前 thread-store、app-server、fresh lifecycle、core 聚焦和 residency 整改证据未被本次修复的范围推翻；core 全量既有 16 项非 078 基线失败继续如实保留，不冒充全量 PASS，也不要求重跑。

## 代用户作出的决策

1. **接受 `7014250`，Plan 078 本地实现验收通过、任务目标完成。** 不要求继续扩建、重跑全量或补低价值审计设施。
2. **接受本轮资源处理。** 15 个 `codex_tui-*` incremental 目录属于用户已授权、可重建且精确归属 077 时段的缓存清理；未发现清理源码、证据或当前 core/app-server 缓存。当前项目约 `280028439377 B`、target `187314297963 B`，不再追加 Cargo 或清理；后续任何兼容门仍需用户重新明确批准和人工调度。
3. **更新整合顺序事实。** 审查期间 Plan 077 已通过并先进入 `main`，当前 main/origin 为 clean `305f904`，所以先前“078 先行”的条件决策自然失效。078 现在是后整合者；本次验收不授权 merge/push，也不在审查分支吸收新 main。
4. **获批整合时保留必要兼容门。** 只读 merge-tree 显示 `core/src/team/durable.rs`、`thread-store/src/lib.rs`、`thread-store/src/store.rs` 有三处直接文本冲突；语义分别是 077 query read seam 与 078 snapshot path/lifecycle-write 的加法收敛，app-server 变更可自动合并，静态未见互斥 API 设计。后续整合者应基于最新 main 合并两侧符号，并只跑一轮 query × lifecycle 聚焦兼容门；这属于用户批准 main 整合时的交付步骤，不阻断当前 worktree 实现验收。

## 当前状态

- 078 worktree clean，HEAD `7014250`；未 merge、rebase、cherry-pick 或 push。
- main/origin clean `305f904`，已包含 Plan 077，不包含 Plan 078。
- **验收通过 / 任务目标完成。**
