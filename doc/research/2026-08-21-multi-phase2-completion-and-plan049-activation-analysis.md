# RONDO Multi 第二期完成态与任务 C 主动委派未激活分析

> 文档性质：2026-08-21 时点冻结的研究报告，用于后续人与网页端 AI 讨论。
> 当前代码基线：`main@23596204c6c258198c40e59114c806b5129d3d65`，形成报告前与 `origin/main` 一致。
> 规划边界：本文记录完成事实、源码设计、证据解释和候选研究问题，不是新的任务排期；当前规划唯一来源仍是
> `doc/WBS.md` 与 `doc/WBS/multi-agent-trusted-evidence.md`。
> 研究对象：RONDO 是基于冻结 Codex CLI v0.147.0 修改的产品，产品源码位于 `multidev/`；本文中的“Codex”均指
> 冻结对照产品，不指开发过程中使用的 Codex 工具。

## 1. 执行摘要

RONDO Multi 第一期与第二期 A、B、C 均已完成，当前没有已排期的 Multi 下一任务包。第二期三个任务的完成含义不同：

| 任务 | 性质 | 完成结果 | 它真正证明了什么 |
|---|---|---|---|
| A / Plan 047 | 正确性测试 | 通过 | Team State 的核心跨功能操作序列在有限性质测试中满足 reference state 与不变量；未发现产品缺陷 |
| B / Plan 048 | 观测工程 | 通过，零产品 hook | 原生 rollout trace 足以离线归约出确定、body-free 的跨产品 Team View，并生成自包含静态 HTML |
| C / Plan 049 | 真实付费测评 | 工程验收通过；activation 阴性 | 六个固定 pilot 都是有效运行，但两侧 Root 均未尝试主动委派，因此不能进入“委派后收益”比较 |

任务 C 必须同时保留三个看似矛盾、实际上处于不同层次的结论：

1. **测评工程通过**：合同冻结、真实运行、费用结算、trace、Root/Guardian 选择、恢复和停止逻辑均通过验收。
2. **activation 实验得到有效阴性结果**：六个 pilot 中 Root 的 `spawn_agent` attempt 和 accept 都是 0；这不是
   infra、费用或 trace 缺失造成的“没测到”。
3. **原始科学目标没有达成**：实验原本要比较“模型主动委派后，Team State 是否改善质量、速度或成本”；由于从未发生
   Root 委派，实验没有进入这个条件，所以不能回答收益问题。

本文的主要判断是：**任务 C 的直接失败原因是模型在共同的软性 proactive policy 下没有调用 `spawn_agent`；更深层的
设计原因是 RONDO Team State 被有意设计为“委派发生后的共享协调状态”，不是自动任务分解器或委派调度器。** 在第一位
成员出现之前，RONDO 相对 Codex 新增的 Team State 基本处于空闲状态，没有强机制改变 Root 的第一次 spawn 决策。

因此，C 的阴性结果不能推出“Team State 无效”，也不能推出“任务失败是因为没有委派”。它更准确地暴露了一个实验问题：
“自然主动委派是否发生”与“已经委派以后，Team State 是否有收益”是两个不同问题，当前实验把后一个问题的可测性依赖在
前一个问题先成功激活上。

## 2. 本报告如何使用证据

为了避免把推断写成事实，全文使用三类证据：

- **已验证事实**：来自冻结 plan、真实运行记录、独立验收报告、WBS 完成记录或当前源码的机械行为。
- **源码推论**：不是运行记录直接给出的数字，但可由产品控制流与数据流推出；本文会明确写“源码推论”。
- **待验证假设**：例如 pilot 任务是否让模型觉得不值得拆分、`medium` 模型对软提示是否不敏感。它们可以指导讨论，
  但不能当作本次失败的既定原因。

本次主要取用了以下证据：

- 当前/完成状态：`doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md`、`doc/WBS-COMPLETED.md`；
- 任务合同：`plan/047-team-state-sequence-properties-execplan.md`、`plan/048-rondo-team-lens-execplan.md`、
  `plan/049-multi-proactive-delegation-eval-execplan.md`；
- 最终验收：Plan 047、048、049 的最终执行日志与独立验收日志；
- 产品源码：`multidev/codex-rs/team-state/`、`multidev/codex-rs/core/src/agent/`、
  `multidev/codex-rs/core/src/team/`、Multi-Agent V2 工具处理器和上下文策略注入代码；
- 测评源码：`eval/rondo_eval/team_lens/`、`eval/rondo_eval/proactive_eval/`、冻结 lock、taskset 和 policy。

没有为了本文重新运行真实 API、Docker、Cargo、模型或正式测评，也没有读取敏感原始 prompt/response。本文对任务内容的判断
只使用已跟踪的任务身份、冻结合同和 body-free 汇总，不假装看到了仓库中没有公开保存的任务正文。

## 3. Multi 产品目前完成到了哪里

### 3.1 第一期：从原生多智能体工具到可验证的团队世界状态

冻结 Codex 本来已有 Multi-Agent V2 的控制面：Root 可以创建成员、发消息、追加任务、等待、查看和中断成员。RONDO
第一期没有重写这套原生 agent runtime，而是在同一棵 Root agent tree 上增加一个由 Harness 持有的 Team State。

第一期按 M-1 至 M-5 形成了以下能力：

1. **M-1：Team State 基线。** 建立 canonical Event/Version、producer 与 Root 双生命周期、活动投影、revision、
   幂等重试和 wake 纵切。团队状态不再依赖模型各自记忆。
2. **M-2：选择性路由。** Root 可把 canonical Event 路由给具体成员；“获得可见性”“承担工作”“通知是否投递成功”
   被拆成不同状态，避免一次通信失败破坏已经提交的协作事实。
3. **M-3：证据锚定。** Version 可引用 Harness 实际保留的工具 observation。Team State 保存的是 typed Fact identity
   与 locator，不复制工具正文；权限由 Root、producer 或 Event 可达关系机械决定。
4. **M-4：协调闭合与可观测性。** 增加 producer availability、Root retirement、恢复边界，以及有界
   inspect/dump/log/stats，能解释状态而不建立第二套全量 tracing 或持久数据库。
5. **M-5：真实工作流与不退化门。** 明确要求协作的真实运行证明完整协作链确实能被模型触发；20 个基础有效 run
   中未观察到相对冻结 Codex 的稳定单向退化。

第一期证明的是“机制可达、状态正确、在固定小样本中未见稳定单向退化”。它没有证明模型面对自然任务会主动委派，也没有
证明 Team State 带来质量、时延、token 或费用收益。第二期正是围绕这两个缺口增加稳定性测试、可视化和主动委派测评。

### 3.2 第二期 A：Team State 序列性质测试

Plan 047 在现有 `codex-team-state` crate 内增加一个默认 ignored 的有限性质测试，而不是另建 fuzz 平台。核心设计是：

- 用固定 Root 和少量成员生成 publish、producer/Root lifecycle、route、delivery、retry、wake 等组合步骤；
- 用一个“薄 reference state”只预测外部可观察结果，不复制产品内部实现；
- 每一步先预测 canonical ID、ordinal、revision 和 outcome，再执行真实 store mutation；
- 比较 store identity、对象数量、权限视图、route/delivery、wake 与 lifecycle；
- selector 总是从当前 canonical state 重新解析有效引用，使 shrink 后的最小反例仍有意义；
- invariant checker 能主动拒绝错误 canonical binding 和重复 active assignment。

冻结运行合同为 64 cases、每 case 最多 32 个候选步骤、固定 seed `20260820047`。最终结果：

- 默认门禁：128 passed、1 skipped，性质测试保持 ignored；
- 主动性质测试入口：1 passed；
- 未发现 Team State 产品缺陷，没有修改产品语义代码；
- 没有扩大到 Fact、真实 mailbox/residency、provider retry、Docker、API 或模型。

这项任务的价值不在“多写了一个随机测试”，而在于它首次系统探索跨模块状态组合，并能把真实缺陷收缩成可复现的最小序列。
它仍是有限、固定 seed 的正确性补充，不是无界 fuzz，也不是性能测评。

### 3.3 第二期 B：RONDO Team Lens

Plan 048 交付了一个本地离线 reducer/viewer。它不修改 Rust runtime，不新增 trace writer，也不运行在线服务。

数据流只有两步：

```text
原生 rollout bundle
        │
        ▼
Team Lens reducer ──► team_view.json（规范化、body-free、确定）
                              │
                              ▼
                      team_report.html（离线单文件）
```

`team_view.json` 是唯一中间合同。报告器不能回头读取 raw trace，这个约束防止可视化需求反向诱导产品保存更多敏感正文。

共同视图包括 Agent、turn、inference、usage、tool、terminal、interaction、wait 与 timing；RONDO 额外显示 Team
revision、projection、Event/Version、route 和 Fact 关系。每类能力都显式标为 `available`、`partial`、
`unsupported` 或 `not_applicable`：冻结 Codex 没有 Team State，因此是“不适用”，不能伪装成“空 Team State”。

安全与解释边界如下：

- 不复制 prompt、response、命令输出、Fact 正文或 raw trace 路径；
- 不分析或重建隐藏推理；
- schema 严格，未知键、损坏 bundle 和不明确产品身份 fail-closed；
- JSON 使用稳定排序，HTML 只嵌入已经验证的 Team View；
- 报告包含 Agent swimlane、工具/模型活动、interaction/wait、Team Attention、Event/Version 和 Fact flow，
  但不是审计平台或运行时调度器。

最终验收为 25/25 定向测试通过；24/24 个代表性 RONDO bundle 可归约，JSON 与 HTML 重复生成字节一致。Codex
侧没有可用的真实无费用 bundle，因此使用了结构忠实且明确标记的合成原生 fixture；这足以验证 reader/schema 的工程路径，
不被冒充为真实 Codex 行为证据。

### 3.4 第二期 C：主动委派与收益对比

Plan 049 是一个两阶段但同一合同的任务：

- **阶段 A，无费用准备**：冻结任务、策略、模型、工具、顺序、分类、trace、Team Lens、预算、resume 与停止语义；
  用 pure/fake/loopback/replay 和合成 fixture 排除可预见设施问题。
- **阶段 B，真实付费执行**：先运行六槽 activation pilot。只有至少一次 trace-backed Root spawn 被接受，才允许
  进入正式十题收益对比。

阶段 A 独立验收为 `paid-ready`。阶段 B 也完整执行并按预注册门正确停止。因此 C 不是“阶段没做完”，而是“实验做完，
激活条件未出现，原本依赖该条件的正式比较不适用”。

## 4. RONDO Multi 源码设计：网页端分析所需的最小完整模型

### 4.1 三层结构，而不是一套巨型多智能体框架

理解任务 C，最重要的是分清三层：

```text
模型的语义决策层
  判断是否拆任务、是否调用 spawn_agent、发布什么、如何 route/resolve
                │ 工具调用
                ▼
Codex 原生 Multi-Agent V2 控制面
  AgentControl、spawn/message/followup/wait/list/interrupt、成员 registry/residency/limiter
                │ 同一 Root tree 内共享
                ▼
RONDO Team State 协调状态层
  Event/Version、双生命周期、route、Fact、projection、wake、inspect
```

Team State 不是控制面的替代品，更不是模型决策层的替代品。它复用原生 spawn 和通信机制，并把“团队现在共同知道什么、
谁还需要关注什么、哪些观察支持某个版本”变成 Harness-owned canonical state。

### 4.2 原生控制面如何真正创建成员

`multidev/codex-rs/core/src/agent/control.rs` 中的 `AgentControl` 每棵 Root thread tree 最多创建一次，然后被所有子 Agent
共享。它持有：

- 原生 Agent registry；
- V2 residency；
- 并发 limiter；
- rollout budget；
- 一个共享的 `Arc<TeamStateHandle>`。

真正的创建路径位于
`multidev/codex-rs/core/src/tools/handlers/multi_agents_v2/spawn.rs`。只有当模型产生 `spawn_agent` 工具调用后，
handler 才会解析任务名、消息、fork、模型/effort 等参数，构造 `ThreadSpawn` session source，再通过
`AgentControl::spawn_agent_with_communication` 创建成员并触发其首轮工作。

这一控制流中不存在“Team State 发现可并行任务后自动调用 spawn”的分支。Team State 共享进 `AgentControl`，是为了让
已经存在的成员看到同一个团队实例，而不是让它成为 scheduler。

### 4.3 Team State 保存什么

`multidev/codex-rs/team-state/src/lib.rs` 对 crate 的定位很直接：团队依赖的协作状态归 Harness 所有，不归任何模型的
记忆所有。其核心对象是：

- **Event**：一个需要团队持续关注的语义事项；
- **Version**：某个参与者对 Event 的一次不可变 authored checkpoint；
- **Fact**：Harness 实际保留的 observation 的稳定引用，不是正文副本；
- **Route**：Root 将 Event 的可见性或工作职责交给指定成员的 canonical 记录；
- **Team revision**：canonical mutation 的全局顺序；
- **projection**：每次模型采样前，从当前状态重新生成的 Active World Index。

`model.rs` 把 Version 分成不可变 authored 内容与可变 lifecycle：作者、summary、handoff、evidence refs 一旦创建就不
重写；可变部分只包括 producer 当前是否仍关注、Root 当前是否仍需要协调，以及作者不可再行动时的独立 retirement。

两条 lifecycle 轴刻意独立：

- `ProducerState::Open/Closed` 表示作者是否认为事项仍需其关注；
- `RootState::Pending/Tracking/Resolved` 表示 Root 是否仍需要协调它。

作者 close 不等于 Root resolved，Root resolved 也不宣称事项已经客观解决。这避免把“工作者做完了”和“协调者已经处理”
压成一个容易失真的 done 标志。

Route 同样拆开三个概念：

- 可见性一经授予不可撤销；
- duty 可以是 notice、assigned 或 ended；
- delivery 可以 pending、delivered 或 failed。

所以通知失败不会回滚已经提交的可见性/assignment，迟到的失败也不能覆盖成功。这个设计面向异步协作中的真实部分失败。

### 4.4 canonical store 为什么可靠

`team-state/src/store.rs` 的 mutation 在一个同步 canonical store 中完成，外层 `TeamStateHandle` 用单 mutex 保护。
所有 precondition 在一次无 `await` 的临界区内检查并提交，避免异步通知把状态提交撕开。store 负责：

- 分配和推进 revision；
- 绑定幂等 request identity；
- 区分“基于旧 view 追加仍可接受”和“生命周期前置条件不成立必须拒绝”；
- 确保拒绝没有 partial write；
- 先提交 route visibility/assignment，再由上层尝试通知；
- 单独记录 wake ledger，避免已消费变化重复唤醒。

这解释了为什么 Team State 主要解决的是**发生协作以后**的状态一致性，而不是是否应当发生协作。

### 4.5 Fact 是可解释证据，不是第二份 transcript

M-3 在原生工具执行与 conversation retention 之间增加了机械绑定：工具 dispatch 前预留唯一 output item identity，
工具形成终态时记录 observation，只有该结果实际进入保留 history 才铸造 Fact。Fact 保存 producer、工具类别、稳定 identity
和 locator；正文仍在 Codex 原生历史中。

Version 发布时，Harness 确定性地关联作者自上次成功 publish 以来新增的 Fact。读取权限按团队角色和 Event 可达关系计算；
如果 producer 已卸载或当前 history 已不再持有正文，接口诚实返回不可用原因，而不是伪造永久可恢复性。

这套设计使 Team Lens 能画出 Fact flow，也使网页端理解一个关键边界：Team State 提供“这项结论当时基于哪些实际观察”
的身份链，但不保存完整命令输出，不判断 Fact 今天是否仍为真。

### 4.6 projection 与 wake 如何进入模型上下文

Team State 不把状态永久追加到对话历史。`team-state/src/render.rs` 与
`core/src/team/projection.rs` 会在每个逻辑采样请求前，从同一个 snapshot 重新生成有 token 上限的 Active World Index，
作为尾部 developer context。provider 对同一次请求的网络重试复用同一 snapshot，避免重试期间状态变化造成请求漂移。

如果存在 active state 但预算不足，代码返回显式 `NeedsRoom`，而不是静默隐藏世界状态。投影包含当前参与者真正需要关注的
事项；resolved/closed/retired 等 lifecycle 和路由共同决定活动视图。

`multi_agents_v2/wait.rs` 在 Team State 开启时同时等待原生 mailbox activity 与 Team State wake。这里的 wake 只会让
已在等待的 Agent 获知团队状态发生了变化；它不会创建新 Agent。源码推论：在任务刚开始、尚无成员、Event 或 route 时，
这套投影和 wake 没有可供 Root 使用的实质协作内容，因此很难单靠自身改变第一次 spawn 判断。

### 4.7 工具面与身份边界

两侧共有的原生 V2 工具是：

- `spawn_agent`
- `send_message`
- `followup_task`
- `wait_agent`
- `list_agents`
- `interrupt_agent`

RONDO 在 `team_state_enabled && collaboration_tools_enabled && V2` 时额外注册：

- `team_publish`
- `team_update`
- `team_history`
- `team_route`
- `team_route_update`
- `team_evidence`
- `team_retire`
- `team_inspect`

这些 Team 工具也不会替模型 spawn。`core/src/team/mod.rs` 和 team tool handler 从当前 Session 的权威 thread identity
推导 actor；模型不能通过参数自称 Root、author 或 producer。目标成员也通过原生 registry 解析，未知身份 fail-closed。

### 4.8 proactive policy 在源码中究竟如何生效

`protocol/src/config_types.rs` 定义 `MultiAgentMode`：`Custom`、`ExplicitRequestOnly`、`Proactive`。
`core/src/session/multi_agents.rs` 的默认规则是：有自定义 `multi_agent_mode_hint_text` 时使用 `Custom`；没有自定义提示时，
`ultra` effort 使用内建 `Proactive`，其他 effort 使用 `ExplicitRequestOnly`。

Plan 049 固定为 `medium`，但通过自定义 developer instruction 注入同一 proactive policy，所以实验比较的是：

> `medium` + 相同的自定义 proactive policy + 相同 V2 控制面，RONDO 侧额外启用 Team State。

它不是 `medium` 的默认行为，也不是 `ultra` 的内建 Proactive 模式。冻结 policy 的语义是：自主判断独立、实质子任务是否
值得委派；只有可能改善结果或缩短时间时才委派；不要仅为展示协作而委派；Root 仍负责整合和最终答案。

这是一个有意保持自然性的软性成本收益准则。它保证“模型有权主动委派”，但不保证“每题至少委派一次”。因此，零 spawn
并不违反 policy。

## 5. Plan 049 的实验合同与真实结果

### 5.1 公平比较冻结了什么

| 维度 | Codex | RONDO Multi |
|---|---|---|
| Root/member/Guardian 模型 | `gpt-5.6-terra` | `gpt-5.6-terra` |
| reasoning effort | `medium` | `medium` |
| proactive policy | 相同冻结文本与 hash | 相同冻结文本与 hash |
| 原生 V2 协作工具 | 6 个共同工具 | 同样 6 个共同工具 |
| Team State | 无，Team Lens 标 `not_applicable` | 开启，额外 8 个 Team 工具 |
| Terminal-Bench 并发 | 1 | 1 |
| session 最大并发线程 | 4 | 4 |
| provider 请求并发 | 4 | 4 |
| 原生 rollout trace | 开启 | 开启 |
| 外部任务判定 | 同一冻结任务与 verifier | 同一冻结任务与 verifier |

Root、member、Guardian 使用同一模型/effort，避免把角色模型差异混进产品差异。六个 pilot 按预冻结 side × position
顺序运行三道任务，两侧各一次：

1. `filter-js-from-html`：Codex → RONDO；
2. `sanitize-git-repo`：RONDO → Codex；
3. `db-wal-recovery`：Codex → RONDO。

正式十题也提前冻结，但只有六个 pilot 全部有效且至少出现一次 Root accepted spawn，才允许启动。

### 5.2 activation 指标不是文字判断

`eval/rondo_eval/proactive_eval/aggregate.py` 不搜索模型说过“我会委派”之类的文本。它从 Team View 中：

1. 识别唯一 Root thread；
2. 统计 `kind == spawn_agent` 的工具记录，形成 attempt count；
3. 只把 Root 发起、interaction 完成、且对应 Root tool 也完成的 spawn 算作 accepted；
4. 只要任一有效 pilot 的 `root_spawn_accept_count > 0`，才令 `activation_observed=true`。

这个定义较严格，但符合研究目标：要比较真实协作收益，必须真的创建成员，不能把意图、失败调用或 Guardian 误计为主动委派。

### 5.3 Root/Guardian 双 bundle 缺口与修复

第一条 paid Codex 运行产生两个原生 rollout bundle：

- `SessionSource::Exec` 的 Root bundle：15 个 inference、14 个 tools；
- `SessionSource::SubAgent/Other("guardian")` 的独立 Guardian bundle：1 个 inference。

早期 locator 假定 trace 目录只能有一个 bundle，因此观测阶段 fail-closed。这个问题是 **trace 选择设施缺口**，不是任务运行
本身失败：Root trace 已存在，任务外部终态也已经是 `reward=0.0` 的有效 task failure，15 个请求与 `$0.262759` 已结算。

最终 `proactive_eval/trace.py` 的规则是：

- 必须且只能有一个 `Exec` Root bundle；
- 可以存在身份明确的 Guardian bundle；
- 双 Root、未知来源、损坏、不明确或 symlink bundle 一律 fail-closed；
- Team Lens 和主动委派聚合只消费 Root bundle，Guardian 不进入产品 agent/spawn 指标。

新 recovery identity 只读承接旧 a01、请求、费用、Terminal-Bench 结果和 trace，没有产生 a02，也没有 provider replay。
所以首槽在最终汇总中仍是 attempt 1，而不是为了得到更好结果重跑一次。

### 5.4 六槽结果

| 任务 | Codex | RONDO | 请求数与费用（Codex；RONDO） |
|---|---|---|---|
| `filter-js-from-html` | `task_failed` | `task_failed` | 15 / `$0.262759`；13 / `$0.238894` |
| `sanitize-git-repo` | `completed` | `completed` | 20 / `$0.733812`；16 / `$0.550285` |
| `db-wal-recovery` | `task_failed` | `task_failed` | 18 / `$0.443474`；18 / `$0.304460` |

总计：

- 6/6 均为有效 attempt 1；
- 2 个成功，4 个有效任务失败，0 infra；
- 6/6 `trace_status=available`；
- 100/100 请求按 usage 结算；
- 累计费用 `$2.533684`；
- 0 未结算 reservation、0 未知费用、0 stopped run；
- Codex 与 RONDO 六槽 Root 的 spawn attempt/accept 全为 0；
- `activation_observed=false`；
- 正式十题未运行，追加的机动预算也没有用来换题或扩大样本。

### 5.5 为什么停止是正确行为

activation gate 在付费前已经冻结。若六个有效 pilot 没有 Root spawn，合同要求停止，因为后续正式十题即便继续跑，仍不能
保证获得“委派以后”的样本。临时增加 pilot、换成更容易拆的题、加强提示或强制 spawn，都会把一个自然主动委派实验事后
改造成另一个实验，并产生选择性采样。

所以“还有很多预算却没继续”不是执行保守或设施失败，而是预注册停止逻辑在保护结论。剩余预算不能把阴性数据变成需要被
修复的异常。

## 6. 任务 C 所谓“失败”究竟是哪一层失败

### 6.1 没有单独的失败方

如果“失败方”指 Codex 或 RONDO 的某一侧，那么本次没有单独失败方：三题的外部结果在两侧完全同向，一题双方成功、两题
双方失败；主动委派指标也同样是六槽全 0。没有证据支持“RONDO 侧特别无法委派”或“Codex 侧特别失败”。

如果“失败”指任务 C 的目标，则应按下面四层区分：

| 层次 | 状态 | 解释 |
|---|---|---|
| 设施正确性 | PASS | 策略、工具、runner、账本、trace、selector、resume、Team Lens 与停止逻辑正确 |
| activation 实验 | 有效阴性 | 两侧 Root 在固定 pilot 中都没有尝试 spawn |
| 委派收益比较 | 未形成/目标失败 | 没有 post-delegation 样本，无法比较质量、时间、token、成本或协调行为 |
| RONDO 产品正确性 | 未发现失败 | 没有进入 Team State 协作链，不能据此认定 Team State 错误或退化 |

最终最准确的状态是：`completed / activation_not_observed`。

### 6.2 可以排除的原因

#### 不是 API、Docker 或真实运行设施失败

六槽都是有效 terminal attempt，0 infra，trace 全部可用，100 个请求全部结算。独立验收还验证了 Docker 和正式资产状态。
共享回归最初出现的 42 failures / 6 errors 来自继承代理变量使 loopback 统一返回 502；清除代理后 144/144 通过。这个
环境污染发生在测试复验，不是六个 paid pilot 的原因。

#### 不是费用或过窄重试把模型提前停掉

没有 budget stop、未知用量、悬空 reservation 或 stopped run。六槽都自然走到任务终态；只花了 `$2.533684`。用户给予
的宽容恢复空间也实际用于修 selector/recovery，而没有重放 provider 或污染公平合同。

#### 不是 trace selector 丢掉了真实 spawn

修复后的 selector 机械选择唯一 Exec Root，并明确排除 Guardian。聚合在 Root view 中同时看到工具 attempt 与完成
interaction，两个计数都为 0。若存在一个被拒绝或失败的 Root spawn，应至少出现 `spawn_agent` tool attempt；事实不是
“attempt 有、accept 无”，而是两者都无。

#### 不是 Guardian 被错误当成模型主动委派

Guardian 是审批审查路径产生的独立 subagent session，不是 Root 调用 `spawn_agent` 创建的工作成员。它有独立 bundle，
但不进入 Root 产品协作指标。将它计入 activation 反而会把审批机制伪造成任务委派。

#### 不是 Team State 在运行中拒绝了 spawn

spawn 由原生 Multi-Agent V2 handler 执行，Team State 不是 spawn 前置审批器。当前没有任何 spawn attempt，自然也没有
Team State 拒绝 spawn 的证据。

### 6.3 直接原因：模型选择了单独完成

从可观察执行链看，最接近根因、且证据最强的陈述只有一个：**Root 模型在六个运行中从未调用 `spawn_agent`。**

共同 policy 只要求“在可能改善结果或减少墙钟时间时主动考虑并委派”，同时明确“不要为了展示协作而委派”。模型可以合法得出
“当前任务自己做更合适”的判断。测评不读取隐藏思维链，也不应从工具序列伪造模型内心理由，因此无法进一步机械证明它是因为
任务小、风险高、拆分成本大，还是只是没有把软提示转化为动作。

### 6.4 更深层原因：产品与实验的因果位置不匹配

这是本文最重要的源码推论。

RONDO 与 Codex 在第一次 spawn 之前拥有相同模型、effort、自然任务 prompt、共同 proactive policy 和六个原生协作工具。
RONDO 多出来的是 Team State 工具与可能的 Active World Index。但是在没有成员、Event、Version、route 或 Fact 时，
Team State 没有团队活动可投影，也不会自动建议任务拆分，更不会自动调用 spawn。

换句话说，Team State 的主要因果作用点在这条链的后半段：

```text
Root 判断值得拆分
  → Root 调用 spawn_agent
  → 成员实际工作
  → 成员 publish Event/Version/Fact
  → Root 被 wake、route、resolve、整合
  → 可能影响质量、时延、token 或失败恢复
```

Plan 049 卡在第一个箭头之前。实验原本希望通过“RONDO 可用 Team State”观察到后半段收益，但没有为第一次 spawn 增加一个
独立、强而公平的激活机制。这不是代码 bug；它正是产品坚持“语义决策仍由模型负责、不另建调度器”的结果。

因此，与其说“Team State 没能让 RONDO 主动委派”，更准确的是：“当前 Team State 设计并不负责让 Root 开始委派；在共同
软 policy 下，模型也没有自行开始委派。”

## 7. 失败原因的分层判断

下面按证据强度给出归因，便于后续 AI 不把所有猜测混在一起。

### 7.1 高置信度：激活机制与被测收益之间存在门槛错位

**判断**：强证据支持。

Team State 的设计目标是 post-spawn 协调一致性，而 activation gate 测的是 pre-spawn 的模型动作。源码没有 delegation
recommender、任务分解探针或自动 scheduler。RONDO 相对 Codex 的新增机制，在第一次 spawn 之前几乎没有状态信号可以影响
决策。于是“Team State 是否改善委派后协作”被“模型是否自然愿意第一次委派”完全挡住。

这解释了为什么即使 RONDO 产品实现正确，C 仍可能完全没有可比较样本。

### 7.2 高置信度：冻结 policy 有意允许零委派

**判断**：强证据支持。

policy 不是强制执行器，只是 developer instruction。它把是否委派留给模型，并特别禁止为展示协作而委派。零 spawn 与合同
相容。实验选择这种 policy 是为了测自然倾向，而不是保证观测到 collaboration；代价就是小样本可能完全不激活。

### 7.3 中等置信度：`medium` + Custom policy 可能不足以跨过模型的委派阈值

**判断**：合理假设，未被本实验直接证明。

源码表明 `medium` 默认会走 `ExplicitRequestOnly`，Plan 049 通过 Custom hint 覆盖它；内建 Proactive 默认只在 `ultra`
出现。虽然 policy 确实注入且 hash 正确，但 Custom 文本与内建 Proactive、不同 effort 或不同模型的行为响应强度是否相同，
本次没有对照。

不能据此断言 `medium` 不会主动委派；只能说当前六次观测没有委派，且没有 policy-strength/effort 消融来区分原因。

### 7.4 中等到较低置信度：pilot 任务可能没有给模型足够的并行收益信号

**判断**：待验证假设。

三个任务名称分别涉及 HTML 过滤、Git 仓库净化、数据库 WAL 恢复。它们并非显然不可拆，但模型可能认为主要关键路径需要连续
查看同一工作区、快速修改和验证，委派的沟通与整合成本高于收益。两题双方都失败也不能反推“本该委派”：失败可能来自任何
任务执行原因，而不是缺少协作。

仓库内跟踪的 Plan 049 catalog 冻结了任务身份、镜像、顺序和 digest，但没有在本报告可用的 body-free 证据中提供足以机械
判定“可并行子任务数量”的任务正文。因此，不能把“选题不够可拆”写成事实。

### 7.5 低置信度：RONDO 额外 Team 工具增加了选择负担，反而抑制 spawn

**判断**：理论上可能，当前没有证据。

RONDO 比 Codex 多八个 Team 工具，工具面更大，可能改变模型的工具选择分布；但两侧都是零 spawn，且没有工具面消融或多轮数据。
不能把这一点当作 RONDO 的负面结论。若未来要研究，必须单独比较“相同 policy 下仅改变 Team 工具可见性”，而不是从六个
阴性槽推断。

### 7.6 已被证据反驳：metric 漏计、Guardian 干扰、设施失败或预算停止

这些解释与 trace、attempt/accept 双计数、Root/Guardian selector、结算和 terminal 状态冲突，应从后续讨论中排除，
除非出现新的原始证据。

## 8. 任务 C 能得出与不能得出的产品结论

### 8.1 能得出的结论

1. 在 `gpt-5.6-terra`、`medium`、共同 Custom proactive policy 和固定三道 pilot 任务下，两侧 Root 六次都没有主动
   调用 `spawn_agent`。
2. RONDO 的 Team State“可用”本身没有在这六次运行中触发首次委派。
3. 当前测评设施能诚实处理有效 task failure、Guardian 双 bundle、恢复、费用结算和 activation 阴性停止。
4. 若继续把“自然主动委派”作为 Team State 收益测评的前置门，小样本存在完全无 post-delegation 数据的现实风险。

### 8.2 不能得出的结论

1. 不能说 Team State 对委派后的质量、时延、token 或成本没有收益；实验没有发生委派。
2. 不能说 Team State 有退化；三题两侧结果一致，也没有触发 Team State 主协作链。
3. 不能说 `gpt-5.6-terra` 一般不会主动委派；这里只有固定任务、policy、effort 和六次运行。
4. 不能说两道 task failure 是因为没有委派；没有反事实对照。
5. 不能说 pilot 任务不适合多智能体；任务可拆性没有被预注册或独立标注。
6. 不能把未运行的正式十题写成失败、skip 或“预算不足”；它们是 activation 阴性后的合同性不适用。
7. 不能把 M-5 中“明确协作指令可激活完整链路”外推成“自然软提示也应当激活”。两者 prompt 合同不同。

## 9. 对后续讨论最有价值的研究拆分

以下不是排期，只是为了让网页端 AI 与用户讨论时先选清问题，避免再把不同目标混为一个实验。

### 9.1 问题一：模型会不会自然主动委派

这是 **activation tendency** 问题。自变量可以是模型、effort、policy 强度、任务类型或可拆性；Team State 不一定是主要
自变量。若坚持自然行为，就必须接受零激活也是合法结果，并需要比三题更有针对性的预注册任务分层或更大样本。

需要讨论的选择：

- 测的是 `medium + Custom`，还是 `ultra + built-in Proactive`；
- 是否预先按“独立子任务数量、并行关键路径、共享工作区耦合”给任务分层；
- 是比较 activation rate，还是只要求建立少量可解释的 activated cohort；
- 是否允许一个不泄漏解法的轻量 delegation reminder；若允许，它已改变产品行为，不能再称纯自然基线。

### 9.2 问题二：一旦发生委派，Team State 有没有收益

这是 **conditional post-delegation benefit** 问题。它需要保证或筛选出真实委派样本，才能比较：

- 外部任务成功率或 reward；
- wall time 与峰值并发；
- token、inference、工具调用和费用；
- 重复工作、消息/等待、交接和失败恢复；
- RONDO 的 Event/Version/route/Fact 是否解释了整合过程。

若使用显式委派指令或固定最少一个 spawn，可以稳定观测 post-delegation 机制，但结论必须改名为“在明确委派条件下的协调
收益”，不能声称模型更愿意主动委派。也可以只分析自然运行中已经激活的 cohort，但必须预注册选择规则，避免只挑好看的轨迹。

### 9.3 问题三：RONDO 产品是否应该主动帮助第一次委派

当前产品边界明确：Team State 是共享世界状态，不是 scheduler。若希望产品本身提高 activation，需要新增不同类型的机制，
例如：

- 很轻的任务可拆性提醒；
- 只在检测到多个独立目标时显示 delegation suggestion；
- 在不自动执行的前提下给 Root 一个可忽略的委派候选；
- 更激进的 planner/scheduler。

这不是修复 Plan 049 暴露的“Team State bug”，而是改变产品职责的新决策。越靠后越可能提高激活，也越可能带来误委派、额外
token、提示干扰和复杂控制面。应先确认用户真正想优化的是“委派发生率”还是“委派后的协作质量”。

### 9.4 一个适合后续讨论的二维框架

网页端 AI 可以用下面的框架分析候选实验，而不是直接把 Plan 049 扩大重跑：

| | 自然/软 proactive | 明确或条件性 delegation |
|---|---|---|
| 无 Team State | 测 Codex 自然 activation | 测原生协作在已委派条件下的表现 |
| 有 Team State | 测 RONDO 自然 activation；预期第一次 spawn 的直接因果差异较弱 | 测 Team State 对 post-delegation 协调的真正增量 |

左列回答“愿不愿意委派”，右列回答“委派以后做得怎样”。Plan 049 只运行了左列上方和下方各三个 pilot，并因为两格都没有
spawn，未进入右列所代表的研究问题。

## 10. 对网页端 AI 的源码交接摘要

如果网页端 AI 只能记住十条，应记住以下内容：

1. RONDO 基于冻结 Codex CLI v0.147.0；原生 Multi-Agent V2 已有 spawn/message/wait 等控制面。
2. `AgentControl` 是每棵 Root tree 一个的共享控制对象，Team State 只是其中一个共享 handle。
3. 只有模型调用 `spawn_agent`，原生 handler 才会真正创建成员；Team State 没有自动 spawn 控制流。
4. Team State 用 Event/不可变 Version 表达团队语义检查点，用双 lifecycle 区分作者状态与 Root 协调状态。
5. route 把可见性、工作职责和通知投递拆开，适应异步部分失败。
6. Fact 是对实际保留 observation 的 typed reference，不是正文副本，也不是永恒真理。
7. Active World Index 每次采样从 canonical snapshot 重建；wake 只唤醒等待中的现有 Agent。
8. Team Lens 读取原生 trace，先生成 body-free `team_view.json`，静态 HTML 只消费这个合同；它不参与 runtime。
9. Plan 049 比较的是 `medium + 相同 Custom proactive policy`，不是 medium 默认，也不是 ultra 内建 Proactive。
10. 六个 pilot 两侧均零 spawn；因此工程实验成功、activation 结论阴性、Team State 收益问题未被回答。

## 11. 完成证据索引

### 11.1 状态与规划边界

- `doc/WBS.md`
- `doc/WBS/multi-agent-trusted-evidence.md`
- `doc/WBS-COMPLETED.md`

### 11.2 任务 A

- 合同：`plan/047-team-state-sequence-properties-execplan.md`
- 最终验收：`agent_log/2026-08-20-094034-plan047-final-acceptance-review.md`
- 主要源码：`multidev/codex-rs/team-state/src/sequence_properties_tests.rs`
- 主动入口：`multidev/justfile` 中的 `team-state-sequence-properties`
- 实现提交：`b0a8db079a642a5ea965b2ff789c5460359c5eff`
- 验收报告提交：`7eaa8f28ce7d9575ca65a4a793fe88b525b9cec6`

### 11.3 任务 B

- 合同：`plan/048-rondo-team-lens-execplan.md`
- 最终复验：`agent_log/2026-08-20-110755-plan048-team-lens-reacceptance-review.md`
- schema：`eval/rondo_eval/team_lens/model.py`
- reducer：`eval/rondo_eval/team_lens/reducer.py`
- 静态报告：`eval/rondo_eval/team_lens/report.py`
- CLI：`eval/rondo_eval/team_lens/__main__.py`
- 关键语义返修：`78736a7ec2c6d37fdad74ae30fdbf682e4801ec1`
- 最终报告提交：`7e8ef8ee80a492e0fcc49fe3467d5e75d5812505`

### 11.4 任务 C

- 合同：`plan/049-multi-proactive-delegation-eval-execplan.md`
- 冻结 lock：`eval/locks/multi-proactive-delegation-v1.json`
- 冻结 taskset：`eval/tasksets/multi-proactive-delegation-v1.json`
- 冻结 policy：`eval/templates/multi-proactive-delegation/proactive-policy-v1.md`
- 公平合同校验：`eval/rondo_eval/proactive_eval/contract.py`
- 确定性 schedule：`eval/rondo_eval/proactive_eval/schedule.py`
- 正式 runner/恢复：`eval/rondo_eval/proactive_eval/formal.py`、`paid.py`、`recovery.py`
- Root/Guardian selector：`eval/rondo_eval/proactive_eval/trace.py`
- activation 聚合：`eval/rondo_eval/proactive_eval/aggregate.py`
- 阶段 A 验收：`agent_log/2026-08-20-211938-plan049-phase-a-final-acceptance.md`
- 阶段 B 执行：`agent_log/2026-08-20-231500-plan049-phase-b-final.md`
- 阶段 B 独立验收：`agent_log/2026-08-20-233234-plan049-phase-b-final-independent-acceptance.md`
- 最终层次化结论：`agent_log/2026-08-21-002729-plan049-phase-b-final-acceptance.md`
- selector 提交：`fffb1f9`
- recovery identity 提交：`ebd77c7`
- 阶段 B 文档收口：`bb17291`
- 最终独立验收提交：`267825f61e7f7bb48dd2bcad67ca6f7a5de9faa1`

### 11.5 RONDO 产品源码

- Team State 总体合同：`multidev/codex-rs/team-state/src/lib.rs`
- domain object 与双 lifecycle：`multidev/codex-rs/team-state/src/model.rs`
- canonical mutation：`multidev/codex-rs/team-state/src/store.rs`
- mutex handle 与 wake：`multidev/codex-rs/team-state/src/handle.rs`、`wake.rs`
- Active World Index：`multidev/codex-rs/team-state/src/render.rs`、
  `multidev/codex-rs/core/src/team/projection.rs`
- Team 身份与启用门：`multidev/codex-rs/core/src/team/mod.rs`
- Root tree 共享控制面：`multidev/codex-rs/core/src/agent/control.rs`
- 真正的 spawn 路径：`multidev/codex-rs/core/src/tools/handlers/multi_agents_v2/spawn.rs`
- mailbox/Team wake 合流：`multidev/codex-rs/core/src/tools/handlers/multi_agents_v2/wait.rs`
- 原生与 Team 工具注册：`multidev/codex-rs/core/src/tools/spec_plan.rs`
- Multi mode 与提示：`multidev/codex-rs/protocol/src/config_types.rs`、
  `multidev/codex-rs/core/src/session/multi_agents.rs`、
  `multidev/codex-rs/core/src/context/multi_agent_mode_instructions.rs`

## 12. 最终结论

RONDO Multi 第二期已经完整收口：A 提高了 Team State 组合状态的正确性信心，B 提供了零 hook、body-free、确定性的真实团队
观测面，C 建成并实际运行了公平的主动委派 activation 测评。C 的工程质量不是失败点；其失败是研究目标在 pilot 阶段没有
获得任何 Root 委派样本。

从源码看，这个结果并不神秘。RONDO 当前产品把 Team State 放在“成员已经存在以后”的协调、证据和恢复链路上，第一次是否
spawn 仍完全由模型在软 policy 下作语义判断。六次运行里模型选择了单独工作，于是 Team State 没有真正进入可产生收益的
工作区间。

后续讨论不应围绕“怎样把这六个阴性 pilot 重跑成阳性”，而应先决定要研究哪一个问题：自然主动委派率、明确委派后的 Team
State 增量，还是让 RONDO 产品新增第一次委派建议能力。三者都合理，但属于不同合同、不同因果问题，也会得到不同类型的结论。
