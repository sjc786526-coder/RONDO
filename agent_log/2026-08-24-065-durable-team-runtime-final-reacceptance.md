# 065 Durable Team Runtime WBS 最终复验

日期：2026-08-24 ｜ 验收对象：`worktree-065-durable-workspace-runtime-planning`

## 结论

**验收通过。** F065-LC-01 已按最小 V1 语义闭合，未发现剩余功能性、正确性或全局依赖阻断。Codex fork 只复用原生
conversation/thread-history 分叉，新 Root Thread/Session 使用新的空 TeamInstance；Durable Team State 不继承、不克隆，旧 Team
引用按既有 instance mismatch/`InstanceReset` 规则 fail-closed。

该修订没有引入 Team clone/branch、ID 映射、历史成员档案、跨 lineage Fact 恢复或 provenance registry，也没有改变 S/C 必成主线、
W 可选增强和 M4-Z(core) 不被 W 阻塞的总体结构。

## F065-LC-01 复验

- 稳定生命周期合同已统一 latest/历史位置 fork：原生 history 按 Codex 分叉点进入新 thread，新 Team 从初始 revision 开始；来源
  Team 保持不变（`doc/WBS/durable-team-runtime.md:76-97`）。
- M4-A 明确 fork 使用新 Root Thread/Session 与空 TeamInstance，不复制 Team revision，也不建立来源 TeamInstance/旧引用映射层
  （`:119-132`）。
- M4-S2 的目标、边界和出口均采用相同语义，不再存在无编号的 clone/remint 后置工作（`:194-207`）。
- 验收只增加一条相称的 deterministic/fake 回归：验证原生 history 分叉、新 Team 为空、来源 Team 不变及旧引用 fail-closed；明确
  禁止为测试建设 ID remint 或 lineage 恢复设施（`:357-363`）。
- 核心 PASS 与非目标同步排除 Team State 继承、Team clone/branch、ID remint/mapping、历史 contributor、跨 lineage Fact 与
  route/wake/retry 克隆（`:368-387,399-415`）。
- 方向 3 总 WBS 只保留必要摘要，未复制完整生命周期实现细节
  （`doc/WBS/multi-agent-trusted-evidence.md:24-40`）。

冻结源码与该合同相符：Event/Version/Route/Fact ID 都携带 TeamInstance tag，跨实例解析由 store 拒绝；原生 fork 负责 thread history、
新 thread/session identity 和 `forked_from_id`，并不提供 Durable Team State 克隆。因而当前 WBS 没有把 Codex thread fork 的能力
错误扩大为 RONDO Team clone。

## 全局回归检查

- 前两项 Root writer 整改保持闭合：失败 shutdown/session-task 不伪报关闭完成；非 owner 读取仍要求完整已提交状态或明确
  `stale/unknown/unavailable`。fork 修订没有改动这些合同或增加 Team lock/read lock。
- resume/member reload 仍保留原 TeamInstance；`/new`、slash `/clear`、detach、archive/unarchive/delete 与原生生命周期映射未被
  fork 修订改变。
- 新 Team 不复制 writer binding/handoff；W0/W1 价值门、replacement binding、S/C-W 条件依赖及 M4-Z(core) 出口保持一致。
- 旧审查日志按形成时点保留旧 finding，不作为当前 WBS 的权威规划；当前三份 WBS 中未发现旧的 revision-copy、historical-fork
  继承或 Team clone 表述。

## 检查边界

- `git diff --check` 通过，新增 WBS 未发现尾随空白；主工作区保持 clean。
- 本次只进行 WBS、冻结源码与既有回归定义的静态复核，并新增本报告；未修改代码，未运行 Cargo、Docker、真实模型/API、训练或
  测评，未提交、合并或推送。

## 代用户作出的决策

- **批准本次第四期 WBS 最终验收 PASS。** F065-LC-01 关闭，前两项 Root writer finding 不再重开。
- **冻结 V1 fork 的最小产品边界：新空 TeamInstance，不继承 Durable Team State。** 未来若真实使用证明 Team clone/branch 有价值，
  必须独立立项，不能由 M4-S2 或单次 ExecPlan 静默扩张。
- **不追加设施或重型门禁。** 实施时只保留 WBS 已列的一条 fork deterministic/fake 回归，不建设 provenance、审计、事务或恢复平台。
- **不代行交付操作。** 本次验收不授权 commit、merge、push 或启动 M4-A。
