# Plan 043 / Multi M-4 最终独立验收报告

日期：2026-08-17 ｜ 审查对象：`worktree-043-multi-m4-coordination-closure@da4b7cd` ｜ 前次复验：`8a3d7eb` ｜ 基线：`main@af1063d`

## 结论

- **验收通过**：第五轮窄修通过现有 availability gate 一致采样并复验 `(generation, active)`，上一轮唯一剩余的原子边界双义
  epoch 已关闭；未发现新的任务内功能或正确性阻断。
- **任务目标完成**：四类 producer availability、Root 显式退休独立终态、确定性有界 dump、精简 changelog 与 publication stats
  已形成完整离线纵切，Plan 043 / Multi M-4 可以在当前工作树收口。
- 当前成果尚未合并或推送。M-5 仍未开始，也不由本次离线验收自动授权。

## 最终闭环

- `ThreadManagerState::availability_marker` 在既有 availability gate 内同时读取 generation 与 store-transition active。begin/end token、
  loaded-map insert/remove 及其 generation bump 均使用同一 gate，因此 snapshot 不能再落入“状态已变、epoch 未变”的夹缝。
- producer snapshot 在分类前后分别取得 coherent marker；active 分支在返回全员 `unknown` 前也再次复验。锁只覆盖同步读取，不跨
  `await`；marker 变化即重试。旧 dump cursor 因而不能用同一 epoch 拼接不同 availability 内容。
- Root retirement 取得 snapshot 后持同一 gate 复查 active 与 live epoch：transition 活跃时拒绝，控制面变化先发生时 stale CAS 拒绝，
  retirement 先线性化时后续变化不会倒灌覆盖。store 删除的 RAII token 在错误/取消路径由 Drop 收口。
- producer 分类按真实 explicit-resume 能力派生；shutdown/registry miss 不被误判为不可恢复，dead resident 也不冒充 available。
- Root retirement 保持独立终态，只撤销对应 Version 的 producer-open 活动理由；不伪装 producer closed，不改 Root attention、route、
  assignment、其他 Version，也不自动 cleanup/escalation。稳定重试和同状态 lifecycle 不制造 revision/log/wake generation。
- dump 绑定 team instance、revision、availability epoch 与 observe generation，拒绝裸 offset；Version→Fact 逐行受统一页限，Fact 只含
  locator 元数据；重复 label 由 ThreadId 消歧。log 只保存协调 delta，stats 从 canonical Versions 按 ThreadId 重算并分页。

## 替用户作出的决策

1. 接受 `da4b7cd` 的短持现有 gate 方案作为最终并发闭环；不再增加事务、签名、审计、可信链或外部可观测设施。
2. 接受当前定向验证强度：独立复验重跑 team-state、availability 与 explicit resume；M-4 产品纵切采用执行者本轮 1/1 结果，不重复跑
   M-1—M-3 或全 workspace。当前修改只触及 marker 读取接缝，扩大门禁收益不足。
3. 将 Plan 043 / Multi M-4 标记为已独立验收、任务目标完成；工作树保留供用户决定合入。合并与推送仍需用户批准，本报告不代替授权。
4. 合入前不开始 M-5。M-5 涉及 runtime bundle、真实协作工作流与付费 API，仍须按 WBS 另行规划和授权。

执行者没有留下必须由用户另选的产品决策；上述取舍由本轮审查直接作出。

## 独立验证与现场

| 项目 | 结果 | 说明 |
|---|---|---|
| `git diff --check 8a3d7eb..da4b7cd` | 通过 | 第五轮整改差异无 whitespace error |
| `just test -p codex-team-state --lib` | 125/125 通过 | 共享构建锁与资源看门狗；run `8f810c0a-6388-4ee2-a0cf-7e1d10823326` |
| `just test -p codex-core --lib agent::control::availability` | 5/5 通过 | 2206 skipped；run `679948ff-d6e2-4266-8cf5-6a6d4e62d250` |
| `just test -p codex-core --lib resume_agent_restores_closed_agent_and_accepts_send_input` | 1/1 通过 | 2210 skipped；run `3babc001-69ef-426e-935d-ff49cd5406fd` |
| M-4 产品纵切 | 本轮未重跑 | 采用执行日志的 1/1；避免重复较重门禁 |

未运行 M-1—M-3、全 workspace、Docker、真实 API、本地模型、付费资源或测评。审查开始时 043 工作树干净，
`main = origin/main = af1063d` 且主工作区干净。本轮只更新验收报告和受影响的 Plan/WBS 状态；未修改实现，未合并、未推送、
未归档分支。
