# Plan 069 第三轮预验收复验

## 结论

- 审查对象：`f3c6a7ed76ffc56993b656dde498e7611331e0f8`（`fix(multidev): close durable team activation gaps`）。
- 结论：`REJECTED`。上一报告的三项中等级 finding 已按正确方向关闭，SessionMeta/ThreadStore 兼容改动和现有聚焦证据也成立；但仍发现 2 项中等级 correctness finding，当前不能接受 `PREACCEPTANCE_COMPLETE`。
- 当前准确状态：`IMPLEMENTATION_INCOMPLETE / PREACCEPTANCE_REJECTED / FINAL_PASS_BLOCKED_BY_CORRECTNESS_AND_#37198`。
- 本轮未重跑 Cargo、clippy 或完整 workspace。项目存储已接近 watchdog 主动停止线，且现有 11 组 watchdog/JUnit 记录均真实为零失败；源码级确定性路径已经足以判定下列问题。`git diff --check 811a0d8..f3c6a7e` 通过，提交边界未触碰四份共享 WBS、Plan 070 控制面或 `#37198`。

## 阻断 finding

### M-1：activation 完成后不再验证 canonical SessionMeta，marker 丢失时仍可返回 durable mutation success

`root_team_write_authority` 只在构造时验证调用方传入的 intent（`core/src/team/durable.rs:34-54`）。之后
`LocalTeamWritePermit::read_snapshot` 与 `compare_and_swap` 只访问 `{root}.team-state`（`:123-187`），不再验证 canonical Root rollout 中的
SessionMeta marker。`DurableRootActivation.complete` 一旦置位，后续入口也会直接跳过 activation 检查（`session/session.rs:537-553`）。

确定性场景是：fresh/resumed activation 成功 → live owner 存续期间 canonical rollout/SessionMeta 因介质故障被删除、截断或 marker 被损坏 →
后续 Team mutation 仍 CAS snapshot 并返回成功 → 进程退出后没有可定位、可交叉证明的 Session/root lineage，刚报告成功的 mutation 无法恢复。
LocalThreadStore 的 live-writer delete/archive guard 能排除正常产品删除竞态，但不能覆盖计划明确纳入的 marker/lineage 缺失或损坏故障。

修复不需要 lease、registry、审计或可信设施。应在 owner 的 committed read 与 mutation success 边界复用 canonical Session/root intent 校验；
无法证明时保留现有 owner并返回明确 unavailable/unknown，不推进 snapshot generation。补一条 activation 后删除或损坏 marker、再尝试 Team read/
mutation 的聚焦回归即可。具体同步/API 路线由执行者选择。

### M-2：projection 与 wait 把持续的 durable failure 静默降级成“无 Team/正常等待”

`capture_team_projection` 在 fresh activation retry 或 `TeamAccess::resolve/snapshot_for` 失败时都返回 `TeamProjectionOutcome::Nothing`
（`core/src/team/projection.rs:76-97`）。但 `Nothing` 的既有合同是 feature off、非 participant 或 active view 为空（`:47-59`）；turn 路径把它转成
`None` 并继续向模型发送 sampling request（`session/turn.rs:405-430`）。因此只要 persist/read-back 或后续 durable reconcile 在下一 turn 仍失败，
模型就会在没有 canonical Team view 的情况下继续推理并可能执行普通工具或外部动作，无法区分 Team idle/off 与 Team unavailable。

`wait` 有同类问题：`ensure_durable_root_activation().await.is_ok()` 和 `TeamAccess::resolve(...).ok()` 丢弃错误，设置 `team_waiter=None`
（`tools/handlers/multi_agents_v2/wait.rs:76-86`），随后仍返回正常 Completed/timeout 结果（`:107-137,159-182`），可能漏掉无法读取的 Team activity。

这不是要求阻塞所有非 Team 业务或建设新状态机；只需保持已有语义区分：合法 off/non-participant/idle 仍可无 projection/Team waiter，而 durable
activation/reconcile/read 的失败必须让本次 sampling 或 wait 诚实失败。可把现有一次性故障 wrapper 延长为持续两次失败，分别证明不会发送模型请求、
不会把 wait 记录为正常成功。

## 已确认关闭与成立的部分

- durable intent 已进入 canonical Root `SessionMeta`，`.team-lineage` 运行时旁路已删除；marker 与 snapshot 位于独立持久边界。
- Team backend 整体移走后，durable-off resume 仍由 SessionMeta marker 拒绝，不创建空 Team；marker-only、snapshot-only、identity/version/corruption 均 fail-closed。
- `SessionSource::Unknown` 在打开 thread persistence 前拒绝，现有产品回归确认没有 Team artifact 或 rollout JSONL。
- persist-after-success read-back 成功可在同 owner 内继续 generation 1；首次 read-back unavailable 会返回 degraded Session 并保留 live Root owner，由下一入口重试。
- Team tools 会传播 activation 错误；close 在 activation 未完成时发送错误并在 shutdown/close permit 前返回，未提前释放 owner。
- `DurableTeamSessionMeta` 与 `SessionMeta.durable_team` 具备兼容默认值；所有 workspace 构造点已传递或显式置 `None`。测试支持新增的内部 `codex-thread-store` 依赖与单项 Cargo.lock diff 相称。
- watchdog/JUnit 原始记录支持 protocol 1/1、thread-store 1/1、core durability 2/2、产品最终 5/5、rollout 1/1、state 3/3、app-server 1/1 的执行摘要。这些测试证明已覆盖路径，但没有覆盖 M-1 或 M-2 的持续故障。

## 代用户作出的决策与复验边界

- 当前不接受 069 预验收，不进入阶段 E，不合并、不推送，也不处理 `#37198`。
- 两项修复继续留在 Plan 069 原边界。允许为 canonical marker 复核和 projection/wait 错误传播做必要的 core/ThreadStore/rollout 窄接缝；不得扩建 registry、审计/可信平台、S2 生命周期或 Plan 070 控制面。
- 普通编译、测试和 fixture 问题由执行者自主修复、重跑。修复后只需运行新增的 marker-loss mutation、持续故障 projection/wait 及直接受影响 core/ThreadStore/rollout 聚焦门禁；无需重跑完整 workspace，也不要求 clippy，除非源码改动实际触发新的编译/lint 问题。
- 继续只形成 069 工作树内的干净本地提交；未经用户批准不 merge/rebase/push/删除 worktree。

## 最终状态

- 验收：**不通过**。
- 任务目标：**失败（当前提交仍未完整实现预期；允许在原授权与 Plan 069 边界内继续窄修后复验）**。
