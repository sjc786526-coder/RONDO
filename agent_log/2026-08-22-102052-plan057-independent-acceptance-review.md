# Plan 057 / M3-B2b 独立验收审查

审查目标：`d70c597c8a7f0e64448d3311efd07f6bbcdf478a`

对比基线：`9c002bd898e0f62fcdae521c5ba9b8cddd760a08`

结论：**验收不通过；任务目标尚未完成。** 默认关闭、canonical/raw 分离、typed failure fallback、最终 Team State 单写、
packet allowlist 和已有定向证据整体方向正确，但实现仍有 2 个高优先级 cycle correctness finding 和 2 个中优先级有界读取/trace
correctness finding。修复前不应合并或推送。

## Findings

### P1：无关 replay 或 preparation refusal 会破坏正在等待改稿的 cycle

`core/src/tools/handlers/team_tools/publication_review.rs:303-329` 在检查请求是否属于当前 cycle 之前先做 Team State preparation，
并在任意 preparation error 或 committed replay 上无条件 `clear_active()`。这与 `:207-231` 对 ready、无 continuation 调用“拒绝但保留
active cycle”的行为不一致，也让不同 publication 互相干扰。

可复现场景：B 已提交；A 第一次审核得到 `REWRITE` 和 cycle `c`；此时精确 replay B。B 正确地零审核返回 committed replay，
但同时清空 A 的 active cycle。随后 A 的改稿携带 `c` 会被当成“不存在 active cycle”拒绝。类似地，一个无关的 native preparation
error 也能清空 A，并允许后续无 continuation 请求从 attempt 1 重新开始。

修复必须保证无关 committed replay/native refusal 不改变另一 active cycle；当前 cycle 的终止规则仍应清楚保持 success、final
failure/fallback、store refusal、cancel 和 turn/session 生命周期语义。具体采用先校验归属、条件清理或其他等强方案由执行者决定。
至少补回归覆盖“active REWRITE → 无关 committed replay/refusal → 原 continuation 仍可完成”，并确认不能借无效请求重置 rewrite 预算。

### P1：固定 continuation 允许并发旧 token 跳过第二次反馈

`publication_review.rs:125-133,199-247,421-431` 的 active cycle 在两个阻断式 `REWRITE` 间保持同一个 id；续接只检查该固定 id、
actor、instance 和 target。state mutex 虽会串行服务调用，却不会证明候选是在最近一次反馈之后形成的。

可复现场景：attempt 1 返回 v1 和 token `c` 后，同一批发出两个不同候选且都携带 `c`。第一个被串行为 attempt 2 并返回 v2；第二个随后
仍携旧 `c` 被接受为最终 non-blocking attempt 3，虽然 Producer 从未基于 v2 形成第二次改稿，仍可能直接提交。这违反冻结的“两次按反馈
自主改稿”顺序和并发不串线边界。

修复必须让每个阻断式反馈只授权下一阶段的一次新候选，同时保留同 attempt identity 的 exact replay 幂等。可轮换 continuation、加入
stage/generation 或采用其他等强设计；不要把实现限定为某一种 token 形状。补一个屏障驱动的并发回归，证明两个不同请求不能共用旧
continuation 串成 attempt 2/3，且正常三阶段和 exact replay 仍成立。

### P2：existing-Event continuity 在 Team State mutex 内实际全量克隆

`team-state/src/store/publish.rs:141-167` 请求 `history_limit=4`，但 `team-state/src/store.rs:489-503,559-605` 先通过
`event_view()` 克隆该 Event 的全部 Version 及全部可见 Route，之后才用有限 version window 覆盖 `view.versions`；routes 仍保持全量。
因此最终 packet 虽只有 4 条，准备阶段仍会在 Team State mutex 内对无界 Event history/route 做 O(N) 读取和分配。

这不造成 packet 字段泄漏，但不满足本任务“只读取有界 continuity”的产品边界，并可能让 Critic 前置准备长时间阻塞 Team State mutation。
应改为从 store 直接构造本任务所需的有界公共 projection，或让既有 history 路径在构造 view 前先切出 bounded window；职责契合时复用，
否则新建小而专用的 read view，不需要通用查询或审计设施。补聚焦测试确认 projection 只携合同所需的有限 Version 语义且不复制 routes。

### P2：body-redacted 工具经非阻断 PostToolUse feedback 后 trace 不结束

`core/src/tools/registry.rs:774-781` 会把非阻断 PostToolUse feedback 包装为 `PostToolUseFeedbackOutput`，但该 wrapper 在
`:227-248` 没有转发/实现 `post_tool_use_response()`。随后 `:784-790` 对 reviewed `team_publish` 以 body-redacted 模式记录完成；
`core/src/tools/tool_dispatch_trace.rs:109-111` 因拿不到 safe response 直接返回 `None`，从而不写 ToolCallEnded。replay reducer 会让该调用
永久保持 `Running`。

修复应在不泄漏 candidate/context 的前提下保证 trace 写入唯一终态和安全 typed result。补 reviewed/body-redacted runtime 加
non-blocking hook feedback 的聚焦回归：replay 状态结束、safe result 存在、sentinel 不出现。实现可选择转发安全响应、在包装前冻结
trace metadata 或其他更干净的等强方案。

## 决策与验证边界

- 我替用户决定：argument-comment Cargo wrapper 的 Rust 1.92/`sqlx 0.9.0` 工具链不兼容，以及 Bazel 替代入口 10 分钟未完成，
  继续按已记录的“未完成”处理，**不作为本轮功能修复的阻断门**。不要求升级工具链、修改依赖或再次长时间跑 Bazel；若修复未触及
  Bazel/Cargo 接线，也无需为此重跑该门禁。
- 修复后只需运行与上述 finding 直接相关的 cycle、Team State bounded projection、registry/trace 回归，以及必要的格式和受影响 crate
  定向 lint/test。是否复用现有 11 条 Publication Critic 聚焦组或采用更窄等强命令由执行者按改动选择；不要求全 workspace、Docker、
  真实 API、真实模型或新审计设施。
- 本轮核对了完整 `9c002bd..d70c597` diff、Plan/产品合同/执行日志、配置与 tool runtime 接线，并读取现有 JUnit：11 tests、0 failure、
  0 error。由于已有证据有效且 finding 可由代码路径直接证明，本轮没有重复运行 Cargo、Clippy、Bazel 或服务进程测试。
- 审查前 057 worktree 与主工作区均 clean；主工作区仍为 `main@9c002bd` 且与 `origin/main` 一致。未合并、推送、rebase、归档、删除
  worktree，也未修改 Plan 056 或其他产品线。

## 修复后复验重点

1. active cycle 不被无关 committed replay、native preparation refusal 或错误 continuation 清除，也不能用这些调用重置 rewrite 计数。
2. 每一阶段 continuation 只推进一次新候选；并发旧 continuation 不会把未见 v2 的候选当作最终非阻断稿。
3. existing Event packet projection 的内部读取和输出都保持有限，且不复制 route、Fact ID 或 observation body。
4. body-redacted `team_publish` 在正常、rewrite、hook feedback、failure、cancel 下的 dispatch trace 均有 body-free 唯一终态。
5. 修复不改变 off schema/output/store 路径，不破坏 raw request ledger、committed/exact replay、typed fallback、最终单次 commit、
   cancellation 和 evidence/wake/stale 语义。
