# RONDO Multi WBS 重构独立审查

日期：2026-08-15 ｜ 审查对象：`worktree-038-multi-wbs-restructure` 的 WBS 提交 `845d3ac`
（与审查开始时的 `29de80f` 内容一致）；核对时工作树 HEAD 为 `ea5bb30`

## 结论

**架构方向成立，WBS 主分期值得保留，但当前提交不宜直接合并。**

Claude 没有推翻原设计，且正确采纳了多项高价值工程语义：Harness-owned canonical team state、Event/Version
不可变 authored payload 与可变 lifecycle 的分离、双生命周期、sampling 前 request-only projection、正式 route
采用 canonical visibility + 短通知、Root-authored 默认 tracking、producer 终态变化唤醒 Root、locator-only Fact、
`RetiredByRoot` 的意图区分，以及 M-1 纵切后逐步接入 route、Fact 和收尾能力。这些均有实际源码基础，不是纸面设想。

需要修改的不是总体架构，而是几处会直接改变行为的语义缺口：活动视图谓词写错、增量 mutation 与历史读取消失、
revision/幂等/epoch 只剩结果口号、参与者与 Fact 下钻权限未闭合、request-only projection 没覆盖 provider retry、
M-3/M-5 验收可以空过。另有几项不必要地进入了首版硬路线，应做减法。

本轮只审查并新增本报告；没有修改两份 WBS、源码、研究稿或其他工作树，没有构建、测试、网络、Docker、API、
合并或推送。

## 应优先修正的问题

### 1. Child/Root 活动视图谓词写错，会让仍 open 的事项因 route 结束而消失

`doc/WBS/multi-agent-trusted-evidence.md:59-60,121-126` 把“是否继续占据目标 Agent 活动视图”交给可结束的
RouteAssignment。原设计与修正稿的正确规则是并集：

```text
Agent 自己仍有未终态 Version
或
存在面向该 Agent 的 active RouteAssignment
```

永久 visibility 只决定历史读取和第一版贡献资格，不能单独决定 active；结束 assignment 只能撤掉第二个纳入理由。
否则 B 被 route 后发布 open V2，Root 一结束 assignment，B 就看不到自己尚未结束的事项，直接破坏双生命周期和
“不能靠遗忘退出”的核心目标。Root 同时也是 producer，Root projection 也应包含“自己的 open Version”；否则
Root 将自己发布的 Version 标成 resolved 后，producer 侧 open 状态会在同一个 Root 视图中被隐式抹掉。

依据：原设计 `:19-23`；修正稿 `:424-472`。

### 2. “只提交变化、未提及项保持原状”的核心 mutation 语义被遗漏

原设计 `:23` 明确要求模型只提交本轮真正变化的 Event/Version，未提及的 active 状态保持不变，不要求机械
`keep_open`。Claude 的 24 条合同和 M-1 完成标准没有保留这一条。

这不是工具参数细节，而是产品核心行为。如果后续实现成 replace-all snapshot，模型某轮少复述一个 Event 就会让它
静默死亡，现有 WBS 仍可能形式上通过。应将 patch/增量 mutation 语义写回设计合同，并在 M-1 验收：一次 mutation
只改变显式目标，遗漏项保持不变。

### 3. revision、幂等和 stale-view 语义没有真正冻结

M-1 `:112` 只写了“并发不覆盖、重复不新增”，不足以决定发生冲突时系统该做什么。多个独立 Session 共享同一
TeamStateStore，只用 mutex 串行仍会得到语义上的 last-write-wins。

WBS 不需要写字段或锁实现，但至少应冻结以下行为：

- 每次 mutation 能说明它基于哪一份团队状态，重试有稳定的 operation identity；
- create/route/append 重试不重复创建对象或 assignment；
- append 基于旧视图时可以保留作者判断，但必须显式记录/返回 stale；
- producer/root lifecycle 变更若前置状态已变化，必须拒绝并返回最新状态，不能静默覆盖；
- 终态 Version 不原地 reopen，重新相关时追加新 Version；
- 任何批量变更只作用于 Root 明确看见并列出的 Version，不包含并发新增项。

这正是用户已认可的“把隐含正确性写死”，不是在 WBS 堆实现细节。具体 `operation_id`、revision/CAS 结构和锁形状
留给 M-1 plan。

### 4. `team_epoch` 不能被弱化成“旧投影不冒充当前”一句话

合同 `:76` 只保护旧 projection，但短 route 通知会进入 history/rollout：源码
`multidev/codex-rs/core/src/session/mod.rs:3143-3170` 会持久化 InterAgentCommunication，恢复路径
`session/rollout_reconstruction.rs:325-340` 又会重建它；Root resume 会创建新的 `AgentControl`
（`thread_manager.rs:891-923,1183-1189`）。如果新内存 store 又从 E1 开始编号，旧通知中的 E1 会误指新 E1。

应把 team instance/epoch 写成身份语义：Event、Version、FactRef、projection、mutation result 和 route envelope
都属于明确 epoch；恢复时没有对应 TeamStateStore，旧 projection、通知和引用统一只作 historical，epoch 不匹配
不得解析到当前 store，并显式提示 reset。M-1 先验 epoch/reset，M-2/M-3 沿用；这不要求现在实现 TeamState 持久化。

### 5. 参与者权限与 Fact 下钻权限没有闭合，需轻量 fail-closed

合同 `:61` 只说从当前 Session 身份推导权限，但没有规定谁是团队参与者、谁能改什么、谁能读哪些 Fact。

源码证明 TeamStateStore 可以挂在 root tree 共用的 `AgentControl`（`agent/control.rs:90-109`），但 Review、Guardian、
Internal 等 helper 也可能 clone 该控制面且没有 AgentPath。现有通信代码还有
`get_agent_path().unwrap_or_else(AgentPath::root)` 的先例（`tools/handlers/multi_agents_v2/message_tool.rs:94-103`）；
团队能力不能照搬这个 fallback，否则 helper 可能被误判为 Root。

应冻结最小权限矩阵，不建设复杂 ACL：

- 只有 registry 中登记的 root 与 V2 ThreadSpawn participant 获得团队投影/工具能力；无权威身份时 fail-closed；
- 只有 Version author 修改自己的 producer state；只有 Root 修改 root attention、route 和 orphan retirement；
- 只有 canonical-visible 且具贡献资格的 Agent 可向 Event append；
- Root 可读取本 team Fact；child 只可读取自产 Fact，或从其可见 Event/Version 中可达的 FactRef；
- locator 只授予目标 observation，不连带开放 sibling 的 rollout/thread 周边内容。

这既保护私有上下文和选择性传播，也比另建鉴权系统轻得多。

### 6. 历史 Event 查询与投影安全阀应在 M-1 交付，不能等到 M-4

原设计 `:23,27` 要求 Agent/Root 可按权限读取 historical-only Event。当前 WBS 只在超预算语义 `:52-53`
提到“下钻入口”，没有任何阶段明确交付历史读取；M-4 的调试 dump 不能替代模型可用的 `read_event` 等价能力。

同时 M-1 已把 projection 注入模型上下文，却到 M-4 `:144` 才验 overflow。`multidev/AGENTS.md:92-101`
明确要求所有模型注入有 hard cap、单项不得超过 10K tokens。无界完整 chain 会让采样直接失败，是 M-1 正确性，
不是后期性能优化。

应从 M-1 起同时具备：字段/单 Version/总 projection 硬预算、确定性 overflow manifest、权限受控且有界/可分页的
历史下钻，并验“未静默丢失”。materialized head/history folding 仍留候选池，不必提前实现。

### 7. request-only projection 必须覆盖 provider retry，Claude 所称“单点”并不完整

源码 `session/turn.rs:329-358` 构造首次 sampling input，但 `:1335-1359` 的流重试会重新从 history 取输入。
由于团队投影按合同不进入 history，如果只在外层首次 input 追加，重试请求就会丢失投影；若每次重试重新读取 store，
又会让同一次逻辑 sampling 前后看到不同 snapshot。

合同 `:48-50` 的 request-only、同一次采样一致快照方向正确，但 M-1 应明确验收：同一次逻辑 sampling 的所有
provider retry 复用同一不可变 projection snapshot；工具完成后的下一次 sampling 才读取新快照。无需在 WBS 指定
具体挂点，但不能把“有一个单点”当作已证明事实。

### 8. M-3 的 Fact 验收可以被“全部 Unavailable”空过

将 Fact 收窄为“Codex 实际保留 observation 的 identity + locator，不承诺完整原始字节”是正确且应保留的减法。
源码也支持这一判断：unified exec 的 `raw_output` 在 `tools/context.rs:313-327` 存在，但进入 ResponseItem 前会按
`:407-468` 截断；history 又在 `context_manager/history.rs:345-370` 进行有界处理。

问题在于合同 `:67-68` 与 M-3 `:133-136` 允许每个引用只要标为不可得就算通过，理论上所有 Fact 都不可解析仍能
声称“证据锚定完成”。完成标准应要求：

- 对首版明确支持的高价值 observation 类别，至少有代表性 Fact 在正常生命周期内真实可下钻到 finalized retained
  observation/可用表示；
- `Unavailable` 是诚实的退化状态，不是 normal-path 的替代成功；
- locator 只能在稳定 ID/定位信息与实际可用性确定后提交，持久化失败不得伪装 `Retained`；
- 团队工具与 read_event/read_fact 默认不递归产 Fact。

源码 `session/mod.rs:2903-2956` 才为内部副本补稳定 ResponseItemId，`:3609-3616` 的 rollout append 失败当前只记日志，
因此 Claude 汇报的“集中单点直接捕获”方向可行，但真实 durable boundary 仍须 M-3 plan 设计。WBS 的“下钻原始结果”
也应改成“下钻 Codex 实际保留的 observation/可用表示”。

### 9. M-5 只有退化门，Multi 功能关闭或从未触发也可能通过

M-5 `:148-153` 的完成标准完全跳到 `:168-181` 的同题任务是否完成。若 Multi 协作功能关闭、Event 工具从未被模型
调用，结果可能与冻结 Codex 一样而通过，这不能证明“真实任务上跑通完整协作语义”。

M-5 应有两个相互独立的门：

1. 冻结一个真实 Multi 工作流，证明 Event/Version、wake、route、多作者追加、Fact 下钻和 attention/orphan 收尾
   在 feature-on 运行中实际发生，且没有状态不变量失败；
2. 再做当前保留的相对冻结 Codex 小样本稳定单向退化检查。

内部 Event/route/Fact 计数只作为 Multi 激活证据和诊断，不混进跨二进制任务完成率。首个工作流可在 M-5 plan
冻结，不必现在把 reviewer/verifier 等固定角色写死。因此 D1 的“下一增量”可以关闭，但“首个真实产品工作流”
仍需在 M-5 前闭合。

## 需要去歧义或做减法的问题

### 10. M-2 route 失败语义必须明确保留 canonical commit

M-2 `:124-126` 同时写“先提交可见性再通知”和“投递失败不产生半写入”，容易被实现成失败时回滚 visibility。
正确语义应写成：visibility 与 assignment 先完成 canonical commit；notification 是锁外副作用；失败时保留前者，
RouteRecord 标记 failed/pending，可幂等重试通知，不回滚、也不重复 assignment。唯一必须禁止的是“通知已到但读不到
Event”，不是“canonical grant 已生效而通知暂时失败”这一显式状态。

M-2 plan 还需冻结 route 的行为意图：仅排队的信息使用 queue-only；要求 idle sibling 开始处理的 assignment 必须
触发其下一轮。源码中 `send_message` 与 `followup_task` 分别是 queue-only 和 trigger-turn，二者不是可随意互换的文案。

### 11. 用户已接受的 Root tracking 与 producer-close wake 尚未进入 M-1 验收

合同 7/8（`:39-40`）正确吸收了用户明确接受的修改，但 M-1 完成标准没有验证：

- Root-authored Version 默认 tracking 且不 self-wake；
- producer 将 Root pending/tracking 的 Version 置终态会 wake Root；Root 已 resolved 的旧 Version 只改 producer
  state 时不重新激活；
- 连续两次 wait 中，已消费 generation 不产生 phantom wake，新 generation 必须再次 wake。

现有 `wait_agent` 确实采用“先订阅、再检查 pending”的安全时序（`multi_agents_v2/wait.rs:68-75,178-195`，
`session/input_queue.rs:55-75`），值得复用；但团队变化仍需要持久 unread generation/ack，不能只发瞬时 Notify。

### 12. `RetiredByRoot` 应明确为不同于作者关闭的终态，orphan 验收不能承诺自动消失

合同 `:42-43` 只写“显式退休”，尚不足以排除“producer_state=closed + override flag”这类易丢语义的实现。
建议把 `RetiredByRoot` 或等价的独立 typed terminal state 写成首版产品语义，保证它不冒充 producer 自己关闭。

M-4 `:144` 的“orphan 场景不产生永久悬挂”又与“Root 显式退休、无自动 escalation”冲突：Root 不操作时事项当然
仍会悬挂。正确验收是 producer 不可用状态明确可见，Root 可显式退休，退休后退出对应 active 理由且保留操作者/理由。
还应区分 unloaded-but-resumable 与真正 unavailable；Completed/Interrupted/NotFound 不能机械等同永久 orphan。

### 13. 新增的“producer 可见 Root attention”不应现在冻结为核心语义

合同 9（`:41`）是 Claude 新增项。它不是修复双生命周期正确性的必要条件：producer 是否结束自己的事项，应由自己的
producer state 和显式 RouteAssignment/任务通信决定；单看 Root `tracking` 既不能说明 Root 在等谁，也可能被模型
误读为 ownership transfer。若连 Root note 一起暴露，还会不必要地影响独立调查。

本次决策是：**从冻结合同删除，降为候选观测项。** 真实轨迹证明信息不对称确有问题时，可以先只读暴露 state +
revision，不默认暴露 Root-owned note。无需为此增加第三套权限或 UI。

### 14. 第一版采用“visibility + assignment 两维”可以保留，但活动谓词必须修正

不在第一版单独实现 observe-only/contribute 是合理减法：当前正式 route 本来就是把事项交给目标 Agent 参与，贡献资格
可暂时随永久 visibility。以后确有“只告知不允许追加”的需求，再加 ContributionCapability 是向后兼容扩展。

但必须按问题 1 修正：visibility 决定可读/可贡献，assignment 与 Agent 自己 open Version 的并集决定 active。

### 15. M-4 的“批量结束 attention”不是首版必需交付

修正稿只要求“如果实现批量 resolve，不能覆盖并发新增 Version”；它没有证明逐项消费已成为瓶颈。WBS `:142-143`
却把低成本批量结束排成 M-4 核心能力，增加了不必要范围。

建议降入候选池；若真实使用后确需加入，必须只作用于显式 Version 集并遵守 stale/revision 语义。M-4 保留 orphan
退休、状态 dump/精简 mutation log、projection overflow 可解释即可。

### 16. “Team World State 是唯一事实源”措辞过宽

合同 `:30` 应收窄为：TeamStateStore 是 Event、Version、lifecycle、visibility、assignment 等**团队协作状态的唯一
canonical source**。原始 observation 仍由 Codex 实际保留的 rollout/tool 结果承载，Fact 只是 locator；Event/Handoff
又是 Agent 的语义判断，不是客观事实或当前真理。这个改词能避免实现者把 Fact payload 再复制进 TeamStateStore。

### 17. 候选池应保留能力触发条件，减少具体实现路线名称

`materialized head/history folding`、`workspace revision`、`worktree/lease` 等可继续留在研究稿；WBS 候选池只需写
“当 projection 成本、证据新鲜度或多 writer 冲突成为真实瓶颈时，再立独立任务”。这是文档职责上的轻量整理，
不影响架构结论。

## 值得保留的设计与裁决

1. **保留 M-1 → M-5 主顺序。** 先纵向证明团队状态与模型记忆解耦，再接 route、Fact、收尾和真实验收，依赖合理。
2. **保留拒绝复用现有 Codex WorldState 的决定。** 源码 `session/mod.rs:3003-3033` 会把 diff 写进 conversation
   history 并持久化 WorldState patch；这与 request-only projection 的语义相反，借用后再改会返工。
3. **保留 canonical visibility/assignment + 短通知。** 完整 chain 始终从 TeamStateStore 读取，避免 history 中出现
   陈旧副本；固定 visibility-first，但按问题 10 明确失败状态。
4. **保留 Root-authored 默认 tracking/no self-wake 与 producer-close wake。** 两项都是低成本、明确改善协调时序的
   行为，应补 M-1 验收。
5. **保留 locator-only Fact 与工程截断。** 不复制全量工具输出、不建 artifact store；语义完整指 canonical 历史
   可查询，模型投影必须有硬预算和显式 overflow。
6. **保留无自动语义判断。** Harness 不自动把 Fact 升级为 Event、不自动聚类/合并、不自动判断 Root 对错。
7. **保留 Shared workspace 原生多 writer。** 第一版不引入 worktree/lease/写锁；发生真实冲突后再独立评估。
8. **D1/D2 可以从顶层待定决策删除。** 下一增量已明确为 M-1，价值命题也已转为工程实践；朴素自然语言模式仅作为
   测评期按需开关，不长期维护。M-5 的真实工作流缺口按问题 9 后续冻结即可。
9. **顶层 `doc/WBS.md` 的状态同步总体准确。** 当前方向、M-0、下一步 M-1、runtime bundle 和真实 API 授权边界
   表述精炼，无需恢复旧的 D1/D2 章节。

## 合并前集成事项

- 审查期间，主线提交 `4ebf62d` 已纳入两份研究稿，目标工作树也已基于该提交重放 WBS；研究稿引用当前不再悬空。
- 当前 WBS 提交为 `845d3ac`，Claude 随后以 `ea5bb30` 只新增了其重构说明日志；两份 WBS 内容与本轮实际审查版本一致。
- 本报告是当前工作树唯一未提交文件；本轮没有代替 Claude 修改 WBS，便于其按审查意见修订后再决定是否合并。

## 最终判断

本次不是“方案推翻”，而是**方向通过、语义合同需整改后再合并**。优先修 1—9；10—16 做去歧义和减法；
保留既有主分期与顶层 WBS 状态结构。无需新增数据库、artifact store、复杂 ACL、持久 TeamState、调度器、UI、
审计平台或重型 benchmark。
