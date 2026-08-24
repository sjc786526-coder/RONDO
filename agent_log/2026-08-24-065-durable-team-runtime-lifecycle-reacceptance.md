# 065 Durable Team Runtime 生命周期最终复验

日期：2026-08-24 ｜ 验收对象：`worktree-065-durable-workspace-runtime-planning`

## 结论

**前两项 Root writer finding 已闭合，但本版 WBS 暂不通过最终验收。** 本轮新增生命周期中，resume、`/new`、slash
`/clear`、detach、关闭、archive/unarchive/delete 的方向与冻结 Codex `v0.147.0` 基本一致；仍有 1 项高等级全局冲突：
`latest fork` 同时要求创建新 `TeamInstance` 并复制原 Team revision，违反现行 Team 引用的实例归属合同。

该问题不需要新增平台、审计、事务或重型测试。最小处理是让 V1 fork 继续复用 Codex 的 conversation/thread-history fork，
但 Durable Team State 从新的空 `TeamInstance` 开始；旧 Team 引用按既有 instance mismatch 规则 fail-closed。若未来确有复制团队
世界状态的产品价值，再把 Team clone/branch 作为独立能力评估，而不塞入 M4-S2 生命周期收口。

## 已通过的复验项

- F065-RW-01 已闭合：关闭完成同时要求耐久边界和 Root writer guard 实际释放；存活进程内 shutdown/session-task 失败保持
  `closing/failed` 且可重试，完整进程终止才依赖 OS 释放锁（`doc/WBS/durable-team-runtime.md:124-140,191-202`）。
- F065-RW-02 已闭合：非 owner 读取必须得到一个完整已提交状态或明确 `stale/unknown/unavailable`，并有窄的 deterministic/fake
  回归；没有引入 Team read lock 或第二只读 store（`:118-127,181-187,351-355,367-371`）。
- 冻结源码确认 `/new` 与 slash `/clear` 都启动新 thread，纯 UI 清屏被明确区分；archive 会处理 Root/spawned subtree，
  unarchive 只恢复指定 Root，delete 按 subtree 删除并可能暴露部分失败。WBS 没有为这些原生限制新增补偿、批量复活或事务平台。
- S/C 必成主线、W 可选增强、M4-Z(core) 不依赖 W、上游窄回移条件边及资源关系未因本轮修订回归。

## Finding

### F065-LC-01（高）：新 TeamInstance 不能原样复制旧 Team revision

现行权威合同规定 Event、Version、Fact 引用都只属于一个 TeamInstance，旧引用不得解析到新对象
（`doc/WBS/multi-agent-trusted-evidence.md:264-270`）。源码也把 TeamInstance tag 嵌入 `EventId`、`VersionId`、`RouteId`、
`FactId`，store 在解析时严格校验当前实例（`multidev/codex-rs/team-state/src/ids.rs:1-18,130-325`；
`multidev/codex-rs/team-state/src/store.rs:243-272`）。

当前四期 WBS 却要求 default latest fork 创建新 TeamInstance、复制完整已持久化 Team revision，并让历史贡献者继续解释复制的
Event/Version/Fact，同时不复制旧 Agent graph 或把旧 child 注册为新团队成员
（`doc/WBS/durable-team-runtime.md:80-94,367-375`）。这三项不能由“复制快照”同时满足：

- 原样复制 ID 后，其 instance tag 仍属于来源 Team，新 store 会按既有合同拒绝；
- 重铸 ID 则必须重写 Event/Version/Route/Fact 的全部内部引用，并决定旧到新 provenance；
- 当前 participant registry 没有“仅保留历史署名但不授予成员能力”的独立类型；原样复制 participant 会把旧成员带入新 Team，
  删除 participant 又会丢失标签与权限语义；
- Fact locator 指向旧 producer ThreadId 的 retained observation，而新 Team 明确不复制旧 child runtime/Agent graph；当前读取只从
  本 Team 已加载 producer session 取 observation，因此复制后的 Fact 通常只能变为 unavailable
  （`multidev/codex-rs/core/src/team/evidence.rs:457-479`）。

此外，完整 TeamStore revision 还包含 committed retry namespace、wake ledger、route/delivery、fact publication cursor 与 change log；
哪些复制、重置或改写都尚未定义。把这些选择下放为“持久格式实现细节”会让不同 ExecPlan 得出不同产品语义。

## 最小修订要求

1. 将 `doc/WBS/durable-team-runtime.md:81-94` 收窄为：任何 Codex fork 都创建新 Root/Session 和新的空 TeamInstance；原生
   conversation/thread history 继续按 Codex 的 latest 或指定位置规则 fork，但 V1 不继承 Durable Team State。
2. 明确不复制 Event/Version/Fact、participants、routes/wake/retry 状态，以及可选 binding/handoff；来源 Team 保持不变，来源关系
   只复用原生 thread fork lineage，不新增 provenance registry。
3. fork history 中出现的旧 Team 引用继续按 instance mismatch 明确拒绝；不得把空 Team 描述成“继承成功”。同步 S2 目标/出口与
   宏观验收，只增加一条“新空 Team + 旧引用 fail-closed”的轻量 deterministic 回归。
4. 若坚持复制 Team revision，须另行把 ID remint/rewrite、历史 contributor、Fact availability 和 route/wake/retry 取舍定义为
   Team clone/branch 产品能力并通过价值门；不应作为 M4-S2 的隐含工作。

## 代用户作出的决策

- **接受 Root writer 两项整改及其窄测试口径，不再重开。**
- **当前版本不批准最终 PASS。** 只需闭合 F065-LC-01 后再做一次文档级窄复验。
- **选择最小 V1 语义：fork 新建空 TeamInstance，不继承 Durable Team State。** 不为实现“完整 revision 复制”预建 ID 映射、
  contributor 档案、跨 lineage Fact 恢复或 Team clone/branch 平台。
- **不追加重型验证。** 本轮源码与文档静态证据足以确认规划冲突；未运行 Cargo、Docker、真实模型/API、训练或测评。
- **不代行提交或合并。** 本报告不授权 commit、merge、push 或启动 M4-A。
