# Plan 043 / Multi M-4 第三轮整改后独立复验

日期：2026-08-17 ｜ 审查对象：`worktree-043-multi-m4-coordination-closure@59b0f33` ｜ 前次复验：`31ecafc` ｜ 基线：`main@af1063d`

## 结论

- **验收不通过**：dead resident 分类与跨实例 dump cursor 已正确闭合，正式 app-server 删除也接入了 begin/finish；但 begin 与
  finish 之间没有 transition-in-progress 语义，同一个中间 availability epoch 仍可在 rollout 删除前后分别表示
  `recoverable_unloaded` 和 `unavailable`。
- **任务目标失败（当前提交尚未完整实现预期）**：`59b0f33` 的绝大部分实现应保留，但 availability state version 与冻结 dump
  cursor 仍不成立，不能按当前提交宣称 M-4 完成、合并或推送。
- 只剩一个窄的并发语义缺口。增加轻量 in-progress counter/token 或等强 fail-closed 重试即可，不需要事务系统、审计设施、签名链
  或外部服务。

## 已确认整改有效

- producer 只有在 loaded 且 `CodexThread::is_running()` 时才报告 `available`。dead resident 会在 write lock 下复验，经
  availability gate 移除并 bump，再按 stored resume material 派生 recoverable / unavailable / unknown；未发现误删或锁序反转。
- `delete_stored_thread` 与正式 app-server `thread/delete` 都调用 begin/finish，不再存在“完全无通知的正式删除入口”。
- DumpCursor 已携带完整 TeamInstanceId，五段编码/解码、工具续页生成和跨实例 `InstanceReset` 都正确；旧四段 cursor 拒绝。
- 上轮已通过的 explicit-resume recoverability、VersionFact 有界分页、裸 offset 拒绝、ThreadId 关系字段、lifecycle no-op、
  observe generation、退休元数据与 publication stats 均未回退。

## 唯一验收阻断

### P1：begin/finish 两次 bump 仍允许同一中间 epoch 对应两种 availability

`ThreadManager::delete_stored_thread` 在 `core/src/thread_manager.rs:725-739` 执行：begin 短持 gate 并把 E0 推到 E1，释放 gate，
await 实际删除，最后 finish 再短持 gate 把 E1 推到 E2。app-server 路径在
`app-server/src/request_processors/thread_delete.rs:50-58` 使用相同模式。两次 bump 之间没有 active counter、token 状态或让 snapshot
fail-closed 的判断。

因此存在可达时序：

1. begin 后、rollout 尚在时，availability snapshot 合法返回 `recoverable_unloaded/E1`；
2. Local store 在 `thread-store/src/local/delete_thread.rs:163` 删除 rollout，随后仍在
   `remove_thread_name_entries(...).await`（同文件 `:165-169`）执行收尾；
3. 另一 Tokio worker 可在 finish 前读取到 rollout 已缺失，合法返回 `unavailable/E1`；
4. finish 最后才推进到 E2。

所以 E1 仍不是一个唯一的控制面状态版本。第一页可携带 recoverable/E1，第二页在删除后用同一 cursor 得到 unavailable/E1 而不被
拒绝；retirement 也可记录 unavailable/E1，而系统此前已经合法发布过 recoverable/E1。简单删除场景未必会错误退休仍可恢复者，
但“退休对应状态版本”和“dump cursor 冻结同一 availability snapshot”两个 M-4 核心合同仍被直接破坏。

新增 `beginning_a_store_transition_moves_epoch_before_the_row_disappears` 只证明 begin 先 bump；测试手工 begin 后又调用自带一组
begin/finish 的 delete helper，没有暂停在 rollout 已删除、finish 未执行的窗口，也没有验证 snapshot / dump / retire 在 transition
期间 fail-closed。

处理要求：transition 期间不能对外返回普通 availability snapshot，也不能允许 retire 按中间 epoch 提交。最小方案可用一个跨
await 持有但不持 mutex 的 active counter/token：begin 使 transition active 并 bump，snapshot/retire 在 active 时返回 unknown、
拒绝或有界重试，finish 清除 active 并再次 bump。也可采用其他等强轻量方案；不要求通用事务设施。

## 替用户作出的决策

1. 接受并保留 `59b0f33` 的 dead-resident 清理、TeamInstanceId cursor 和两阶段通知接缝；下一轮只补 transition-active 语义，
   不回滚主体实现。
2. in-progress 期间必须 fail-closed：availability 可返回 unknown 或有界重试，但 Root 不得退休，dump 续页不得把删除前后状态拼在
   同一 epoch。具体 counter/token 类型由执行者选择。
3. 建议让 begin 返回可跨 await 持有、Drop/显式 finish 都能收口的轻量 token，以降低错误/取消路径漏 finish 的风险；这是软建议，
   等强实现可自主选择，不扩展成事务框架。
4. 补一条带 barrier 的小回归，固定“删除已可见但 finish 尚未执行”期间 snapshot/retire fail-closed；随后只跑领域包、精确
   availability 测试、M-4 产品纵切和必要的 M-1—M-3 回归，不跑全 workspace。
5. 继续在 043 工作树整改；不进入 M-5，不合并、不推送。

执行者没有留下必须由用户另选的产品决策；上述取舍由本轮审查直接作出。

## 独立验证与现场

| 项目 | 结果 | 说明 |
|---|---|---|
| `git diff --check 31ecafc..59b0f33` | 通过 | 第三轮整改差异无 whitespace error |
| `just test -p codex-team-state --lib` | 125/125 通过 | 共享构建锁与资源看门狗；run `fc267636-b1c9-4fbd-8b7a-99cf8e946cc2` |
| `just test -p codex-core --lib -- agent::control::availability resume_agent_restores_closed_agent_and_accepts_send_input` | 6/6 通过 | 2205 skipped；run `c9f6d660-1d31-468a-8493-67b341490095` |
| M-1—M-4 产品套件 | 本轮未重跑 | 采用执行日志的 17/17 结果；避免重复较重门禁 |

未运行全 workspace、Docker、真实 API、本地模型、付费资源或测评。复验前 043 工作树干净，
`main = origin/main = af1063d` 且主工作区干净。本报告是本轮唯一产品仓库受跟踪改动；未修改实现、Plan/WBS，未合并、未推送、
未归档分支。当前 WBS/Plan 中“第三轮整改待再审查”不构成验收通过；M-5 仍未开始。
