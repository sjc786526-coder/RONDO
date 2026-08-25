# Plan 080 / M4-C2 独立验收审查

时间：2026-08-25 ｜ 被审实现：`aadddf48751a056df94249107c853d727f4d17a5`

## 结论

`M4_C2_CONTROL_PASS` 暂不成立。当前结论为：**验收不通过 + 任务目标失败（针对当前提交，可在原授权范围内修复）**。

执行者给出的 `45/45` 合并树基线、最终 `17/17`、邻接 `47/47`、fresh 链、schema/snapshot、格式与资源证据均能与
watchdog/JUnit/仓库状态对应；本审查没有否定这些已运行结果，也没有重跑重型测试。阻断来自测试尚未覆盖的 authority 与 lifecycle
竞态，以及几处正式控制链功能缺口。

## Findings

### High 1：online proof 没有绑定 Root owner incarnation，可跨 replacement owner 重放

- `app-server-protocol/src/protocol/v2/durable_session_control.rs:25-34` 的 precondition 只有 storage/residency 与 Team
  instance/revision/commit generation/fingerprint，没有一次 loaded Root owner 的不可复用身份或 generation。
- `app-server/src/request_processors/durable_session_query_projection.rs:44-54` 因而会在 owner A 被卸载、同一 Durable Session
  未发生 Team mutation 地恢复为 owner B 后生成相同 proof；`durable_session_control.rs:91-108` 的精确值比较无法区分 A/B。
- 随后的 Close 会关闭 B，SetRootState 也会路由 B。即“读 A → A 退出 → B replacement → 提交 A 的旧 proof”仍可能成功，违反
  replacement owner 与 exact owner/generation fail-closed 合同。

修复必须让 online 控制在最终 owner authority 上识别并复验同一次 owner incarnation；不要以 Team commit generation 冒充 owner
generation。内部字段和 seam 由执行者按现有架构选择，cold proof 不必无意义耦合 runtime token。

### High 2：Close/active Archive/Delete 未在真正生命周期线性化点复验 query proof

- `app-server/src/request_processors/durable_session_control.rs:65-108` 只在请求入口重投影；Close、Archive、Delete 随后分别在
  `:138-190`、`:221-242` 进入 owner shutdown/ThreadStore。
- M4-S2 的 Root/Team close barrier 要到 `core/src/session/handlers.rs:622` 之后才建立；入口持有的
  `thread_list_state_permit` 不串行普通 Team 写，普通写由 `team-state/src/handle.rs:547` 附近的 mutation gate 与 Root writer
  authority 控制。
- 因此 generation N 的请求通过入口后，活动 turn 可先提交 N+1；close barrier 随后关闭最新状态，Archive/Delete 仍返回成功，Delete
  甚至会删除操作者确认旧视图后新增的有效事实。

修复必须在停止新 admission 后、破坏性 lifecycle 已获得 authority 但尚未不可逆执行的边界复验相关 owner/Team proof；并发提交先赢时
abort/reject 为 stale/conflict，保留 owner 与新事实。具体复用或窄扩展 M4-S2 seam 由执行者决定，不建设第二套 lifecycle manager。

### Medium 1：正式 control 未显式拒绝 parented child

正式 read 在 `app-server/src/request_processors/durable_session_query.rs:277-289` 拒绝 `parent_thread_id.is_some()`，但 control 在
`durable_session_control.rs:65-90` 读取 meta 后直接投影。一个 parented、但具有自洽 self-root durable marker/snapshot 的记录可被当成
Root，对 child subtree 执行 cold Archive/Delete。proof 不是秘密凭据，不能依赖正常客户端不会构造该输入。control 应与 query 的
canonical Root 边界一致，并验证 mutation helper 未被调用。

### Medium 2：Delete 的 M4-S2 retry anchor 无法由正式控制链消费

`thread-store/src/local/delete_thread.rs:95-109` 先删除 Team snapshot，再逐个删除 rollout，并刻意把 canonical Root marker 留到最后作为
retry anchor。后续删除失败时 control 返回 Unknown；但 query 因 snapshot 缺失无法在
`durable_session_query_projection.rs:44-56` 生成完整 proof，下一次正式 Delete 又在 `durable_session_control.rs:84-90` 被拒绝。
底层已有可重试语义，正式 query/control/TUI 却无法到达，结果是一次部分失败后永久失去正式 Delete 能力。

应允许用户在权威重同步后显式重试并消费现有 Root marker anchor，或调整失败边界以保留可生成正式 proof 的权威材料；不要新增 registry、
数据库或自动重试。

### Medium 3：TUI 在展示危险确认前没有由权威 availability/target 驱动

`tui/src/app/durable_session_control.rs:104-133` 只确认存在 fresh accepted-read ticket，就显示 popup；Session attachment、operation
availability、control proof 直到用户点击后才由 `app-server-client/src/durable_session_control.rs:170-225` 校验。因而 list view、无 proof
或明确 unavailable 的操作仍会显示确认，随后才报错。popup `:22-49` 也不显示 Session/Root 目标或关键 mutation 参数，无法让操作者清楚
确认危险/终态操作。

应在展示前从同一 fresh 权威 projection 得到可操作性与明确目标；确认时仍保留 read ticket 和 server 最终复验。如何组织 preview/capture
API 与 UI 文案由执行者决定。

### Medium 4：只关闭 control 时，迟到确认会错误 detach 仍有效的 query attachment

`tui/src/app/durable_session_control.rs:141-146` 在 combined query+control gate 为 false 时无条件
`durable_session_detach()`；`:215-227` 的 completion fallback 也有同类问题。若仅关闭 control、query 仍开启，query-only attachment 应保留，
但 popup 的迟到 Confirm 会将其解除。应仅在 query gate 也关闭时 detach；control 关闭只退休/拒绝控制尝试并保持 query 能力。

### Medium 5：关键关闭态与 domain precondition 验收尚未落地

- 新增 `TeamMutationPrecondition` / `update_lifecycle_at_snapshot` / `SnapshotConflict` 没有直接测试引用；现有 stale RPC 测试在 server
  重投影阶段已拒绝，未覆盖 server preflight 后、domain mutation 前的竞态。
- public RPC 的默认关闭测试只发送 `session/read` / `session/list`；没有向 query-only、control-off 或 non-Durable server 发送
  `session/control` 并证明 typed 拒绝且无副作用。feature 单测也不在报告的最终 watchdog JUnit 中。

这些是本任务明确验收面；不需要增加重型体系，只需在现有相应层补窄回归。

### Low：ExecPlan 当前状态未随提交收口

`plan/080-m4-c2-formal-session-control-tui-execplan.md:294-301` 仍写“正在形成提交”和“剩余提交/发送队列”，但实现提交及验收消息均已完成。
修复批次完成时应把当前状态、剩余步骤和验收状态更新为真实事实。

## 最小修复与复验要求

1. 覆盖 owner A → unload/close → owner B replacement → A 的旧 online proof 被拒绝，且 B 不受影响。
2. 受控注入 app-server preflight 后的 Team commit，证明 Close 与至少一个破坏性 lifecycle 操作不会吞掉新提交，失败后 owner/事实可重试。
3. 直接覆盖 Team snapshot precondition 的成功与 conflict；覆盖 parented self-consistent record 不进入 mutation helper。
4. 注入 Team snapshot 已删、Root marker 尚存的 Delete 中途失败；权威重同步后由用户显式正式 Delete 完成，不自动重放。
5. 覆盖 unavailable/list projection 不展示控制确认、确认展示明确 Session/Root/关键目标，以及 popup 后仅关闭 control 仍保留 query attachment。
6. 覆盖 public `session/control` 在默认关闭、query-only/control-off 与 non-Durable 路径的无副作用拒绝。
7. 只运行受影响 crate/filter、必要 schema/snapshot 和相邻聚焦回归；不要求 full workspace、Docker、真实 API/模型、CI/PR 或新审计设施。
   所有重型 Cargo 仍复用 069 target 并走 canonical lock/watchdog 与本任务临时容量门。

## 代用户作出的决定

- 当前 `aadddf4` 不接受合并；上述 High/Medium 在同一 Plan 080 授权和工作树内修复，不需要追加授权。
- owner incarnation、lifecycle 线性化点复验和 Delete 显式恢复能力是原则边界；具体数据结构、模块拆分与测试布局不冻结，执行者可采用证据更充分的
  更优路线。
- 已通过的 45/17/47 项与 fresh 证据继续有效到其覆盖范围，不为审查重复跑全量；修复后只补直接回归并窄复验受影响邻接面。
- 不引入跨进程 relay/queue、registry/database、自动 mutation retry、额外审计/可信体系，也不触碰 079、合并或推送。

## 仓库状态

审查开始时 080 分支位于 `aadddf4` 且 clean；主工作区、079、远端均未修改。本报告是审查者在 080 工作树中的唯一变更，提交后由执行者继续修复。
