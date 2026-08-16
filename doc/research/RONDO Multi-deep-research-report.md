# RONDO Multi 多智能体前沿资料调研：Research Dossier

**调研日期：2026-08-15，America/Los_Angeles。**  
**资料截止：截至调研当天可公开访问的一手资料。** 本次检索重点放在论文/预印本、官方研究与工程文章、官方文档、公开源码和正式 benchmark；厂商内部评测、产品宣称与公开学术实验分开标注。标题后的引文均可直接进入对应原始资料或源码页面。

## 调研口径与资料导航

这轮调研得到的资料并没有收敛到一种“标准 Multi-Agent 架构”。相反，当前前沿大致分成几条相互交叉、但假设差异很大的路线。

| 研究簇 | 代表资料/系统 | 核心关注 |
|---|---|---|
| **分层 orchestrator / worker** | Anthropic Research、Magentic-One、Google AI co-scientist、Codex subagents | 一个或少数协调者拆解任务、选择 worker、收集结果、重规划 |
| **大规模并行 / swarm** | Kimi Agent Swarm、Meta AutoformBot、Anthropic agent teams | 并发搜索、任务划分、吞吐、并行宽度、冲突管理 |
| **Harness 与 durable execution** | Anthropic Managed Agents、DeepSeek Harness、OpenAI Agents SDK/Codex | session、sandbox、agent loop、event log、恢复、fork、长期运行 |
| **共享状态 / artifact / workspace** | Anthropic filesystem artifacts、Git/worktree、Magentic-One ledgers、AgentScope MsgHub | 信息如何离开私有 context，如何被共享、引用、恢复 |
| **学习式 coordination** | Kimi PARL、Meta Collaborative Reasoner、若干 learned orchestrator 工作 | 不仅 prompt 一个协调协议，而是训练“何时并行、如何通信、如何分工” |
| **分布式共享状态一致性** | CoAgent、AgentScope distributed runtime | agent 同时修改文件、集群、文档时的 race、serializability、冲突恢复 |
| **长时程 agent** | Anthropic long-running harness、Managed Agents、OpenAI Codex 长时实验 | context reset/compaction、外部记忆、handoff、checkpoint、resume |
| **失败、scaling 与 eval** | MAST、HiddenBench、Silo-Bench、CooperBench、General AgentBench、Gaia2 | “多几个 Agent 是否真有帮助”、通信失败、verification gap、coordination tax |

值得首先注意的是，**“共享状态”在这些系统中实际上指四种不同东西**：执行历史的 durable log、面向 Agent 的工作记忆、Agent 间显式通信、以及外部世界中的共享可变资源。Anthropic Managed Agents 的 session log、Magentic-One 的 ledger、Git repository、DeepSeek Cordis 的 runtime context 都不应被当成同一种语义对象。citeturn15view0turn20search0turn15view1turn16search13

同样，所谓“大规模”也至少有四种不同口径：**同时活跃的 subagents、一次任务累计创建的 Agent/session、并行轨迹数、累计 tool calls**。Kimi 公开的是“最多同时若干 subagents”的产品能力；Meta AutoformBot 的“thousands of LLM agents”则是跨大型 formalization pipeline 的工作规模；Anthropic C compiler 的 16-agent team 最终经历接近 2,000 个 Claude Code sessions；这些数字不能直接横向比较。citeturn3search4turn19search0turn15view1

本报告采用以下证据标记：

**同行评审/正式发表**表示已进入正式学术发表渠道；**论文+源码**表示公开论文或预印本同时有可检查实现；**官方研究/工程**表示厂商正式技术文章、文档或源码；**官方自报**表示 benchmark、吞吐、agent 数量等主要由系统开发者自己测得；**公开线索**表示 issue、演示或间接材料，只用于提出问题而不当作确认事实。

## 头部机构与工业系统

### OpenAI：从 Swarm/Agents SDK 到 Codex 的 thread tree

OpenAI 2025 年发布 Agents SDK 时明确把它定位为构建 agentic applications、包括 multi-agent workflows 的官方 SDK，并将早期实验性 Swarm 的思路产品化。到 2026 年，SDK 又继续向更完整的 harness 演进，增加可配置 memory、sandbox-aware orchestration、filesystem-style primitives，并更明确地区分“模型 API”和“拥有 agent loop、handoff、session、tracing 的 SDK”。citeturn0search0turn13view1turn13view2

更直接与 RONDO Multi 相关的是**当前 Codex subagent 实现本身**。官方文档把 subagent 描述为独立 agent thread：主 agent 可以并行启动专门任务，并在结果返回后综合；其主要理由之一正是避免探索性工作、日志和中间结果污染主 context。OpenAI 同时明确警告，read-heavy 的独立任务更适合并行，而多个 agent 同时编辑同一区域代码时会出现冲突和 coordination overhead。citeturn13view0

本轮还实际检查了 Codex 开源树中的 `codex-rs/core/src/tools/handlers/multi_agents_spec.rs`。公开 tool schema 暴露出一些比产品文档更具体的控制面语义：`spawn_agent` 创建独立 thread identifier；旧版有 `fork_context`，新版对应更细的 `fork_turns`；父 agent 可以 `send_message`、触发 `followup_task`、等待、interrupt、close；`list_agents` 返回当前 root thread tree；新版描述还允许被 spawn 的 agent 再生成自己的 subagents，并形成 `/root/task/...` 式任务树。源码中的工具指导强调“concrete, bounded, independent sidecar work”，对写代码则建议 disjoint write sets。citeturn12search8

这意味着目前公开 Codex control plane 已经明显不是简单的“多个 prompt 并行”：它存在 **thread identity、父子树、context fork policy、agent messaging、turn boundary、lifecycle management**。不过，仅凭该 tool-spec 文件还不能断言 Codex 内部拥有某种统一 Team World State；公开代码更直接证明的是 execution/control primitives。citeturn12search8

Codex App 的另一条工程路线是**workspace isolation**。OpenAI 2026 年 2 月发布 Codex app 时描述了在同一项目下管理多个独立 agent thread，并使用内建 worktrees 给并行 coding agents 分配隔离 repo copy，从而减少编辑冲突。citeturn13view4

对于长时程，OpenAI 公开过一个约 25 小时连续运行、约 1,300 万 tokens、约 3 万行代码的 GPT-5.3-Codex 实验；官方明确把它描述为实验而不是一般生产可靠性证明。OpenAI 内部使用数据还显示，到 2026 年 6 月，其最高使用分位的员工已经会把大量工作时间分布到并行 Codex agent turns 上，但这属于 usage telemetry，不是多智能体 benchmark。citeturn13view3turn13view5

**证据等级：官方源码 + 官方工程文档。**  
**RONDO 相关标记：**这里最值得单独研究的是 thread tree、fork semantics、消息/turn 边界、worktree isolation 与 Root 可见的 agent lifecycle；这些是实际存在于 Codex control plane 的机制，而不是为 RONDO 寻找的概念类比。citeturn12search8turn13view0

### Anthropic：目前公开材料中最完整的“多 Agent + 长时程 Harness”演化链

Anthropic 的公开路线非常连续。

其 2025 年 Research 系统采用 **lead agent + parallel subagents**：lead agent 规划研究，把不同方向交给拥有独立 context window 的 subagents，再汇总返回结果。Anthropic 的内部 eval 中，Opus 4 lead + Sonnet 4 subagents 相比单一 Opus 4 提升 90.2%；但团队同时发现，token usage 是性能方差的主要解释变量之一，多 Agent 版本约使用普通 chat 的 15 倍 tokens、agentic system 的约 4 倍，因此不能把增益简单归因于“社会性协作”。citeturn11view0turn14search11

这里最有价值的反面结果同样来自 Anthropic 自己：简单问题曾出现一次 spawn 约 50 个 subagents；有 agent 会不停寻找不存在的来源；过于频繁的 coordinator status update 会浪费 context；当任务存在强依赖、所有 Agent 都必须共享同一上下文、或者多方同时修改同一个 artifact 时，并行收益显著下降。Anthropic 因此把 subtask description、scope、expected output 写得非常具体。citeturn11view1turn11view2

研究系统里还有一个很值得注意但经常被忽略的工程选择：**大量结果不经过 coordinator 重新转述，而让 subagent 把大型 artifact 写入 filesystem，并向 coordinator 返回轻量引用。** Anthropic 明确把这用于减少“game of telephone”、信息损失和 token overhead。也就是说，它区分了“用于协调的短消息”和“承载完整内容的共享 artifact”。citeturn11view3

该系统也不是纯 prompt demo。Anthropic 描述了 production tracing、checkpoint、retry、resume；并指出当时同步等待 subagent 是瓶颈，转向 asynchronous subagents 会进一步引入 **state consistency、error propagation、coordination** 问题。citeturn14search11turn11view2

随后 Anthropic 对 long-running harness 的研究更进一步。2025 年的 *Effective harnesses for long-running agents* 发现，仅靠 compaction 并不能让长任务稳定持续：agent 会一次做太多，context 中断在半成品状态，下一 session 不知道发生了什么；或者看到已有大量进展后过早宣布完成。其方案是 initializer agent 建环境、维护 `claude-progress.txt`、git commit 等 artifacts，后续 coding session 每次只做增量工作并留下结构化 handoff。citeturn15view3

2026 年 3 月的后续工作进一步报告了 “context anxiety”：部分模型接近自认为的 context limit 时会提前收尾。Anthropic 用完整 context reset + structured handoff 解决过这一问题；但又观察到随着模型变化，此类 harness assumption 可能迅速过时。与此同时，其三 Agent planner/generator/evaluator 结构把“执行者自己评价自己”视作独立失败模式，因为 generator 对自己输出往往过度宽容。citeturn15view2turn15view0

2026 年 2 月 Nicholas Carlini 的 C compiler 实验则走了一条与 central orchestrator 几乎相反的路线：16 个 Claude agent 在共享 Git 项目上工作，最终经历接近 2,000 个 Claude Code sessions，成本约 2 万美元，产出约 10 万行 Rust compiler，可编译 Linux 6.9，并在多个 compiler test suite 上表现很高。这个实验**没有高层 orchestrator，也没有直接 agent-agent messaging**；task ownership 只是 `current_tasks/` 里的 lock file，Agent 各自在 Docker 中 clone、修改、pull、merge、push。作者明确报告 merge conflict 很常见。citeturn15view1

这个实验的重要性不在 compiler benchmark 本身，而在于它证明了一条截然不同的协作路线也能扩大任务 horizon：**共享 repo + task locks + tests + persistent documentation + repeated fresh agents**，而不是把大量语义状态维护在一个中央聊天线程里。与此同时，它高度依赖强测试 oracle；作者明确说 verifier 如果不可靠，Agent 会非常有效地优化错误目标。citeturn15view1

到 2026 年 4 月，Anthropic 又发布了 Managed Agents，把 agent 系统拆成三个相对稳定的接口：

> **session**：发生过的一切的 append-only log；  
> **harness**：调用模型并路由 tool calls 的 loop；  
> **sandbox**：运行代码和修改文件的执行环境。citeturn15view0

其中最值得关注的是一句工程上的区分：**“the session is not Claude's context window.”** session log 在 harness 外 durable 存储，harness crash 后可以 `wake(sessionId)`、`getSession()`、从最后事件继续；模型 context 只是根据需要从 `getEvents()` 取 event-stream slices，再由当前 harness 做任意 compaction/transform。Anthropic的理由是：不能预先知道未来模型需要什么 context-engineering policy，所以尽量把可恢复历史和暂时输入 context 分离。citeturn15view0

Managed Agents 同时把“brain”与“hands”拆开：harness 不住在 sandbox 里，sandbox 只是一种 `execute(name,input)` 工具；多个 stateless harness 可以连接不同执行环境。Anthropic 报告这种架构使其 p50 TTFT 下降约 60%，p95 下降超过 90%，但这些是官方系统内部数据。citeturn15view0

**证据等级：官方工程、官方内部 eval、公开实验代码/成果。**  
**RONDO 相关标记：**Anthropic 这组资料特别适合拿来区分 **private context、durable history、semantic handoff、artifact、shared mutable workspace**；它们在 Anthropic 系统中不是一个东西。citeturn15view0turn11view3

### Microsoft：从 AutoGen conversation 到 Magentic ledger，再到显式 workflow

Magentic-One 是目前最清晰的“Root/orchestrator 有显式工作状态”的公开体系之一。Orchestrator 维护两类状态：开始任务时形成包含计划、已知 facts 和 educated guesses 的 **Task Ledger**；执行过程中反复生成 **Progress Ledger**，检查是否已完成、是否取得进展、下一步应该由哪个 agent 执行。连续若干步没有进展时，Orchestrator 会回到外层 loop 更新 Task Ledger 并重规划。citeturn20search0turn20search1

原始 Magentic-One 由 Orchestrator 协调 Coder、ComputerTerminal、WebSurfer、FileSurfer 等 specialized agents，在 GAIA、AssistantBench、WebArena 上达到与当时 state of the art 统计上竞争的结果；论文还发布了 AutoGenBench 以重复、隔离地运行有 side effects 的 agent benchmark。citeturn20search5

值得注意的是，Ledger 在这里主要是**协调器维护的认知/进度状态**，并不等于所有 Agent 共享的一致世界数据库。源码中 `MagenticOneGroupChat`/orchestrator 对这套 dual-loop ledger 有直接实现。citeturn20search15

这一路线后来被纳入 Microsoft Agent Framework。到 2026 年，Microsoft 将 Agent Framework 定义为 AutoGen 与 Semantic Kernel 的直接后继，增加 session-based state、graph-based workflows、long-running/HITL state management，并正式提供 Sequential、Concurrent、Handoff、Group Chat、Magentic 等不同 orchestration primitive，而不是强迫所有系统采用同一拓扑。citeturn20search2turn20search6

这也展示了一条很明显的工业演进：

**AutoGen 的自由 conversation abstraction → Magentic-One 的动态 manager/ledger → Agent Framework 中显式可编排的 workflow/state runtime。** citeturn20search16turn20search24

公开 issue 也暴露过很现实的问题，例如 Progress Ledger 的 JSON 格式对模型输出格式敏感、HITL handoff 后状态恢复曾出现上下文丢失等。这些 issue 不足以判断系统整体可靠性，但说明 orchestration state 本身是工程故障面，而不是纯 prompt 层能力。citeturn20search7turn20search19

**证据等级：论文/官方源码 + 官方框架文档；issue 仅作工程线索。**  
**RONDO 相关标记：**Magentic-One 很适合研究“协调器自己维护的工作状态”与“Agent 真实执行产物”之间的边界，并可作为一种与 Team World State 很不同的比较对象。citeturn20search0

### Google / DeepMind：scientist team 与 Agent interoperability

Google 的 AI co-scientist 是研究型 multi-agent 的重要代表。系统由 Gemini 驱动，Supervisor 根据科学目标组织研究，并调用 Generation、Reflection、Ranking、Evolution、Proximity、Meta-review 等 specialized agents；其设计不是固定一次流水线，而包含产生候选、互相评议、演化和 tournament-like ranking 的迭代过程。citeturn21search0

其价值在于展示了与 coding swarm 不同的 coordination objective：不是主要消灭工程依赖，而是让不同角色对 **hypothesis space** 持续生成、批判、比较、演化。因而这里的“共享状态”更接近候选 hypothesis/proposal pool，而不是 repo/file state。Google 的公开证据包括官方研究文章及研究论文，但很多具体效果仍来自作者自己的科学案例与内部评测，需要与独立重复验证分开看待。citeturn21search0

Google 的另一条路线是 **A2A（Agent2Agent）协议**。A2A 不是新的 reasoning topology，而是把“一个 Agent 系统作为另一个 Agent 系统可调用的远程参与者”标准化，特别面向内部实现保持 opaque 的 agentic applications；Google 后续把它与 ADK 集成，并将协议贡献到 Linux Foundation 生态。citeturn5search14turn5search10turn5search2

**证据等级：官方研究 + 官方协议/源码。**  
**RONDO 相关标记：**AI co-scientist 是“显式角色和竞争/演化”的异质路线；A2A 则值得作为 agent boundary、remote identity 与 artifact/task interoperability 的邻接资料，而不是内部 Team coordination 的现成答案。citeturn21search0turn5search14

### Meta：从“训练合作行为”到 thousands-agent formalization

Meta 的 Collaborative Reasoner/Coral 路线很值得保留，因为它不把 coordination 完全视为 harness prompt 问题。Meta 报告现成 LLM 并不能稳定利用协作，social post-training 甚至可能产生不理想互动，因此提出 Matrix 环境与 synthetic multi-agent conversations，让模型学习 collaborative behavior；其公开实验中，相比等价 single-agent CoT，部分任务最高提升 29.4%。这仍属于作者体系内评测，但研究问题本身与“增加 agent 数”明显不同：**能否训练出更好的协作 policy？** citeturn6search0

Meta Agents Research Environments / Gaia2 则更接近 eval infrastructure。Gaia2 强调 asynchronous events、环境歧义、噪声、协作和 temporal constraints。Meta 报告没有一种 system 在所有场景占优，增强 reasoning 往往同时增加效率成本，而且随着预算增加，性能曲线会出现 plateau。citeturn6search2

Meta 的 AIRA₂ 又把并行引入 research-agent optimization：它使用 asynchronous multi-GPU worker pool 扩大实验吞吐，并对研究 agent 在多轮实验、评估和改进上的表现做长时运行；官方报告在 MLE-Bench-30 上 24h/72h 的 mean percentile 分别达到 81.5% 和 83.1%，同时 ablation 表明多个组件都重要。它更接近“并行 experiment workers + learning/research loop”，而不是聊天式团队。citeturn6search10

本轮检索中一个尤其值得 RONDO 后续精读的最新结果是 **AutoformBot / Formalizing Mathematics at Scale**。Meta FAIR 等机构在 2026 年发布的 AutoformBot **明确称其 orchestrate thousands of LLM agents**，用于把 26 本数学教材自动 formalize 到 Lean 4；系统结合 formal verification tools、dependency-aware scheduling 与 collaborative version control，并公开源码。最终 ATLAS 公开了超过 45,000 个 Lean declarations、约 50 万行 Lean 代码规模。citeturn19search0turn19search8

这并不意味着“数千 Agent 同时对一个任务聊天”。其规模来自大型 DAG/pipeline 在 cluster 上调度大量 agent workers。公开 config 支持 `agents_per_node`、replicas、每个 task 的最少/最多 agents，并支持 SLURM multi-node execution。源码目录把 multi-agent orchestrator/workers/reviewers 放在 `autoform/bot/`，基础 agent/inference/trace/coordination 放在 `core/`，工具则经 MCP 暴露。citeturn19search1turn19search3

它的共享事实层也很特别：Lean compiler/proof checker 是强 external verifier，dependency graph 是机器检查的 DAG，Git 是 collaborative version control。换言之，很多团队状态并不依赖 Agent 相互相信自然语言消息，而有外部形式系统裁决。citeturn19search6

**证据等级：论文+完整公开源码；规模数字来自作者论文/仓库。**  
**RONDO 相关标记：**AutoformBot 是当前公开资料中很罕见的“真正上千 agent-scale 调度 + shared repository + hard verifier + dependency scheduling”实例；但其 task structure 比开放世界 coding/research 要规整得多。citeturn19search0

### Alibaba / Qwen / AgentScope：Actor-style distributed MAS

在 Alibaba/Qwen 相关公开生态中，本轮找到的**multi-agent 系统层资料最扎实的是 AgentScope，而不是 Qwen-Agent 本身**。Qwen-Agent 公开框架主要围绕 tool use、planning、memory 和 Qwen 模型调用；AgentScope 则从一开始就把 message exchange 和 distributed multi-agent execution 作为核心。citeturn7search0turn7search17

AgentScope 原始工作采用 actor-based distributed framework，为本地/分布式 Agent 提供自动并行优化、消息交互、fault tolerance 等机制；后续 *Very Large-Scale Multi-Agent Simulation in AgentScope* 专门研究大规模 multi-agent simulation 与跨设备并行。citeturn7search17turn7academia36

AgentScope 1.0 又进一步把 **MsgHub** 用于消息交换，把 **Pipeline** 用作 multi-agent flow orchestration。它的价值与 Magentic-One 不同：前者更像通信/runtime substrate，后者更像具有特定认知策略的 orchestrator。citeturn7search1turn7search5

**证据等级：官方预印本 + 开源项目。**  
**RONDO 相关标记：**若下一轮要研究“消息总线是否应成为 Agent 控制面的一级对象”“actor mailbox 与 Agent private thread 怎样映射”，AgentScope 比单纯 Qwen 模型能力更值得直接读源码。citeturn7search17

### DeepSeek：非常新的 Harness/Cordis 路线

截至本次调研日期，**DeepSeek Harness 是这轮搜索里时间上最新、而且最值得立即加入资料库的工程项目之一**。它目前明确处于 developer preview，并警告会有 breaking changes。citeturn16search0turn16search3

其核心主张不是某个固定 multi-agent topology，而是：

> **Everything is a plugin.** Models、tools、skills、sessions、sandboxes、storage、loops、scheduling、UI 都是可替换插件。citeturn16search1

官方 architecture 文档甚至明确写道：model adapter、tool registry、session log 和 **agent loop 本身**都是插件；没有需要 patch 的 privileged core，插件通过 Cordis 的 services、typed events 和 reversible effects 接入 shared runtime context。citeturn16search13turn16search7

更值得关注的是其 trace model。DeepSeek Harness 官方说明，**模型看到的一切**会记录到 append-only session log，包括 system prompts、reasoning、tool calls/results、subagent scheduling 和 context injection；Trajectory view、resume、fork、search、replay 都建立在同一 event stream 上。citeturn16search1

这里有两个容易和 RONDO 的术语混淆、但实际不同的概念：

第一，Cordis 的 **event** 是 runtime/plugin event。它有 typed `emit`、`parallel`、`serial`、`waterfall` 等 dispatch semantics，用于插件之间观察、包装、并行或顺序执行。citeturn16search7turn16search8

第二，Harness 的 **session event stream** 才更接近 durable execution history。它记录 Agent 实际看到了什么和发生了什么，而 Cordis `ctx` 则主要是 service/dependency container，并非“团队语义事实数据库”。citeturn16search1turn16search5

Cordis 自身公开为独立 meta-framework，并把“reversible effects + reactive dependency composition”作为核心；DeepSeek Harness vendored Cordis 实现，目前两边 API 都处于快速演化阶段。citeturn18search0turn16search7

**证据等级：官方源码与官方工程文档，极新、尚无成熟独立 benchmark。**  
**RONDO 相关标记：**这是目前最值得拿去直接和冻结 Codex harness source 做“实现层 diff”的公开项目之一，尤其是 session log、subagent scheduling trace、plugin boundaries、reversible runtime effects；但不能因为词汇相似就把 Cordis event 当成 RONDO Team Event。citeturn16search1turn16search13

## 学术研究簇与代表工作

工业系统很容易形成“Agent 越多越强”的印象；近一年学术资料反而越来越集中在**什么时候 multi-agent 才真的产生增益、协调本身需要哪些能力、以及能否学习 orchestration**。

### 分布式信息整合，而不仅是“发消息”

*HiddenBench: Systematic Failures in Collective Reasoning under Distributed Information* 构造了 65 个 hidden-profile tasks，在 15 个 frontier LLM 上专门隔离“每个 Agent 只知道部分事实，但把信息合起来即可求解”的能力。结果非常尖锐：分布信息下的 multi-agent accuracy 仅 **30.1%**，而单 Agent 拿到完整信息时为 **80.7%**。失败不是 Agent 完全无法理解已经收到的信息，而是它们经常不知道“别人可能知道自己不知道的东西”，因此会在共享证据上过早收敛。问题在不同 prompt、通信深度和 group size 下持续存在，并会随着 group 增大而恶化。citeturn22search2turn22search4

这项工作的意义在于区分了两件事：

**message delivery 成功 ≠ collective epistemic state 成功。** Agent 可以把消息全发出去，却仍可能没有主动暴露、索取或整合关键的 unique information。citeturn22search4

*Silo-Bench* 从算法任务角度得到相似结果。它覆盖 30 个任务、3 个 communication-complexity levels、54 种配置、1,620 次实验。作者称之为 **Communication-Reasoning Gap**：Agent 会自发形成看起来合理的 coordination topology，也会积极交换信息，但最终经常无法把已获得的 distributed state 合成正确答案；随着规模上升，coordination overhead 最终可以吃掉并行带来的收益。citeturn23search2turn23search4

对于任何 shared-state 设计，这两篇都比传统“多 Agent 比单 Agent accuracy 高多少”更值得读，因为它们直接问：**信息存在、可达、已发送之后，团队到底能不能正确地使用它？** citeturn22search4turn23search4

### Agent 数量的 scaling 不是单调函数

2026 年的一系列 controlled scaling 工作开始系统反驳“agent count 是天然 test-time compute”的简单假设。

*General AgentBench* 对 10 个 leading LLM agents 研究 sequential 与 parallel test-time scaling：顺序增加 trajectory length 会遇到 **context ceiling**；并行采样大量 trajectories 时虽然 candidate space 变好，却遭遇 **verification gap**——系统并不能可靠选出正确 trajectory，因此并行生成的潜在增益无法完全兑现。作者还发现从 domain-specific benchmark 转到统一 general-agent setting 后，多类系统出现显著性能下降。citeturn23search1turn23search3

*Scaling Behavior of Single LLM-Driven Multi-Agent Systems* 等工作进一步观察到，随着同质 Agent 数量增加，synergy 与 coordination cost 之间会产生非单调 trade-off；另一项 agent-scaling 研究同样报告简单增加 homogeneous agents 很快出现 diminishing returns，heterogeneity 可以推迟但不能自动消除 saturation。citeturn10view1turn9search5

因此，当前更精确的研究问题已经从：

> “多少 Agent 最好？”

转向：

> “在什么 task dependency、information topology、verifier quality、communication cost 和 model heterogeneity 下，额外 trajectory/worker 的边际价值为正？” citeturn23search3turn23search4

### 软件工程协作与“curse of coordination”

2026 年的 *CooperBench: Why Coding Agents Cannot be Your Teammates Yet* 很值得 RONDO 精读。它收集 600 多个 collaborative coding tasks，故意给两个 Agent 分配可独立完成、但合并时可能产生冲突的 feature。作者发现 state-of-the-art coding agents **合作时平均 success rate 比单独完成两个任务低约 30%**，称之为 “curse of coordination”。citeturn23academia19

错误分析主要落在三处：消息 vague / ill-timed / inaccurate；即使已经达成合理 communication，Agent 后续也会违反自己的 commitment；Agent 对对方计划与沟通状态存在错误预期。与此同时，实验中偶尔也会涌现 role division、resource division、negotiation。citeturn23academia19

这和 Anthropic C compiler 的实践形成很有价值的对照：后者没有追求丰富聊天协议，而大量依赖 **task lock、Git merge、tests 和 persistent docs**。二者不能直接比较 benchmark，但至少说明“让两个 coding agents 多交流”本身并不是自动减少冲突的充分条件。citeturn23academia19turn15view1

### 把数据库并发控制重新引入 Agent 系统

*CoAgent: Concurrency Control for Multi-Agent Systems* 是本轮最重要的相邻计算机科学资料之一。其出发点很直接：两个 agent 同时修改 Git tree、Kubernetes cluster 或 document，已经进入经典 database concurrency-control 问题，但 agent transaction 持续数分钟、read set 模糊、外部 side effect 往往不能像数据库 transaction 一样缓冲。citeturn23academia17

作者提出 MTPO：启动时固定 serialization order；read 返回按顺序过滤的值；write 可以 speculative 地立即执行；如果后来出现冲突，runtime 通知受到影响的 Agent，由 Agent 判断计划是否失效并局部修补，同时 tool 为可机械 undo 的 effect 注册 saga-style inverse。citeturn23academia17

在作者的 10 个 contended workloads 上，CoAgent 声称 correctness 距 serial execution 5% 以内，同时约 1.4× speedup；而 2PL/OCC 在这种长 agent transaction 下几乎失去并发优势。另一个 bash-only 场景中，系统在线生成 25 个 undoable tools，将 pass rate 从 45/71 提高到 63/71。这些仍是预印本作者自报实验，但问题定义非常重要。citeturn23academia17

**RONDO 相关标记：**CoAgent 讨论的是 **actual mutable world state 的 serializability**，不是语言层“谁相信什么”；这是与 Team World State 完全不同、却未来很可能必须共存的一层。

### 学习 coordination，而非固定 prompt workflow

Moonshot 的 PARL 和 Meta Collaborative Reasoner 都说明一个正在增强的方向：**coordination policy 本身可能成为训练对象。** Kimi 官方称 PARL 会奖励 agent swarm 形成更好的并行 decomposition，随着 RL compute 增加，平均 parallelism 和 reward 同时上升；Meta 则通过 synthetic collaboration episodes 训练更强合作行为。两者的训练细节和开放程度差异很大，但共同点是“不认为 orchestration 只需要手工写 prompt”。citeturn2search4turn6search0

学术界也开始把 spawn/delegate/message/tool/return/aggregate/stop 表述为可学习的 orchestration trajectory，并研究 learned conductor 或 multi-agent RL；当前证据仍分散，而且 shared-policy、isolated-policy 等训练方法存在稳定性问题。citeturn9search3turn9search15turn9search33

这里暂时没有形成统一赢家，反而应把“固定 protocol”和“learned protocol”都保留在下一轮资料树中。

## 负面结果、失败模式与扩展边界

这部分是本轮最不适合省略的材料。

### MAST：目前最系统的 multi-agent failure taxonomy

*Why Do Multi-Agent LLM Systems Fail?* 对 5 种常见 MAS framework、150+ tasks/约 200 execution traces 做人工 failure analysis，6 位 expert annotators 参与，最终形成 14 个 failure modes，inter-annotator Cohen’s κ 为 0.88。作者把问题分成三大类：**specification/system design、inter-agent misalignment、task verification/termination**。citeturn22search1turn22search5turn22search7

更重要的是作者实际试了两个看起来很自然的干预——把 agent role 写得更清楚、增强 orchestration strategy——但并没有简单消除这些 failure，说明许多问题不是“prompt 再详细一点”即可解决。citeturn22search1

对于 RONDO，MAST 的价值不是告诉你采用哪个 topology，而是给 future tracing/eval 提供现成 failure vocabulary，例如 task allocation 不合理、agents 对 task state 理解不一致、重复工作、错误终止、verification failure 等。citeturn22search7

### 分布式事实越多，团队可能越早达成错误共识

HiddenBench 的结果尤其值得反直觉地保留：group size 增加并未消除 knowledge asymmetry，反而会让问题恶化。Agent 通常能理解已经被明确 disclosure 的关键事实，但不会主动推断“还有没有未披露的信息”。citeturn22search4

这意味着一个系统即使有完美的 mailbox、broadcast、Team Event，也可能仍然失败，因为 failure 出在 **epistemic policy**：什么值得主动告诉别人、什么时候应该问别人、什么时候不该认为 evidence 已足够。citeturn22search4

这点恰好不能靠“消息传输可靠”来证明解决。

### 通信越丰富，不一定越协作

Silo-Bench 与 CooperBench 都指出 communication itself 会引入 overhead。前者发现 agents 经常已经取得足够信息却无法集成；后者发现自然语言 channel 会被模糊、时机错误和不准确消息占据。citeturn23search4turn23academia19

Anthropic 的生产经验也类似：研究 subagents 把大型 artifact 直接写 filesystem，而不是让 coordinator 反复转述，就是主动降低 communication surface。citeturn11view3

因此，有必要把“消息数量”“有效信息”“共享 artifact”“shared semantic state”分别度量，而不是把 communication volume 当作 cooperation proxy。这是从多组一手资料得到的综合推论。citeturn23academia19turn23search4turn11view3

### 写共享 workspace 是一个独立 scaling bottleneck

OpenAI Codex 当前文档明确说 read-heavy independent work 更容易并行，write-heavy parallel work 更容易产生 merge conflict 与 coordination overhead。Anthropic 16-Agent compiler 也明确报告 frequent merge conflicts。CooperBench 则把这件事变成可重复 benchmark。citeturn13view0turn15view1turn23academia19

所以“Agent scale”至少应该分成：

**parallel readers/searchers** 与 **parallel writers/actors**。

这两种 scaling regime 不应共享一条经验曲线。该区分是综合上述系统材料得到的工程推论。citeturn13view0turn23academia17

### Verification 本身可能成为 parallel scaling 的瓶颈

General AgentBench 的 parallel scaling 结果非常重要：采样更多 candidate trajectories 有潜力增加正确答案出现概率，但系统无法可靠识别正确 candidate，形成 verification gap。citeturn23search3

Anthropic 在 long-running coding 里也从另一个角度遇到同样问题：Agent 对自己作品评价偏正，因此把 evaluator 与 generator 拆开；而 C compiler 实验几乎把强 test harness 当作系统核心。citeturn15view2turn15view1

但这里也不能反过来得出“永远需要 reviewer Agent”。在 Lean/AutoformBot 这样的领域，formal proof checker 可以承担强 oracle；在 open-ended research 中却不存在同等级验证器。citeturn19search6turn21search0

### 模型升级会让 Harness workaround 失效

Anthropic Managed Agents 报告了一个很值得长期 Harness 项目警惕的例子：针对 Sonnet 4.5 “context anxiety” 增加的 context resets，到更强模型上可能已经变成 dead weight。因此其 Managed Agents 反而追求 session/harness/sandbox 的稳定 interface，而允许 harness policy 随模型迭代更换。citeturn15view0

这是一种重要的 negative engineering lesson：**当前模型缺陷并不一定应该固化为永久 control-plane invariant。** 这是 Anthropic 明确提出的设计动机，而不是 RONDO 的架构结论。citeturn15view0

### Multi-agent 同时扩大了安全边界

Multi-agent framework 还增加新的攻击传播面。已有工作针对 AutoGen/Magentic-One、Selector、Round-Robin、CrewAI、MetaGPT 等框架研究来自不可信 web/file input 的攻击，并展示了 multi-agent workflow 中执行恶意代码的风险。citeturn20search25

Anthropic Managed Agents 也把 credentials 与执行 sandbox 物理分离视为结构性安全要求：agent-generated code 所在 sandbox 不应该能够读到 OAuth/API credentials；MCP credential 在 sandbox 外的 vault/proxy 中处理。citeturn15view0

因此，当 Agent 可以 spawn Agent、把工具权限传递给子 Agent 或修改共享环境时，**delegation graph 同时也是 authority graph**。这是一条从公开安全资料可以直接导出的研究方向。citeturn15view0turn20search25

## 长时程、共享状态与相邻系统思想

从 RONDO 背景出发，最有价值的不是找到某个“Team World State 同款”，而是把目前系统中的状态层分清楚。

| 状态/通信层 | 公开实例 | 实际语义 | 已知问题 |
|---|---|---|---|
| **Agent private thread/context** | Codex subagents | 独立 thread，可选择 fork 部分/全部 parent turns | context rot；fork 太多会复制噪声 |
| **Durable execution history** | Anthropic Managed Agents session、DeepSeek session log | append-only 历史，支持 resume/fork/replay | 原始历史太大，仍需 context selection |
| **Coordinator working memory** | Magentic-One Task/Progress Ledger | plan、facts/guesses、progress、replanning | coordinator 可能错误，格式本身也可能故障 |
| **Semantic handoff** | Anthropic progress files/context-reset artifacts | 跨 session 保存“下一 Agent 应知道什么” | 是 lossy interpretation，可能遗漏未来重要信息 |
| **Large shared artifact** | filesystem、Git repository、Lean code | 完整内容不必进入所有 context | 并行写冲突、staleness、merge |
| **Message bus/mailbox** | Codex send_message、AgentScope MsgHub | Agent 之间的 explicit communication | 发到了不等于被正确理解/使用 |
| **Shared mutable world** | Git、Kubernetes、documents | Agent 实际修改的外部状态 | race、non-serializable execution |
| **Runtime service context** | DeepSeek Cordis `ctx` | plugin/service dependency container | 与 semantic world knowledge 是不同层 |
| **Verified state** | Lean proof graph、tests | 外部 verifier 可机器判定的结果 | 很多现实任务没有这样的 oracle |

这些区分分别有 OpenAI、Anthropic、Microsoft、DeepSeek、AgentScope、Meta AutoformBot 和 CoAgent 的一手实现或实验支持。citeturn12search8turn15view0turn20search0turn16search5turn7search1turn19search6turn23academia17

### Durable log 与 semantic memory 是两类对象

Anthropic Managed Agents 是目前公开资料里最明确地强调这一点的系统：session 是 recoverable event history，模型当前 context 则是 harness 从 event log 选择、转换后产生的视图。citeturn15view0

DeepSeek Harness 的 append-only session log 又提供另一个实现实例：reasoning、tool call/result、subagent scheduling、context injection 都可以追踪；但这并不表示这些记录被自动宣告成“事实”。citeturn16search1

这两个系统共同证明了一种工程上已经存在的模式：

**保存“发生过什么”与决定“当前 Agent 应相信/看到什么”可以解耦。** 这是资料观察，不是对 RONDO 的规范性建议。citeturn15view0turn16search1

### Git 正在成为事实上的 Agent coordination substrate

Codex worktrees、Anthropic compiler、long-running Claude harness、Meta AutoformBot 都把 Git 当作远不止“代码保存”的东西：它提供 isolation、version、merge、history、handoff、shared artifact 与某种粗粒度 serialization。citeturn13view4turn15view1turn15view3turn19search1

但 CoAgent 表明 Git-style merge 本身不能解决任意 shared-world concurrency；当 side effect 是 Kubernetes、database、remote service 或无法 fork 的环境时，需要进一步研究 locks、OCC、sagas、compensation 与 agent-aware conflict repair。citeturn23academia17

### Actor/message-passing 与共享内存仍是两条不同路线

AgentScope 的 actor-based distributed execution 更接近传统 actor system：私有 Actor/Agent state 加 message exchange；CoAgent 则正面面对 multiple agents 对 shared mutable state 的并发访问。citeturn7search17turn23academia17

这对应一个值得保留的相邻 CS 问题：到底哪些信息应通过 **message passing** 传播，哪些资源必须由 **shared-state concurrency control** 保护。当前 LLM MAS 文献经常把两者都叫“coordination”，但经典 distributed systems 并不会这样合并。citeturn23academia17turn7academia36

### Event sourcing、replay 与可观察性正在成为 Harness 一级能力

Anthropic 把 session 设计成 append-only event log；DeepSeek 把 resume/fork/search/replay 放在同一 trajectory stream 上；OpenAI Agents SDK 则把 tracing/session 作为 SDK primitive。citeturn15view0turn16search1turn13view2

这类设施不仅用于 debugging。对于长期 Agent，crash 后能否恢复、某条 semantic conclusion 能否追溯到具体 tool result、某 subagent 到底看到哪版 context，都依赖这些 execution-level records。公开系统正在明显把 observability 从“日志”提升为 agent runtime primitive。citeturn15view0turn16search1

### Runtime 的可替换性正在被单独研究

DeepSeek Cordis 的 reversible effects、plugin dependency lifecycle，与 Anthropic “harness assumptions go stale” 的 Managed Agents 有一个有趣交集：两者都不希望具体 agent loop policy 变成永远不可替换的 core。citeturn16search13turn15view0

但实现哲学明显不同：Anthropic 倾向在托管基础设施上稳定 session/harness/sandbox interface；DeepSeek Harness 则把 agent loop 本身都降为可 hot-compose 的 plugin。citeturn15view0turn16search13

这是本轮特别值得保留的**架构分歧**，不应强行归纳成行业共识。

## Moonshot / Kimi “约二百 Agent”专项核验

先给核验结论：

**截至 2026-08-15，本轮没有找到 Moonshot/Kimi 一手资料确认“某系统上限约为 200 个并行 Agent”。能够确认的一手数字是：K2.5/早期 Agent Swarm 为最多 100 个 subagents；K2.6 之后的当前公开能力为最多 300 个 subagents 同时工作。** citeturn10view6turn2search4turn3search4

“200”非常可能来自几个相邻数字的混淆，但这只能标为推断。

### 可以确认的时间线

| 时间 | 一手资料 | 能确认什么 | 证据性质 |
|---|---|---|---|
| 2026-01-27 | Kimi K2.5 官方发布 | Agent Swarm 最多 **100 sub-agents**；最多约 1,500 tool calls；官方称相对 sequential execution 最多约 4.5× wall-time speedup；引入 PARL | 官方产品/研究自报 citeturn2search4 |
| 2026-02-09 | 官方 *Agent Swarm* 文章 | 再次明确 **up to 100 subagents in parallel**、>1,500 tool calls；展示 research/search 场景 | 官方工程自报 citeturn10view6 |
| 2026-04-20 | K2.6 / 帮助文档更新 | 上限升级为 **up to 300 sub-agents simultaneously**，单任务可超过 4,000 tool calls；官方仍将 3×–4.5× critical-path reduction 作为大型搜索场景指标 | 官方产品自报 citeturn2search3turn3search4 |
| 2026-07 | K3 | 当前帮助资料称 Agent Swarm 已由 K3 驱动，300-agent 上限仍为公开产品能力 | 官方产品说明 citeturn3search12turn3search4 |

早期 Agent Swarm 的官方文章中有一个特别容易造成误传的演示：系统处理 **200+ Paul Graham essays**。这里的 200+ 指 essay 数量，不是 200 个 Agent；同一篇文章对 Agent 数量写的是最多 100。citeturn10view6

另一个可能的混淆来源是更早的 Kimi K2 Thinking。Moonshot 曾公开强调其可以完成 **200–300 sequential tool calls** 而无需人工干预；这里的 200–300 是连续 tool calls，也不是 Agent 数量。citeturn3search8

因此，当前“约 200 Agent”说法可能来自：

**200+ essays**、**200–300 sequential tool calls**、或在 100→300 两代产品之间被二手材料泛化成“~200 agents”。这一因果关系没有一手来源直接确认，所以只能记录为**最可能的数字混淆路径**。citeturn10view6turn3search8

### Kimi Agent Swarm 到底公开了什么技术含义

K2.5 的官方技术材料并没有把 Swarm 描述成预先硬编码的固定专家流水线。官方称主模型会动态拆分任务、创建 specialized subagents，并通过 **Parallel-Agent Reinforcement Learning（PARL）** 学习并行执行；内部实验显示随着训练 compute 增长，reward 与平均 parallelism 上升。citeturn2search4

早期 Agent Swarm 文章还明确把 **direct sub-agent communication** 与 **dynamic parallel width** 列为后续工作。这一点很重要：至少 2026 年 2 月公开的 100-agent preview 并不是一个已有完全自由 peer-to-peer mesh communication 的 swarm。citeturn10view6

到 K2.6/current product docs，系统公开上限变成 300 个 subagents，但现有公开材料主要展示的是 search/research/coding product behavior 与规模指标，并没有公开足够细的 server-side scheduler、mailbox、shared-memory consistency、agent-lifetime、failure recovery 或 PARL training implementation。citeturn3search4turn22search0

本轮还发现一个文档版本漂移现象：Kimi 中文帮助材料中存在正文已经写“300 subagents”，但部分旧示例 caption 仍残留“100 subagents”的情况。这更支持“产品能力在快速迭代”的解释，而不是存在一个稳定的 200-agent 配置。citeturn3search15

### 目前没有确认到的东西

本轮没有找到 Moonshot 官方公开的 **Agent Swarm orchestration server source code**；公开 Kimi 模型 weights/repository 与 Kimi Code 能证明模型和 coding-agent 生态开放，但不能等同于 300-agent Swarm 的调度实现已经开源。citeturn2search7turn3search5

也没有找到独立第三方在受控条件下复现“300 simultaneous subagents / 4000+ tool calls / 4.5×”的公开 benchmark。因此这些数字目前应记录为：

**“Moonshot 官方可核实的产品能力与内部评测数字”，而不是独立验证过的科研结论。** citeturn3search4turn2search4

同样，目前没有公开材料足以回答“300”究竟是 300 个同时保持完整 model context 的持久 worker、300 个逻辑 task-agent、还是 scheduler 能并发维持的最大 subagent slots；公开文档使用的是“sub-agents simultaneously/parallel”的产品表述，但资源层语义尚不充分。citeturn3search4

所以本次专项核验的最稳妥记录是：

> **已确认：100 → 300 的官方演进。**  
> **未确认：约 200 Agent。**  
> **最可能混淆项：200+ essays 或 200–300 sequential tool calls。**  
> **未确认：Swarm server-side implementation / PARL training code / 独立规模复现。** citeturn10view6turn3search8turn3search4

## 附录索引

**A. 最值得精读的资料**

| 资料 | 为什么值得完整阅读 |
|---|---|
| **OpenAI Codex Subagents docs + `multi_agents_spec.rs`** | 直接观察当前 Codex 的 thread tree、spawn/fork/message/wait/interrupt/lifecycle，以及官方对并行读写任务的边界判断；对基于冻结 Codex source 的 RONDO 属于第一优先级。citeturn13view0turn12search8 |
| **OpenAI — The next evolution of the Agents SDK** | 当前 OpenAI 对 harness、memory、sandbox、filesystem primitives 的方向性表述，可用于区分 Responses API 与 agent runtime。citeturn13view1turn13view2 |
| **OpenAI — Codex app / worktrees** | 公开展示“多 thread + workspace isolation”作为 coding-agent 并行基础设施的产品化形态。citeturn13view4 |
| **Anthropic — How we built our multi-agent research system** | 目前最完整的生产 multi-agent research postmortem：并行收益、15× token cost、失败案例、checkpoint、artifact bypass coordinator、async 难题都在同一资料中。citeturn14search11turn11view0turn11view3 |
| **Anthropic — Scaling Managed Agents: Decoupling the brain from the hands** | 极重要的 meta-harness 资料；session ≠ context window，append-only log、stateless harness、sandbox interface 与 crash recovery 都非常清楚。citeturn15view0 |
| **Anthropic — Effective harnesses for long-running agents** | 直接记录 compaction 不够、fresh sessions、progress artifacts 和 premature completion 等负面结果。citeturn15view3 |
| **Anthropic — Harness design for long-running application development** | context reset、generator/evaluator separation、自评偏乐观、structured handoff 的后续演化。citeturn15view2 |
| **Anthropic — Building a C compiler with a team of parallel Claudes** | 很重要的反主流案例：无中央 orchestrator、无直接通信，仅靠 Git、task lock、tests、docs 与大量 fresh sessions 扩展到大型项目。citeturn15view1 |
| **Kimi K2.5 + Agent Swarm 官方技术资料** | 100-agent 初代规模、PARL、1,500 tool calls、并行 speedup 与早期限制的一手来源。citeturn2search4turn10view6 |
| **Kimi K2.6/current Agent Swarm docs** | 300-agent 当前产品上限与 4,000+ tool-call 口径的一手依据；也是后续追 Swarm 实现最重要入口。citeturn3search4turn22search0 |
| **Microsoft — Magentic-One** | dual-ledger orchestrator、replanning loop 和 specialized workers 的经典实现；源码可查。citeturn20search1turn20search15 |
| **Microsoft Agent Framework orchestration docs** | 看 AutoGen/Magentic-One 如何演化成 explicit graph/workflow runtime，同时并存 concurrent/handoff/group-chat/magentic 多种拓扑。citeturn20search2turn20search6 |
| **Google — Towards/AI co-scientist** | 与 coding swarm 差异很大的多 Agent science 路线：generation/reflection/ranking/evolution/meta-review。citeturn21search0 |
| **Google A2A** | Agent 与 Agent 系统之间 interoperability/opaque boundary 的标准化尝试；适合研究跨 Harness delegation。citeturn5search14turn5search10 |
| **Meta Collaborative Reasoner / Coral** | 把“合作能力”当作训练问题而不是仅靠 harness prompt；适合追 learned coordination。citeturn6search0 |
| **Meta Agents Research Environments / Gaia2** | async、noise、collaboration、temporal constraints 与 scaling plateau 的官方 eval environment。citeturn6search2 |
| **Meta AIRA₂** | research agents 的 async multi-GPU worker pool 和长时 experiment loop，是“cluster of agents for research”路线的重要实例。citeturn6search10 |
| **Meta — Formalizing Mathematics at Scale / AutoformBot** | 当前最值得看的超大规模公开 multi-agent 工程之一：thousands of agents、DAG scheduling、Git coordination、formal verifier、SLURM，多数代码已开放。citeturn19search0turn19search1 |
| **Alibaba — AgentScope / Very Large-Scale Multi-Agent Simulation** | actor-based distributed MAS、message exchange、大规模模拟，是与中央 Root 路线不同的重要系统传统。citeturn7search17turn7academia36 |
| **DeepSeek Harness + Cordis** | 本轮最新且最值得源码级跟踪的 harness：everything-is-plugin、append-only trajectory、session/replay、subagent scheduling trace、typed events/reversible effects。citeturn16search1turn16search13turn18search0 |
| **MAST — Why Do Multi-Agent LLM Systems Fail?** | 14 类 failure taxonomy；适合作为 future RONDO eval/trace labeling 的反面资料库，而不是直接当设计论文。citeturn22search1turn22search7 |
| **HiddenBench — Systematic Failures in Collective Reasoning** | 最强的“信息都分散在团队里，但团队仍然整合失败”的受控证据之一。citeturn22search4 |
| **Silo-Bench** | 区分 communication 与 reasoning integration，并展示 coordination overhead 随规模吞掉并行增益。citeturn23search4 |
| **CooperBench** | 对 coding-agent team conflict 的系统 benchmark；“合作反而平均低 30%”是必须认真处理的反例。citeturn23academia19 |
| **General AgentBench** | context ceiling 与 verification gap 为 sequential/parallel scaling 提供了非常清晰的负面解释。citeturn23search3 |
| **CoAgent: Concurrency Control for Multi-Agent Systems** | 直接把 database serializability、sagas、undo、conflicting read/write 引入 Agent；对任何未来 shared workspace 都是重要相邻 CS。citeturn23academia17 |

**B. 值得进一步查源码的系统**

| 项目 | 本轮已确认的入口 | 建议重点代码区域 | 本轮阅读状态 |
|---|---|---|---|
| **openai/codex** | `codex-rs/core/src/tools/handlers/multi_agents_spec.rs` citeturn12search8 | `spawn_agent`、`send_message`、`followup_task`、wait/list/interrupt/close；继续向 agent registry、thread tree、turn routing、persistence 实现追踪 | **已实际检查 tool-spec 源码**；更下层 runtime 尚未完整追读 |
| **openai/openai-agents SDK** | 官方 SDK 与 current docs citeturn13view1turn13view2 | session、handoff、agents-as-tools、tracing、memory/sandbox adapters | 本轮以官方文档为主，**未逐文件源码审计** |
| **Anthropic long-running harness quickstart** | 官方文章链接的 quickstart citeturn15view3 | initializer/coding prompts、progress artifact、session reset、Git lifecycle | 已读工程说明，**未逐文件审计 quickstart** |
| **Anthropic parallel C compiler artifact** | 官方文章链接到 Git repo citeturn15view1 | `current_tasks/` locks、agent logs、Git history、progress docs、CI/test harness | 已读官方实现描述；值得直接沿 Git history 重建 coordination 行为 |
| **microsoft/autogen** | `python/packages/autogen-ext/src/autogen_ext/teams/magentic_one.py` citeturn20search15 | Task/Progress Ledger prompts、outer/inner loop、speaker selection、stall detection、state serialization | **已定位具体源码文件**，未对整个 runtime 做完整 call-graph review |
| **Microsoft Agent Framework** | 官方 workflow/orchestration implementation citeturn20search2turn20search6 | graph state、concurrent/handoff/group-chat/magentic execution、checkpoint/HITL resume | 本轮主要读官方 docs |
| **deepseek-ai/deepseek-harness** | `docs/architecture.md`、Cordis primer/API、session/trajectory docs citeturn16search13turn16search7 | session log、agent/subagent plugins、scheduler、context injection、tools、storage、fork/replay、plugin lifecycle | **已实际阅读多个 architecture/API/source docs**；项目非常新，应优先继续源码下钻 |
| **cordiverse/cordis** | Cordis repo与 DeepSeek vendored source citeturn18search0turn16search10 | Context/Fiber/Registry、effects、dependency activation/deactivation、event dispatch、hot reload | 已读 API/primer 与部分 event source 描述 |
| **facebookresearch/autoform-bot** | `autoform/bot/`、`core/`、`tools/`、`docs/` citeturn19search1 | orchestrator/worker/reviewer registry、DAG scheduling、agent messaging、SLURM control plane、Git coordination、trace format | **仓库结构和多份官方 docs 已检查**，是下一轮源码研究优先项目 |
| **agentscope-ai/agentscope** | AgentScope current repo/论文 citeturn7search5turn7search1 | MsgHub、Pipeline、distributed actor/runtime、fault handling、state persistence | 本轮确认了架构概念，**未可靠逐文件核实当前 1.x/2.x 路径，因此不虚构具体文件名** |
| **Google A2A / ADK** | 官方 A2A repo 与 ADK integration citeturn5search14turn5search10 | remote-agent lifecycle、task status、message/artifact transport、identity/capability discovery | 本轮读协议/官方资料，未做完整源码 audit |
| **Moonshot Kimi model/code repos** | Kimi/Kimi Code 官方公开仓库 citeturn2search7turn3search5 | 可检查 subagent client-side support，但尤其要确认与 Web 产品 Agent Swarm server 是否共用实现 | **目前没有证据表明公开仓库包含 300-agent Swarm server orchestration；不要把模型开源与 Swarm 开源混为一谈** |

**C. 尚未查清的问题**

| 问题 | 当前能确认到的边界 |
|---|---|
| **Kimi “300 simultaneous subagents”的 runtime 定义到底是什么？** | 官方产品文档确认 300，但没有充分公开 worker lifetime、model instance/context persistence、scheduler slot、资源占用与 backpressure 语义。citeturn3search4 |
| **Kimi PARL 的完整算法、训练数据、reward decomposition 与代码是否会公开？** | 官方 K2.5 材料给出机制名称和内部 scaling 图景，但本轮未找到可完整复现的训练实现。citeturn2search4 |
| **所谓“约 200 Agent”有没有被 Moonshot 某次中文演讲口头说过？** | 目前官方书面资料只能确认 100→300；尚未找到支持 200 的原始演讲/论文。citeturn10view6turn3search4 |
| **Codex multi-agent 在 tool schema 以下如何存储 thread tree、mailbox 与 pending follow-up？** | 已确认公开 tool-level semantics；还需沿 Codex Rust 源码做完整 call graph。citeturn12search8 |
| **Codex subagent 之间可见的“团队状态”究竟有哪些隐式 runtime fields？** | 文档证明独立 thread、parent/child control 与 messaging；没有足够证据把它描述成统一 shared semantic state。citeturn13view0turn12search8 |
| **Anthropic 2025 Research system 提到的 async subagents 后来在生产中发展到什么程度？** | 2025 文章把 async state consistency/error propagation 列为未来难题；2026 Managed Agents 解决 durable session/harness infrastructure，但并不等价于公开了 Research 的最新 multi-agent scheduler。citeturn11view2turn15view0 |
| **DeepSeek Harness 对多个 agents 同时修改同一 session/workspace 的 consistency model 是什么？** | session/event/plugin architecture 已公开，但项目刚进入 developer preview；多 Agent shared-world consistency 尚值得专门源码追踪。citeturn16search0turn16search13 |
| **DeepSeek Cordis 的 reversible effect 与不可逆外部 tool call 如何组合？** | Cordis 能撤销 plugin registration/listener 等 runtime effects；这不自动意味着现实外部 side effects 可逆，正好可与 CoAgent/saga 类研究对照。citeturn16search7turn23academia17 |
| **AgentScope 当前最新版的大规模 runtime 是否有新的真实 workload scaling 数据？** | 论文证明其 actor/distributed direction；本轮尚未找到足够新的统一 benchmark 来与 Kimi/AutoformBot 比较。citeturn7academia36turn7search1 |
| **“Agent 数量”是否存在跨系统可比较的统一 scaling law？** | 目前研究分别统计 agent count、trajectory count、session count、tool calls、wall-time、token budget；General AgentBench、Silo-Bench 等已经表明不归一化 compute 很容易误判收益。citeturn23search3turn23search4 |
| **Semantic shared state 是否能真正解决 HiddenBench 类失败？** | HiddenBench 证明 disclosure/integration policy 是主要瓶颈之一；仅增加共享通道或让事实“存在”并不足以证明 Agent 会主动寻找和使用它。尚缺专门比较 event store、semantic KB、mailbox、broadcast 等机制的强 benchmark。citeturn22search4 |
| **Fact provenance、staleness、contradiction、belief revision 应怎样 benchmark？** | 当前 durable logs、Git、ledgers、formal verifiers 分别覆盖部分问题，但本轮没有发现一个已经成为事实标准的 multi-agent benchmark 同时评价这些语义。citeturn15view0turn20search0turn19search6 |
| **并行 writer 的 consistency 能否在非可逆环境中可靠解决？** | CoAgent 的 MTPO 很有价值，但依赖 tool footprints、inverse/repair 等条件；真实 SaaS、payments、deployment 等不可逆 side effect 仍是开放问题。citeturn23academia17 |
| **Verification gap 是否会成为大规模 swarm 的真正上限，而非生成 compute？** | General AgentBench 已在并行 trajectory scaling 中观察到该瓶颈；Kimi 等产品报告的是吞吐/critical path 优势，尚缺公开的跨系统、compute-normalized verifier study。citeturn23search3turn2search4 |
| **Multi-agent security 的最小 authority unit 应该是 thread、agent、task 还是 tool capability？** | 当前 Anthropic 强调 sandbox/credential separation，安全研究又表明 malicious input 可沿 MAS workflow 传播；delegation 与 authority 的组合仍明显缺乏成熟统一模型。citeturn15view0turn20search25 |
| **是否应该长期保留固定 reviewer/verifier role？** | Anthropic 在某些长时 coding 中发现独立 evaluator 很有效；AutoformBot 有 hard verifier；但其他 benchmark 显示 verifier 本身可能是 scaling bottleneck。现有证据明显依赖任务类型，不能形成统一结论。citeturn15view2turn19search6turn23search3 |
| **learned orchestration 是否会取代大量手写 routing policy？** | Kimi PARL、Meta Coral 已给出早期正面结果，但开放复现、跨模型迁移、failure interpretability 和 control-plane safety 仍不充分。citeturn2search4turn6search0 |

综合这批资料，当前公开前沿可以比较可靠地说已经形成了一个非常多样的实验空间：从 Codex 的 parent/child thread control、Anthropic 的 durable session 与 artifact handoff、Magentic-One 的 coordinator ledger、Kimi 的 learned high-width swarm、AgentScope 的 actor/message runtime、AutoformBot 的 thousands-agent DAG、到 CoAgent 的 database-style concurrency control，都在解决“多 Agent”这个词下面不同层次的问题。与此同时，HiddenBench、Silo-Bench、CooperBench、MAST 和 General AgentBench 连续给出了强反例：**Agent 更多、消息更多、上下文更多、轨迹更多，均不自动等于团队知道得更多、协调得更好或最终结果更可靠。** citeturn12search8turn15view0turn20search0turn3search4turn19search0turn23academia17turn22search4turn23search4turn23academia19turn22search1turn23search3