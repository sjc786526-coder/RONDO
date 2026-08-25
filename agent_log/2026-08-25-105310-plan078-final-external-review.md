# Plan 078 M4-S2 外部终审

## 结论

- **验收不通过；任务目标失败。**
- 本轮只做源码、提交、测试保存物和资源记录的只读复核，并执行 `git diff --check b077462..cfbf81b`；未运行 Cargo、Docker、模型、API、训练、测评、CI 或 PR。
- 身份恢复、fork/new/clear、durable Root close、delete 顺序和多数冷态语义的实现方向正确，现有聚焦与相邻测试证据可信；但最终候选仍有 1 项 High、2 项 Medium correctness finding。它们都集中在 owner replacement 与 descendant admission 的并发收口，不需要建设新 registry、事务平台或审计设施。

## Findings

### High — shutdown 完成后的按 ID 删除可误删同 ID replacement owner

多个路径先捕获旧 `Arc<CodexThread>` 并等待它 shutdown，随后却只按 `ThreadId` 删除当前 map entry：

- app-server archive/delete 的同步准备路径：`app-server/src/request_processors/thread_processor.rs:927-967`；
- app-server 带 override 的 running resume 路径：`app-server/src/request_processors/thread_processor.rs:3610-3626`；
- core `close_agent`/tree finalize：`core/src/agent/control/legacy.rs:10-37,65-98`；
- V2 residency eviction：`core/src/agent/control/residency.rs:127-148`；
- bounded shutdown 的最终批量删除：`core/src/thread_manager.rs:1140-1172`。

旧 owner 终止后、删除取得 map 写锁前，显式 `resume_agent` 可以把同一 durable ThreadId 的 replacement 插入 map。上述旧 finalizer 随后会删除未被它关闭的 replacement；archive/delete 还可能继续清理 ID 级 app-server 状态并让 Root barrier 看不到仍可 mutation 的 descendant。代码已经有 `remove_thread_if_same`（`core/src/thread_manager.rs:1112-1135`），但同步完成路径没有一致使用。

修复结果约束：凡 shutdown 等待绑定了具体 owner，最终移除也必须绑定同一 owner；若 current owner 已替换，保留 replacement，当前 lifecycle 操作明确失败/重试，且不得继续做 ThreadId 级 teardown、archive/delete 完成或 registry 释放。具体 API/返回结构由执行者按现有架构自主选择。

### Medium — `close_agent` 只关闭一次 descendant 快照，关闭期间仍可接纳新 descendant

`shutdown_agent_tree_runtimes` 在开始时读取一次 descendant tree，随后按该快照关闭并持久化 target `Closed` edge（`core/src/agent/control/legacy.rs:65-98,115-141`）。该过程没有进入 Team admission closing 状态，也没有在提交 Closed 前重新验证 subtree；与此同时 `spawn_agent` 和显式/lazy resume 仍可取得现有 admission guard。

因此 child 正在关闭时可并发产生或恢复 grandchild，使 late descendant 逃过快照；父 edge 仍可能标记 Closed 并报告成功，留下活的 orphan descendant。修复应复用/窄扩展现有 lifecycle admission 语义，或采用等强的最终重验证，保证一次成功的 subtree close 不遗留关闭开始后进入的 mutation-capable descendant。无需新建第二套 close coordinator。

### Medium — exact-owner mismatch 会永久遗留 app-server `closing` 标记

idle/late shutdown 已正确使用 `remove_thread_if_same`，但 mismatch 分支在
`app-server/src/request_processors/thread_lifecycle.rs:464-470` 直接返回；本次 unload 设置的
`pending_thread_unloads` 只在成功移除后的 `:472-476` 才清除。旧 owner 已被移除或被 replacement 替换时，后续 attach/resume 会一直收到 `thread is closing`，只能依赖进程重启恢复。

修复时应在 mismatch/owner 已不存在的分支释放本次 pending 标记，同时继续保留 replacement 的 callback、watch 和 thread state；补一条旧 owner 被替换或提前移除后的聚焦回归即可。

## 已核验证据与非阻断项

- 保存的 JUnit/summary 与执行摘要相符：thread-store `199/199`、app-server `1134/1134`、core 聚焦 `19/19`、fresh 正式组 `23/23`、禁用重试 `1/1`、最终 residency 整改 `3/3` 均为退出码 0。最终 `3/3` 的 JUnit 哈希和源码/提交时间顺序一致。
- core 全量 `3417 pass / 16 fail / 8 skipped` 的 16 项可归因于 077 共享 schema artifact、Publication Critic 外部 service-bin、旧 relative-cwd/empty-rollout fixture 和 realtime timeout；未发现它们由 078 引入，也未发现执行者把它们冒充为 PASS。本轮不要求为此重跑全 core。
- archive/unarchive 在 rename 已完成而 SQLite metadata 更新失败时，会明确返回“文件已移动但 metadata 更新失败”；现有 locator 也有文件系统 fallback/read-repair。Plan 078 要求诚实暴露 partial/unknown，并未硬性要求同一操作幂等重试或通用回滚，因此本终审不把它升级为 finding，也不要求引入事务设施。
- clippy/fmt 保存物足以支持执行记录，但单靠摘要不能独立证明逐条 warning 文本；这不值得追加重型重跑。`git diff --check` 当前通过。

## 代用户作出的决策

1. **当前不合并 078。** 先关闭上述 1 High、2 Medium，再做外部复验；无需扩大到与 finding 无关的重构、全 workspace 测试或新审计设施。
2. **修复验证保持聚焦。** 优先覆盖 exact-owner replacement 交错、close 与 descendant admission 交错、pending closing 清理，并只跑受影响的 core/app-server 最小门；不因本轮 finding 重跑 thread-store 全量、core 全量或 fresh 23 项全组，除非修复实际扩张到这些语义。
3. **不追认新的重型授权。** 保存物显示项目 `280044613632 B`、共享 target `185999601664 B`，已经高于 Plan/根规则的 260GB 绝对线；执行记录中的临时 `270/285/290GB` 例外是否得到用户逐批明确授权，仓库内无法独立证明。当前不得再启动 Cargo。执行者可先完成源码和轻量检查；如需聚焦 Cargo，必须由用户重新明确批准准确批次及资源处置/临时门限，仍由用户人工调度，且不得擅自清理 077 或共享 069 target。
4. **后续合并顺序采用 078 先行。** 077 当前虽已 clean 提交，但其独立审查仍未通过；078 修复并最终验收通过后，适合先进入本地 main，077 再基于最新 main 收敛四处 shared-file 文本冲突并承担 query × lifecycle 聚焦兼容验收。此决定不授权当前 merge 或 push。

## 当前状态

- 078 分支提交内容完整且 worktree clean，但存在未关闭 correctness finding。
- **项目状态：验收不通过 / 任务目标失败。**
