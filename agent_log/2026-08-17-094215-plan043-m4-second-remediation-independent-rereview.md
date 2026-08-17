# Plan 043 / Multi M-4 第二轮整改后独立复验

日期：2026-08-17 ｜ 审查对象：`worktree-043-multi-m4-coordination-closure@c203e34` ｜ 前次复验：`035977c` ｜ 基线：`main@af1063d`

## 结论

- **验收不通过**：`c203e34` 已正确修复 shutdown / registry miss 的恢复能力分类、无界 Version Fact 列表、裸 dump offset 和
  重复 label 身份歧义；但 store deletion 仍发生在 availability gate 外，已终止但尚留在 loaded map 的 runtime 仍被误报为
  available，dump cursor 也未绑定 team instance。
- **任务目标失败（当前提交尚未完整实现预期）**：M-4 主体和本轮绝大部分修复均应保留，但以上三点分别影响退休状态版本、
  producer 四类可用性和确定性分页，不能按 `c203e34` 宣称完成、合并或推送。
- 剩余问题都可在现有 ThreadManager / AgentControl / DumpCursor 内窄修；不需要跨进程事务、复杂审计、可信链、外部日志平台或
  新的身份体系。

## 已确认整改有效

- 产品 availability 已与自动 V2 load 解耦：`probe_producer_recoverability` 会按 stored rollout + history 判断显式
  `resume_agent` 能力。shutdown 后 registry 已释放但 rollout 仍在的成员现在是 `recoverable_unloaded`，且现有回归证明可以
  resume 并继续接收输入。
- loaded map 的正常 insert/remove、residency 清理和 registry release 已与 retire 最终 epoch 重验使用同一同步 gate；这些
  无 await 的临界区未发现锁序或死锁问题。
- Version→Fact 已拆为独立 `VersionFact` 行并计入统一页上限；裸 offset 在工具层和 TeamStore 层都被拒绝。
- Event / Version / Route / Fact / Visibility / Activity、change-log actor 与 wake target 均在 label 外补了 ThreadId，重复 label
  可以消歧。
- 上轮已确认的 lifecycle no-op、Fact 插页 `observe_generation`、退休元数据和 ThreadId publication stats 分页均保留。

这些部分不应在下一轮推倒重做。现场轻量测试全部绿色，但没有覆盖下面三个反例。

## 验收阻断

### P1：store deletion 没有被 availability gate 线性化

`ThreadManager::delete_stored_thread` 在 `core/src/thread_manager.rs:723-739` 先 await 实际删除，成功后才取得 gate 并 bump。
正式 app-server `thread/delete` 同样先在 `app-server/src/request_processors/thread_delete.rs:50-55` 修改 store，之后才调用
`notify_thread_store_changed`；而该通知在 `core/src/thread_manager.rs:744-746` 只 bump，根本没有取得 gate。

因此 store 已从 recoverable 变为 unavailable、generation 尚未推进的窗口仍然存在；app-server 的无锁通知也可以在 retire
持 gate 完成 live-epoch 检查后并发推进 generation。此时退休可以记录一个不对应提交时控制面状态的旧 epoch，dump cursor 也可在
删除可见但 bump 尚未发生时接受旧 availability epoch。`team_retire` 虽在
`core/src/tools/handlers/team_tools/retire.rs:45-73` 持 gate 提交，但不能线性化 gate 外已经发生的 store mutation。

现有 `a_live_epoch_that_moved_during_commit_is_refused` 仍只向 TeamStore 传入预制的不同 epoch，没有运行真实 store transition / retire
竞态，因而没有验证新增 gate 的完整范围。

处理要求：store deletion 的“变化可见点”、generation 和 retire final check 必须进入同一线性化协议。执行者可选两阶段
transition/version、受控 store mutation 接缝或其他等强轻量方案；不要求跨 await 持同步锁，也不要求通用事务设施。

### P1：已终止但仍驻留 map 的 runtime 被误标为 available

`probe_producer_recoverability` 在 `core/src/agent/control/spawn.rs:319-331` 仅凭 `get_thread().is_ok()` 返回 `Loaded`。但
`get_thread` 只验证 map membership；`CodexThread::is_running()`（`core/src/codex_thread.rs:550-552`）才检查提交通道仍可用。
仓库恢复路径自身也在 `core/src/thread_manager.rs:1713-1734` 把 map 中 `!is_running()` 的 thread 当作失效对象移除并重建。

在 session 异常终止到清理 map 的窗口内，当前 dump 会显示 `available`，但向该 Agent 提交任务会得到
`InternalAgentDied`。这不符合“当前可用 = 正在运行或可继续接收任务”，也会让 availability epoch 与真实可接收能力脱节。

处理要求：loaded 分类必须确认 runtime 仍可接收任务；dead resident 应继续按 stored resume material 派生
`recoverable_unloaded` / `unavailable` / `unknown`，并让这个状态变化进入 availability version。无需增加心跳或后台监控平台。

### P1：dump cursor 未绑定 team instance，可跨实例静默续页

`DumpCursor` 目前只编码 `revision:availability_epoch:observe_generation:offset`
（`team-state/src/observe.rs:205-266`）；`TeamStore::dump` 也只比较这三个计数
（`team-state/src/store/observe.rs:37-46`），不检查 `self.instance`。

两个新 TeamStore 很容易同时处于 revision 0、epoch 0 和相同 observe generation。实例 A 的 cursor 交给实例 B 时会被接受，并从
B 的同一 offset 静默续页。这违反 TeamState 既有“旧实例引用不得解析当前实例”的身份合同，也不符合 cursor 冻结同一团队快照
的声明。

处理要求：cursor 编码和校验需携带完整 TeamInstanceId（或等强实例 tag），跨实例 cursor fail-closed；补两个 TeamStore 交叉
cursor 的小回归即可，不需要签名、MAC 或可信 cursor 设施。

## 替用户作出的决策

1. 接受并保留 `c203e34` 的 explicit-resume recoverability、同步 gate 方向、VersionFact、dump offset 拒绝和 ThreadId 关系字段；
   下一轮只补缺失接缝，不回滚主体实现。
2. “当前可用”必须同时满足 loaded 且 `CodexThread::is_running()`；dead resident 不得仅凭 map membership 报 available。之后按既有
   stored resume material 探针分类，不新增心跳或自动清理系统。
3. 不要求跨 await 持 `std::sync::Mutex`。store delete 可采用执行者认为最小的两阶段版本/临界接缝，但删除可见、epoch 推进和
   retire final check 必须线性化，正式 app-server delete 也必须走同一协议。
4. DumpCursor 必须绑定完整 team instance；这只延续既有 TeamInstanceId 规则，不建设复杂可信 cursor。冲突的 inspect 参数若顺手
   fail-closed 可以接受，但不是本轮阻断条件。
5. 继续在 043 工作树窄修；不进入 M-5，不合并、不推送。修复后只需领域包、精确 availability / delete-retire 竞态、M-4 产品纵切
   和必要的 M-1—M-3 定向回归，不扩大为全 workspace。

执行者没有留下必须由用户另选的产品决策；上述取舍由本轮审查直接作出。

## 独立验证与现场

| 项目 | 结果 | 说明 |
|---|---|---|
| `git diff --check 035977c..c203e34` | 通过 | 第二轮整改差异无 whitespace error |
| `just test -p codex-team-state --lib` | 124/124 通过 | 共享构建锁与资源看门狗；run `5b90d58e-5057-456d-9d0c-987fb83cb46f` |
| `just test -p codex-core --lib -- agent::control::availability resume_agent_restores_closed_agent_and_accepts_send_input` | 4/4 通过 | 2205 skipped；run `45d7a8fd-a260-4228-a035-3b1ffbd2dc63` |
| M-1—M-4 产品套件 | 本轮未重跑 | 采用执行日志的 17/17 结果；避免重复较重门禁 |

未运行全 workspace、Docker、真实 API、本地模型、付费资源或测评。复验前 043 工作树干净，
`main = origin/main = af1063d` 且主工作区干净。本报告是本轮唯一产品仓库受跟踪改动；未修改实现、Plan/WBS，未合并、未推送、
未归档分支。当前 WBS/Plan 中“第二轮整改待再审查”不构成验收通过；M-5 仍未开始。
