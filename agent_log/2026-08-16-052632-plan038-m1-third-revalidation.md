# Plan 038 / Multi M-1 第三轮复验

## 结论

- 复验对象：`worktree-039-multi-m1-team-world-state` 提交 `19a0318436609f620edb26f5d6bc9663e1c544a0`，
  上次复验报告提交为 `95a57b5`。
- **验收状态：不通过。**
- **任务目标：失败（当前提交仍未完整满足 M-1 的每次采样可见与整次请求硬预算标准）。** 第二轮报告中的四项领域
  缺口和 history 产品测试已经正确修复；现在只剩一组投影调用层闭环问题，不需要新设施或重构领域模型。

## 已确认修复

- lifecycle 批次已拒绝同一 Version 同一轴的重复 target，同时保留 producer/root 两轴同批分别修改；批内绕过
  `resolved` 终态的路径已关闭。
- retry 判定直接保存并比较结构化 `PublishRequest`，不再存在 `None` / 空字符串或分隔符碰撞。
- lifecycle 校验顺序已经是权限 → expected 双状态 → 转换合法性；陈旧终态调用返回完整
  `LifecycleConflict { current }`。
- renderer 的 `Idle` / `Rendered` / `NoRoom` 三态本身清楚，`Rendered` 不再突破传入 budget；削减顺序先去 Version、
  尽量保留带 Event ID 的标题行，普通省略仍可行动。
- `team_history` 集成测试已精确解析 `history-1` / `history-2` 的 function-call output，并真实使用
  `next_before -> before` 取回两页内容；上一版整份 request 搜索导致的假阳性已消除。
- 第一次 attempt 捕获/渲染后复用同一投影给 provider retry 的行为仍成立。

## 仍阻断验收的问题

### 1. `NoRoom` 仍然先进行一次无投影 sampling，而不是先 compaction

- `core/src/team/projection.rs:87-95` 遇到 `NoRoom` 只调用 `session.request_new_context_window()`，随后返回 `None`。
- `core/src/session/turn.rs:1359-1381` 把这个 `None` 当作“本次不附投影”，继续构造 Prompt 并立即调用 provider。
  模型因此会在完全看不到活动团队状态的情况下先做一次决定，直接违反“活动视图在模型决定是否调用团队工具之前进入
  本次采样上下文”。
- 新窗口 flag 只在 provider 响应后的 `turn.rs:422-435` 消费，而且 `should_roll_over` 还要求
  `needs_follow_up=true`。若模型直接给最终答复，compaction 不发生，flag 因短路继续残留；即使模型调用工具，也已经先
  依据缺失团队状态的请求做过决定。
- 当前测试只有 renderer 的 `NoRoom` 单测；已有 compaction 集成是由 provider usage 超限触发，没有证明
  `NoRoom -> sampling 前 compaction -> 重新渲染投影 -> provider`。
- 修复边界：`NoRoom` 必须成为 provider 调用前的显式控制流，先压缩并基于新 prompt 重新捕获/渲染，再允许普通
  sampling。具体用返回枚举、外层循环或现有 compaction 接缝实现均可，不限制路线。

### 2. 所谓“实际待发请求”预算仍漏算模型可见部分

- `core/src/team/projection.rs:102-115` 只从 window 中减去 base instructions 与 `prompt_input`。
- 实际 `Prompt` 还包含 `ToolRouter::model_visible_specs()` 产生的 tools 以及可选 `output_schema`
  （`session/turn.rs:1280-1295`、`client_common.rs:18-35`）；Responses 请求会实际发送这些内容。动态 MCP/tool schema 可以
  很大，不能假设固定 2k headroom 必然覆盖。
- renderer 估算的是 projection 纯文本，而实际追加的是带 role/content 等 framing 的 `ResponseItem`。在“基础请求仍能
  放下、加投影后越窗”的边界上，这些漏项会高估可分给投影的空间，因此 hard boundary 仍未被最终 Prompt 闭合。
- 修复边界：预算应以 provider 即将接收的最终模型可见 Prompt 为准，至少计入 tools、output schema 与投影 item framing，
  并保留当前 4k / 2k / 20% 策略。无需复制整套 tokenizer，也无需新增预算审计系统。

## 本次验证

- `just test -p codex-team-state -p codex-features`：80/80 通过，本次未观察到 flaky。
- `just test -p codex-core -E 'test(/team_world_state/) + test(only_verifiable_sessions_get_a_team_identity)'`：7/7 通过，
  3329 skipped。
- 两组仅各运行一次，均通过共享构建锁/cgroup 看门狗；最后一组记录 project 72.36 GB、target 52.94 GB，未触发停止。
- `git diff --check 95a57b5..19a0318`：通过。
- 未重跑广口径 core/rmcp、全 workspace、Bazel、Docker、真实 API 或本地模型，符合本轮轻量复验范围。

## 替用户作出的决策

1. **决策 020/021 的目标继续接受，但当前实现未完成。** `NoRoom` 不能先采样再择机压缩；必须在 provider sampling 前
   完成 compaction 与重渲染。
2. **接受决策 022 的削减顺序。** 尽量保留 Event ID 是低成本且必要的下钻能力；若连标题行都放不下，则进入上述
   pre-sampling compaction，而不是发送无投影请求。
3. **一次未记录名称、随后 12 次未复现的 flaky 记为非阻断观察项。** 日志没有冒充已定位或已排除，本次一次独立复跑也
   全绿；除非再次出现，不要求继续消耗资源追查。
4. **保持既有产品决策。** `team_state_enabled` 默认关闭；Root 全队/member 已有可见性与贡献资格；
   `wait_agent_enabled` 独立；不增加 ACL、审计或可信体系。
5. **不补跑重型门禁。** 85 个宽门禁失败集合前后一致仍只证明没有新增宽门禁失败；Bazel 保持未验证非阻断，不安装、
   不下载、不冒充通过。

## 交付状态

- 本次仅新增本复验报告；未修改实现、ExecPlan、WBS、main 或 L6 工作树。
- `19a0318` 未合并、未推送。建议在原 M-1 工作树仅修复上述投影控制流与最终 Prompt 预算后再次提交复验。
