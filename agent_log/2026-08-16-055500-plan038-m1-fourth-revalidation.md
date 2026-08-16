# Plan 038 / Multi M-1 第四轮复验

## 结论

- 复验对象：`worktree-039-multi-m1-team-world-state` 提交
  `c6bb081c51ac4bbe9841e861db6e271581385057`，上次复验报告提交为 `9a96720`。
- **验收状态：不通过。**
- **任务目标：失败。** 可通过一次压缩恢复空间的产品链已经正确接通，但当前提交仍允许活动团队状态在普通
  sampling 中缺席，并且压缩恢复会丢失稳定团队协议；整次请求预算也仍漏算随后附加的模型可见 metadata。
- 三项均位于现有 turn/projection 接缝内，只需窄修和定向回归，不需要新增审计、可信体系或调度设施。

## 已确认正确的部分

- `NoRoom` 已从 provider 响应后的 flag 改成 provider 调用前的显式控制流：先尝试 compaction，再重取 history、
  重渲染投影，最后才进入普通 sampling。新增第 8 条集成测试真实走过 session、team tool、compaction 与 provider
  seam，能证明“压缩后可放下”的顺序，不是假阳性。
- 投影预算已补入 base instructions、input、tools、output schema 和投影 item framing；上一轮指出的静态漏项已修复。
- 投影在 `run_sampling_request` 外捕获并传入，provider retry 仍复用同一份投影，未见快照一致性回退。
- history 下钻用例继续精确读取真实 tool output，并以 `next_before -> before` 翻页；此前的权限、终态、幂等和身份
  整改未被本提交回退。

## 仍阻断验收的问题

### 1. 压缩后仍 `NeedsRoom` 时继续无投影 sampling

- `core/src/session/turn.rs:368-383` 在第二次渲染仍为 `NeedsRoom` 时只写一条 `warn!`，随后把它映射为 `None` 并
  继续调用 provider。
- 这不是可接受的降级：模型会在团队确有活动事项时基于缺失状态做决定，直接违反 WBS 第 14 条“活动视图必须在
  模型决定前进入本次采样上下文”。本地 warning 既不能修复模型视图，也不是对模型或调用者的显式失败。
- 新顺序用例只覆盖 14k 窗口下“压缩一次后可放下”的 happy path；执行日志也明确说明 11k/9k 会走到该错误分支。
- 最小修复边界：只允许一次 compaction，若重渲染仍无空间，则在普通 provider sampling 前明确中止/报错；也可选择
  一个真正能放入且仍可行动的最小投影。不得循环压缩，也不得静默盲采样。

### 2. 当前 turn 内压缩使用了错误的 initial-context 语义

- `core/src/session/turn.rs:352-360` 在本 turn 已记录输入与 world state 后调用 compaction，却传入
  `InitialContextInjection::DoNotInject` 和 `CompactionPhase::PreTurn`。
- `core/src/compact.rs:57-65` 明确规定 `DoNotInject` 适用于真正的 pre-turn/manual compaction：replacement history
  清空 initial context，依靠“下一次 regular turn”重新注入。当前路径压缩后立即在**同一 turn**重取 history 并 sampling，
  不会经过下一 turn 的注入步骤。
- 普通 compaction replacement 在 `compact.rs:356-371` 因此没有 initial context，也把 reference baseline 设为 `None`。
  动态 Active World Index 虽可能回来，但 `<team_protocol>` 等稳定团队规则和其他 initial context 已从模型请求消失。
- 新顺序用例只断言压缩先于动态投影，没有断言压缩后的请求仍含稳定团队协议，所以未捕获该问题。
- 最小修复边界：把这次压缩按当前 turn 的 mid-turn initial-context reinjection 处理，或采用等价方式保证压缩后的首次
  sampling 同时含稳定团队协议与动态投影；具体接缝由执行者选择。

### 3. 预算计算后又追加了 executed-tool metadata

- `core/src/team/projection.rs:123-148` 对传入 input 计算余量；但 `core/src/session/turn.rs:1391-1397` 在稍后的
  retry loop 内才调用 `attach_pending_to_prompt` 并 bound metadata，然后再追加投影、构造最终 Prompt。
- 该 metadata 是模型可见输入，协议侧允许保留到约 32 KiB；它可能明显超过 2k headroom。因此当前预算仍不是最终
  实际请求的余量，存在基础请求可放下、追加 metadata 与投影后越窗的路径。
- 最小修复边界：在捕获/预算投影前完成并冻结首次 attempt 的最终 prompt input，或以等价方式把待附加 metadata 计入
  余量；同时保留 retry 的同一投影快照语义。无需引入精确 tokenizer 或预算审计设施。

## 本次验证

- `just test -p codex-team-state -p codex-features`：**80/80 通过**。
- `just test -p codex-core -E 'test(/team_world_state/) + test(only_verifiable_sessions_get_a_team_identity)'`：
  **8/8 通过**，3329 skipped。
- 两组仅各运行一次，均经共享构建锁/cgroup 看门狗；未观察到 flaky。
- `git diff --check 9a96720..c6bb081`：通过。
- 未重复执行 executor 已跑的广口径 core/rmcp、fmt，也未跑全 workspace、Bazel、Docker、真实 API 或本地模型。
  executor 报告的 85 项宽门禁失败集合仍按既定口径只作为“未新增失败”的证据，不独立确认其环境根因。

## 替用户作出的决策

1. **拒绝“压缩后仍无空间就 warning 并无投影采样”的降级。** 一次 compaction 后仍不能满足合同，应 fail-closed；
   不要求反复压缩，也不要求建设新恢复系统。
2. **`DoNotInject` 不是可接受取舍。** 这次压缩发生在当前 turn 内，压缩后的普通 sampling 必须恢复稳定团队协议；
   建议在现有 initial-context injection 接缝内窄修。
3. **预算以最终模型可见 Prompt 为边界。** pending executed-tool metadata 必须在预算前冻结或被计入；接受仓库既有近似
   token 估算器、24-token framing、4k/2k/20% 常量，不要求复制 provider tokenizer 或增加预算审计体系。
4. **只要求三条聚焦回归证据：** 压缩后请求保留稳定协议；第二次 `NeedsRoom` 不发普通 provider sampling；带 pending
   executed-tool metadata 时预算仍不越界。可合并成现有产品测试或局部单测，不要求扩建套件。
5. 上轮未复现 flaky 继续记为非阻断；Bazel 继续未验证非阻断；不补跑重型全量测试。`team_state_enabled` 默认关闭、
   Root/member 最小权限和独立 `wait_agent_enabled` 等既有决定保持不变。

## 交付状态

- 本次仅新增本复验报告；未修改实现、ExecPlan、WBS、main 或 L6 工作树。
- `c6bb081` 未合并、未推送。建议仍在原 M-1 工作树完成上述三个接缝窄修后提交复验。
