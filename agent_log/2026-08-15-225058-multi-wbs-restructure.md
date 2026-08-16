# RONDO Multi 规划重构：设计语义冻结与 M-1—M-5 重排

- 输入：用户的《RONDO Multi 当前最新完整设计（补充修订版）》（原始意愿）与《RONDO Multi 修正方案意见稿
  （工程落地版）》（AI 对工程落地的建议）。本批把二者收敛进 `doc/WBS.md` 与
  `doc/WBS/multi-agent-trusted-evidence.md`，并关闭 D1/D2。
- **只改文档，未运行 Cargo、Docker、真实 API 或本地模型。** 下面的源码结论全部来自对 `multidev/` 的静态阅读，
  未经编译或运行验证。
- 决定与结论已写进 WBS，本日志只记录**支撑决定但不适合进 WBS 的依据**。

## 源码核查：决定的实际依据

意见稿是照冻结 Codex 源码写的，本次逐条对 `multidev/` 复核。以下七处是真正改变了取舍的观察。

1. **既有 world-state 通道不是 request-only 投影。**
   `core/src/session/world_state.rs::build_world_state_for_step()` 确实每个 step 重建一次，但
   `core/src/session/mod.rs` 拿它与上一份 snapshot 算 RFC 7386 merge patch 之后，`render_diff()` 产出的
   fragment 走 `record_conversation_items()` 进 conversation history，patch 再 `persist_rollout_items()`
   落 rollout。
   → 意见稿"第一版先借用 extension WorldState section"会把 Active World Index 塞回可压缩消息流，
   并在 rollout 里堆积过期投影，只能靠"本条取代此前所有投影"这类标记打补丁。这是语义级偏差而非临时实现，
   将来改回来投影渲染与相关测试都要重做。**用户的保留意见成立，不采纳。**

2. **采样输入有唯一组装点，request-only 投影落得进去。**
   `core/src/session/turn.rs` 的 run_turn 循环每轮现构造
   `sess.clone_history().await.for_prompt(...) -> Vec<ResponseItem>`，紧接着交给 `run_sampling_request()`
   → `build_prompt()`。Root 与子 Agent 共用同一个 Session/turn 循环，agent turn 的采样只有这一条路径
   （compaction、startup prewarm 与 prompt-debug 各自另行构造 prompt，不属于 agent turn 采样，需分别确认是否要投影）。
   → 在这一点挂一份不写回历史的投影，语义与"与消息上下文并列、不受 compaction 影响"完全对齐；
   而且投影位于输入尾部，对 prompt 前缀缓存友好（写进历史的做法同样在尾部，但会永久占位）。
   这是把 M-1 定成纵切、而不是先借道再返工的直接依据。

3. **`wait_agent` 已经是"先订阅、再检查待处理活动"的形状。**
   `core/src/tools/handlers/multi_agents_v2/wait.rs` 先 `subscribe_activity()` 取回
   `watch::Receiver<InputQueueActivity>` 与 `pending_activity`，命中 pending 立即返回，否则
   `select` changed/timeout。上游已用这个形状解决 mailbox 的 lost-wake。
   → 意见稿提的"持久 wake generation"不是新机制，是照抄现成形状再加一路。风险低于预期。

4. **团队状态的挂载点有一模一样的先例。**
   `core/src/agent/control.rs` 的 `AgentControl` 是 `#[derive(Clone, Default)]`，注释明确它"每个 root
   thread/session tree 至多创建一次，然后与该 root spawn 出的每个子 agent 共享"，其中
   `rollout_budget: Arc<RolloutBudget>` 的注释就是"session-scoped state shared by the root thread and
   every cloned sub-agent control handle"。
   → "同一 Root 树内共享同一份 canonical 团队状态"不需要新建共享机制，顺着这个字段旁边放即可。

5. **Fact 捕获点确实是单点。**
   `core/src/tools/registry.rs` 的 `AnyToolResult::into_response()` 是工具结果转 `ResponseInputItem`
   的集中出口。
   → 意见稿"在 finalized tool output 进 history 前捕获"落在一个位置上，不必挨个工具 handler 改，
   也不必事后解析 rollout。M-3 的侵入面比预想小。

6. **route 的投递模式不用新造。**
   `multi_agents_v2/message_tool.rs` 已有 `MessageDeliveryMode { QueueOnly, TriggerTurn }`，
   `send_message` 走 QueueOnly、`followup_task` 走 trigger。
   → M-2 只需决定何时选哪个，不需要新增传输语义。

7. **权限可以从 Session 身份推导。**
   `protocol/src/agent_path.rs` 有 `AgentPath::is_root()`。
   → "不信任模型自报 author/root 标志"不是理想主义要求，是现成能力。

## 为什么阶段压成 5 个纵切，而不是意见稿的 9 个横向阶段

意见稿建议先做纯状态机、再接宿主、再接工具、第 4 阶段才接投影、第 5 阶段才接唤醒。工程上稳妥，但
**多智能体的真实风险集中在跨 Session 的状态提交与唤醒时序**——这恰恰是横向分层测不出来的部分。
前四层全绿之后第五层才暴露时序问题，返工面覆盖前面所有层。

所以 M-1 直接取意见稿 §三十二 那条纵切链路作为完成标准（发布 → 唤醒 → 投影 → Root 处理 → 追加 Version
→ 重新获得注意力），把 route、Fact、orphan、relation 拆到后面。层内顺序留给 plan 决定，WBS 不管。
这与"稳步推进、每步可控"不冲突：每个阶段仍然是一个可独立验收的完整能力，只是切法是竖的。

## 语义裁决的理由（WBS 只留结论）

- **权限维度砍成两个。** 意见稿要拆 visibility / route assignment / contribution 三层。前两层解决的是真矛盾：
  单靠一个 `visible_to` 集合，要么 Event 永远赖在子 Agent 活动列表里，要么撤销可见性去假装它没看过——
  用户原设计其实已经承认这里没定（"具体 route 信息何时不再对目标 Agent active，第一版继续复用 Root 的
  任务与通信语义"）。第三层 `observe_only` 则是为尚未出现的需求提前建权限：原设计里被 route 的 Agent
  默认就可贡献，且将来放开是向后兼容的加法。**故取二留一进候选池。**
- **Root attention 对 producer 只读可见（第 9 条，本次新增，非原设计也非意见稿）。** 双生命周期解耦很干净，
  但留了盲区：Root 标 tracking 表示"我在等这件事"，producer 完全看不见，可能已认为可以收工，
  两边都以为对方在处理。单向可见成本近乎为零（producer 的活动列表本来就要展示自己的 Version），
  且不破坏解耦——双方仍然只能改自己那一侧。**这条是我加的，用户尚未确认，若否掉不影响其他条款。**
- **Fact 措辞收窄。** 原设计称原始 payload"继续保存在原有 rollout/thread/tool state 中"。实际上 Codex 对进入
  历史的大工具输出会截断，无法承诺任意 Fact 都能找回完整原始字节。收窄为"只承诺身份与定位，指向 Codex
  实际保留的那份 observation，取不到必须显式标注"。协作语义（可追溯、可下钻、可重新验证）不受影响，
  但避免了在证据可靠性上给出做不到的承诺。

## 对意见稿的取舍总账

- **采纳进语义合同**：TeamStateStore/Projection 两层分离、投影时点前移、route 只发紧凑通知、
  visibility 先于投递提交、wake 用持久 generation、Root 自建默认 tracking 且不自唤醒、
  producer 关闭 Root-active Version 触发唤醒、`RetiredByRoot`、投影硬预算加显式 overflow、
  `team_epoch`、权限从 Session 身份推导、Fact locator 语义、Fact 窗口确定性。
- **降到阶段完成标准或不变量**（不写进 WBS 正文）：revision/幂等键、锁边界、authored 与生命周期投影类型分离、
  transition table、原子 projection 快照、批量 resolve 带显式版本集、payload guardrail、状态不变量清单。
  这些是正确性条件，不是规划内容。
- **降到候选池**：Event relation、workspace chronology、`observe_only`、持久化、materialized head/history folding。
- **不采纳**：借用既有 world-state section 承载投影（理由见上）；九阶段横向切分（理由见上）；
  `based_on_versions` 与向量时钟（对 2–8 Agent 过度）。

同时按用户裁定推翻了旧 WBS 中与本设计冲突的部分：root 为唯一 writer 且 child 只读由宿主收窄、
"主候选 + 审查者"流程形态、以及把"朴素自然语言转述模式"作为设计约束（降为测评期可选开关——
把它作为产品内长期维护的平行降级模式，成本高且会污染核心设计）。

## 已知风险与未验证项

1. **token 估算口径。** `context_manager/history.rs::estimate_token_count()` 基于 history items 计算。
   request-only 投影不进 history，会被漏算，导致上下文余量被高估。**M-1 必须把投影预算并进估算**，
   否则接近上限时会翻车。这是选这条路的已知代价，不是阻断项，但不能忘。
2. 上述源码结论均来自静态阅读，未编译、未运行、未写探针验证。M-1 的 plan 应先做一次 live 复核再动手。
3. `multidev/` 与冻结 Codex 的差异集中在 Guardian/审批链路；本次核查的多智能体接缝未见 RONDO 侧改动，
   但**未做逐行 diff**，不能断言完全一致。
4. 团队规模假设 2–8 Agent。所有"锁内提交、串行 mutation"类判断只在该规模下成立。
