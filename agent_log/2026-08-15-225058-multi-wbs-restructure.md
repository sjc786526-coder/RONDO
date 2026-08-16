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

2. **request-only 投影落得进去，但挂点不是我最初认定的那个。**（本条已按独立审查更正，见下）
   `core/src/session/turn.rs:334` 的 run_turn 每轮现构造
   `sess.clone_history().await.for_prompt(...) -> Vec<ResponseItem>` 再交给 `run_sampling_request()`。
   我最初把这里当成唯一组装点，**这是错的**：`run_sampling_request` 内部还有流重试循环
   （`:1339-1345`），`initial_input.take()` 只喂第一次，**之后每次重试都重新
   `clone_history().for_prompt()`**。团队投影按合同不进 history，所以挂在外层会在每次重试时静默丢失。
   正确挂点在重试循环内，且必须跨重试复用同一份快照（否则同一次逻辑采样前后看到不同团队状态）。
   现成先例就在旁边：`executed_tool_calls.attach_pending_to_prompt(&mut prompt_input, ...)`
   正是"在重试循环内向 prompt 注入非 history 内容、并用一份跨重试的状态保持一致"的既有做法。
   → 结论方向不变（request-only 可行、投影在输入尾部对前缀缓存友好），但"有一个现成单点"是我的误判，
   已写进 M-1 完成标准作为必验项。

   顺带：`multidev/AGENTS.md` 的 Model visible context 规则要求注入模型的内容一律有界、单项不超过 10K
   tokens，并且"避免频繁变动导致缓存失效"。前者使投影硬预算成为 M-1 的正确性条件而非后期优化；
   后者是接受投影每轮变化的代价，靠"只挂在输入尾部"把失效范围限制在尾部。

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
- **Root attention 对 producer 只读可见 —— 我加过，后经独立审查撤回，见下节。**
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

## 独立审查后的整改（同批第二轮）

外部审查（见 `agent_log/2026-08-15-224905-multi-wbs-independent-review.md`）指出 9 项应修、7 项去歧义与减法。
逐条复核后**全部成立**，其中四条依赖的源码断言我另行验证属实，已按下述结论修订 WBS。

真正改变行为、必须修的：

1. **活动视图谓词写错**（最严重）。我把"是否活动"单独交给可结束的 route 指派，丢了"自己仍有未终态 Version"
   这一支。后果是被 route 的 Agent 发布 open Version 后，Root 一结束指派它就看不见自己没结束的事项，
   直接击穿双生命周期。改为并集谓词，并统一适用于 Root（Root 也是 producer）。
2. **增量提交语义丢失**。原设计"只提交本轮变化、未提及项保持原状、不要求机械 keep_open"我没写进合同。
   若被实现成 replace-all 快照，模型少说一句就让事项静默死亡 —— 正是本系统要消灭的失败模式。已补为第 17 条。
3. **历史查询能力缺席**。原设计要求参与者可调取已退出活动视图的历史，我只在超预算语境里提了"下钻入口"，
   没有任何阶段交付它。已补为第 5 条并落进 M-1。
4. **陈旧视图/重试语义太薄**。原"并发不覆盖、重复不新增"不足以决定冲突时的行为。已补第 18 条：
   追加可陈旧但标记、生命周期变更陈旧则拒绝、重试不重复创建、批量只作用于显式列出对象。
5. **团队实例身份被弱化**。我只保护了"旧投影"，但 route 通知本身会进 rollout 并在恢复时重建
   （`RolloutItem::InterAgentCommunication` 持久化于 `session/mod.rs:3165`，重建于
   `session/rollout_reconstruction.rs:333`）。内存 store 重启后重新从 E1 编号，旧通知里的 E1 会误指新 E1。
   已把实例身份扩展到所有对外引用。
6. **权限未闭合，且现网有 fail-open 先例**。`multi_agents_v2/message_tool.rs:94-97` 现有
   `get_agent_path().unwrap_or_else(AgentPath::root)`；团队能力若照抄，无 AgentPath 的 helper session
   会被当成 Root，可改 root attention、可 route、可退休。已补"无权威身份 fail-closed"。
   同时补了证据读取范围（子 Agent 只能读自产或可见 Event 可达的引用）—— 否则 locator 会变成读取 sibling
   私有上下文的后门，与本设计的核心卖点冲突。
7. **投影预算不能等到 M-4**。`multidev/AGENTS.md` 的 Model visible context 规则要求注入内容一律有界、
   单项不超过 10K tokens。无界完整 chain 会让采样直接失败，是 M-1 的正确性问题。已前移。
8. **provider retry**：见上文源码核查第 2 条，我的"单点"判断有误，已更正并写进 M-1 必验项。
9. **M-3 / M-5 可空过**。M-3 原标准允许所有引用都标"不可得"仍算通过；M-5 原标准在协作功能关闭、
   团队工具从未被调用时也能通过。已分别补正向要求与"功能实际发生"独立门。

做减法或去歧义的：

- **撤回我新增的"Root attention 对 producer 可见"。** 撤回理由不是审查说了算，而是我复核后发现它**冗余**：
  合同第 10 条（producer 关闭 Root 仍活动的 Version 会唤醒 Root）已经从 Root 侧覆盖了同一个协调风险 ——
  producer 收工时 Root 立即被唤醒并可重新调度，producer 本就不需要知道 Root 在等。
  加上暴露 Root note 会污染"让两个 Agent 独立调查"的能力，净收益为负。降入候选池（若将来立项，只暴露状态）。
- **批量结束注意力从 M-4 移入候选池。** 我原本的理由"Root 会被注意力清理拖累"是预测不是观测，
  与用户"不提前优化尚未证明存在的问题"的原则冲突。
- **route 失败语义去歧义**：原"投递失败不产生半写入"容易被实现成失败即回滚可见性。改写为：canonical
  提交先完成且不回滚，通知失败记为可重试；要排除的只有"通知已到但读不到 Event"。
- **M-4 orphan 标准自相矛盾**：原写"orphan 不产生永久悬挂"，但设计明确无自动 escalation，Root 不操作就是会
  悬挂。改为可见性 + 可显式退休 + 保留操作者理由，并区分"可恢复但未加载"与"真正不可用"。
- **"唯一事实源"措辞收窄**为"团队协作状态的唯一 canonical 来源"，避免实现者把证据 payload 复制进来。
- 候选池改写成触发条件式，减少实现路线名称。

审查同时确认应保留的：M-1→M-5 主分期、拒绝复用既有 world-state 通道、canonical visibility + 短通知、
Root 默认 tracking 与 producer-close wake、locator-only Fact、两维（可见性 + 指派）减法、
原生多 writer、顶层 WBS 状态同步、D1/D2 关闭。

## 整改验收后的二次收口（同批第三轮）

验收审查（`agent_log/2026-08-15-231302-multi-wbs-remediation-acceptance.md`）判定不通过，提出 6 项阻断 + 1 项清理。
逐条复核后全部成立，两条依赖的源码断言另行验证属实。

两处会让阶段在核心目标未成立时通过的门：

1. **投影只限制了自己，没有计入整次请求的余量。** 我给投影加了硬预算，却没要求它计入
   `history + instructions + projection` 的总量。`context_manager/history.rs:174-188` 的估算只统计 base
   instructions 与 history items，request-only 投影两边都不在。于是 history 已逼近上限时，即使投影自身远低于
   10K，追加后仍可能直接把请求顶到 `ContextWindowExceeded`。
   **这条尤其该记：我在本日志"已知风险"里早就写对了结论，却没把它写进唯一权威的 WBS。**
   规划文档之外的正确认识不产生约束力 —— 这是流程教训，不只是遗漏。
2. **M-5 第一门只要求功能"被触发"，没要求工作流本身完成。** 机制全部触发、任务照样失败也能过门，
   而第二门跑的是另一组同题任务。两门相加仍证明不了"真实任务上跑通完整协作语义"。已要求冻结工作流达到
   自身预冻结的完成标准。同时把 orphan 退休从必触发清单里移出 —— 正常工作流不该为了过门人为制造 orphan，
   那属于 M-4 的定向验收。

四处会把实现引向错误行为的语义缺口：

3. **生命周期词汇从未定义。** 合同通篇使用 `pending`/`tracking`/`resolved`/终态，却没定义它们各自表达什么，
   也没写明普通参与者新建 Version 默认 `pending`。而"Root 自建默认 tracking"这条修订本身的前提就是
   普通发布默认 pending —— 缺了它，实现者把 child 新 Version 也默认 tracking 还能声称符合 WBS。
   已补一段最小词汇定义（producer `open`/`closed` + 独立的 Root 退休终态，`superseded` 按需后加）。
4. **"历史永久保留"与"第一版内存态"字面互相矛盾。** 已改为"当前团队实例存续期内追加式保留"。
5. **团队实例边界会误伤 residency 重载。** `agent/control/residency.rs:117-148` 会把常驻 V2 成员
   `shutdown_and_wait` 后 `remove_thread` 逐出，之后经 `ensure_v2_agent_loaded` 重新加载，
   而 Root 树和 `AgentControl` 始终存活。我原来的措辞把"进程或会话恢复"一概判为旧引用只作历史，
   会把这种正常的卸载/重载误判成新实例、陈旧引用或 producer 真正不可用，进而错误触发 orphan 处理。
   已明确：同一存活 Root 树内的重载仍属原实例，只有找不到对应团队状态或实例不匹配才开新实例。
6. **两处验收可空过。** M-2 只验了"结束指派后自己仍有 open Version 则保留"，没验反向——若结束指派实现成
   空操作、Event 永久常驻，照样通过；已补成对验收。M-3 要求"每个支持类别都有代表性引用下钻成功"，
   但没要求支持类别集合非空，且没验合同第 22 条的拒绝路径；已补非空要求与 fail-closed 定向验收。
   M-2 的投递规则也漏了"目标正在运行"这一支，已冻结为三分支。

清理：候选池里"原先排在 M-4……故移出"属于修订历史，按项目文档规范不应留在实时 WBS，已删。

## 缓存布局裁决（同批第四轮）

最终验收通过（`agent_log/2026-08-15-233743-multi-wbs-final-acceptance.md`），无新增阻断项。
本轮只按用户要求把投影的挂载位置约束补进合同（新第 17 条），依据如下。

**为什么这条必须进 WBS 而不只是实现细节**：用户原设计说 Active World Index"类似系统提示词那样的存在"。
这句话真正想表达的是"不受消息累加与压缩影响"，但字面很容易被读成"放在请求开头"。若真放在指令之后、
历史之前，团队状态每变一次就会让**其后的整段 conversation history** 失去前缀缓存 —— 而团队投影恰恰是
每轮都在变的东西。所以这是设计语义的澄清，不是工程口味。合同第 17 条据此拆成两层：不随轮次变化的协议规则
（状态含义、工具契约）进稳定且版本化的指令前缀，每轮变化的数据（活动视图、实例与版本号、省略清单）
保持 request-only 并附在请求尾部最后一个协议安全位置。

**边界来自源码而不是通则**：`for_prompt` 内的 `normalize_history` 会强制"每个工具调用都有对应输出、
每个输出都有对应调用"（`context_manager/history.rs:325-336`），随后 `attach_pending_to_prompt` 还会为已有工具
输出附加 prompt-only 元数据。所以投影只能在这些步骤全部完成之后追加，不能插进配对中间、不能重排历史、
不能越过尚未接纳的输入。这也解释了为什么"挂在外层首次 input"是错的（第三轮已记）。

**一处必须诚实说明的取舍**：把投影放尾部对**服务端前缀缓存**有效，但救不了本仓库 WebSocket 传输那条增量复用。
`client.rs::get_incremental_items` 要求本次 `input` 是"上次 input + 上次响应 items"的**严格扩展**；
上一轮的投影在这一轮已从原位置消失，前缀比对必然在那个位置失败，因此该增量复用在有投影时基本不再命中。
这是两套不同机制，不能混为一谈。第一版按正确性优先：不为保住增量复用而持久化旧投影、重复携带或改成累积补丁
（那会让旧团队状态冒充当前状态，违反第 6 条），也不把团队版本号编进缓存键。
缓存命中率与成本只作真实运行后的观测指标，不作为任何阶段的门。

## 已知风险与未验证项

1. ~~token 估算口径~~ —— 已升级为 WBS 合同第 16 条与 M-1 完成标准（见上节第 1 点），不再只是本日志里的提醒。
2. 上述源码结论均来自静态阅读，未编译、未运行、未写探针验证。M-1 的 plan 应先做一次 live 复核再动手 ——
   本轮"唯一组装点"被证伪就是静态阅读不够的直接教训。
3. `multidev/` 与冻结 Codex 的差异集中在 Guardian/审批链路；本次核查的多智能体接缝未见 RONDO 侧改动，
   但**未做逐行 diff**，不能断言完全一致。
4. 团队规模假设 2–8 Agent。所有"锁内提交、串行 mutation"类判断只在该规模下成立。
5. M-5 的"首个真实产品工作流"尚未冻结，只约定在 M-5 的 plan 里定。这是有意留白，不是遗漏。
