# RONDO 证据协作型多智能体内核演进调研

> 文档性质：方向性前置调研，不是实施计划、接口承诺或已验证能力声明。
> 调研日期：2026-08-12。
> RONDO 基线：<code>73b05035c046c817a5c050faa9803f510856f83e</code>；冻结 Codex 基线：<code>rust-v0.147.0</code> / <code>be6e8eac029b183056b7e4402879f15d2c85f61b</code>。
> 调研范围：同行评审论文、近期预印本、标准、头部实验室公开资料、冻结 Codex 与本地教师源码快照。
> 执行边界：本轮只读源码和资料，没有运行 Cargo、Docker、测试、真实模型或真实 API，没有修改运行中实例；本文是唯一交付物。
> 时效说明：在线产品文档和预印本均按 2026-08-12 可见版本阅读，后续实现前应重新核验。
> 规划归属：本文只保存研究证据、候选设计与复杂度边界；当前状态、阶段顺序与实施任务只以 `doc/WBS/multi-agent-trusted-evidence.md` 为准。

## 摘要

RONDO 不应把未来路线定义成“多个智能体互相发消息”，也不应把完整对话、工具输出、推理和结论混在一份共享上下文中。当前实证与源码共同支持一个更有辨识度的方向：

> **把共享证据提升为 RONDO 的一等运行时对象：每个 agent 保持私有上下文；工具结果、child 原件和短结果卡形成可恢复记录；内存中的 SharedContextBoard 只做热索引与上下文投影；agent 围绕可验证分歧协作；root 保留主候选原件，以它为骨架完成合成。**

“工具调用结果属于客观证据”基本正确，但只能理解为：

> RONDO 的工具网关在某个调用参数和当前工作区快照下产生了这个结果，其他 agent 可以直接按 ID 引用。

它不自动证明测试覆盖了完整需求，也不自动证明某个智能体对结果的解释正确。因此运行时结果与 AI 判断仍应是两种类型；前者可共享复用，后者允许相互冲突。

现有受控研究也不支持“智能体越多越好”。同预算下，强单智能体、自一致性或对初始独立答案直接投票，常常追平或超过多轮辩论；多智能体的稳定收益集中在可并行宽搜、上下文覆盖不足、真正异构的工具/知识来源，以及可验证的中间结果。依赖密集、共享可变状态、严格顺序推理和强单体已足够好的任务，反而容易退化。

研究证据对 RONDO 支持以下设计原则：

1. 共享的是带来源、范围和时效的观测，不是“团队共同相信的事实”。
2. 初始分析应盲独立，避免先发言者、模型身份、答案长度和多数意见污染后续判断。
3. 智能体只发布短的 <code>ResultCard</code> 与原件定位，不公开完整思维链。
4. 一个弱模型提供的可复现反例，可以推翻主候选的局部主张；重复“不同意”不能靠票数覆盖它。
5. 合成应保存主候选，以其为骨架吸收有证据的局部改进，并保留未解决异议。
6. 对照与指标适合发现瓶颈，不能单凭 agent 数量或讨论轮数证明系统更强。

本文建议将该方向暂称为 **Evidence-Centered Deliberation（证据中心协作）**。它仍使用 agent，但创新重点从“会话数量”转向“证据复用、独立判断、分歧解析和高质量合成”。

> 候选产品不应是聊天群或审计平台；其辨识度来自“私有判断、可恢复共享观测、有限分歧协作”。

### 工程目标优先

这里的“轻量”是研究筛选原则：控制同时引入的概念、风险和未知量，而不是机械限制 diff 大小。候选设计应复用
冻结 Codex 已有 thread、rollout、AgentGraphStore 和控制面；局部补丁若会制造双重真相源、不可恢复数据或长期耦合，
则内核边界重构可能比外围补丁更合理。是否实施、如何分阶段不由本文决定。

## 1. 调研问题、方法与证据边界

### 1.1 本次要回答的问题

1. 哪些任务拆分、角色、交接与共享方式最适合 RONDO，怎样先做出有用闭环？
2. 什么信息应共享，什么信息应保持私有？
3. 怎样复用相同工具结果而不把一次局部观测误当成永久事实？
4. 当智能体结论不同，怎样把分歧转化为有价值的新信息，而不是继续自由辩论？
5. 怎样防止弱模型、弱聚合器、错误多数或先到消息覆盖强模型的正确结果？
6. 调度器不读取私有思维链时，凭什么判断下属结论？
7. 冻结 Codex 和教师项目已经提供了什么，RONDO 真正缺的是什么？
8. 后续怎样用轻量测评定位问题、比较协议并持续优化，而不是决定是否实现？

### 1.2 证据标签

| 标签 | 含义 | 能支持什么 | 不能自动支持什么 |
|---|---|---|---|
| **[实证]** | 同行评审或较强受控实验 | 特定模型、任务、预算和协议下的观察 | 任意代码任务上的普适规律 |
| **[预印本]** | 尚未完成同行评审的受控研究 | 近期现象与可复现实验线索 | 稳定结论或产品保证 |
| **[厂商经验]** | 头部实验室生产/工程报告 | 真实系统设计、成本和失败经验 | 匹配预算后的因果增益 |
| **[标准]** | W3C、IETF、OCI、SLSA、协议规范 | 数据语义、来源和互操作设计先例 | 模型性能结论 |
| **[源码]** | 冻结版本的可运行实现 | 该版本真实具备或缺少的机制 | 官方未来路线或未执行路径的效果 |
| **[推论]** | 本文跨来源综合的工程判断 | 候选架构和约束 | 已经验证的性能事实 |
| **[假设]** | 建议后续用 RONDO 测评验证 | 明确研究对象 | 当前结论 |

论文之间看似矛盾，常常是因为测量的变量不同。本文始终区分：

- 独立采样与投票；
- 并行任务分解；
- 多轮自然语言讨论；
- 异构模型 mixture；
- 计划、执行、审查、验证等角色化工作流。

“多次调用优于一次调用”不等于“通信有因果价值”；“厂商系统比分配更少计算的单体高分”也不等于“多智能体架构本身更优”。

### 1.3 一条贯穿全文的因果框架

~~~text
净收益
  = 独立且有用的信息增量
  + 可并行带来的时延收益
  + 真正互补的工具、模型和上下文
  - 任务碎片化损失
  - 通信压缩与上下文污染
  - 相关错误放大
  - 聚合器/调度器选错
  - 额外 Token、工具、恢复和协调成本
~~~

这不是立项公式，而是实现时的优化检查表：扩大独立信息增量，压低碎片化、上下文和聚合成本。

## 2. 当前研究真正说明了什么

### 2.1 最强的受控结论：任务结构比 agent 数量重要

**[实证]** 2026 年 Nature Machine Intelligence 的 [Capable language models can outgrow the benefits of collaboration](https://www.nature.com/articles/s42256-026-01268-y) 比较了 260 个配置、三个模型家族、五种系统架构和六个 agentic benchmark，并尽量匹配任务、工具和计算上限。主要结果不是“多智能体好”或“多智能体坏”，而是跨度极大：

- 可分解的 Finance 任务中，中心化多智能体相对单体最高报告约 <code>+80.8%</code>；
- 严格顺序规划的 PlanCraft 中，多智能体退化约 <code>39%–70%</code>；
- SWE-bench Verified 中，多智能体约退化 <code>1%–13%</code>；
- 六类任务合并后的多智能体平均增益约为 <code>0.0%</code>，方差很大；
- 无中心验证的独立架构更容易放大错误，中心化架构相对更稳；
- 强单体基线越高，协作的边际收益通常越低。

论文提出的单体能力阈值和架构选择准确率都是该实验分布上的经验规则，不是普适 scaling law；跨领域绝对预测仍然较弱。但它足以推翻“复杂任务天然应该增加 agent”的直觉。

**[预印本]** [Single-Agent LLMs Outperform Multi-Agent Systems on Multi-Hop Reasoning Under Equal Thinking Token Budgets](https://arxiv.org/abs/2604.02460) 在匹配 thinking-token 预算的多跳推理中也发现，除极低预算外，单体通常最强或与最佳多智能体无统计差异；只有人为削弱单体上下文后，多智能体才更稳定获益。这支持“上下文/覆盖瓶颈”而非“讨论本身”是重要因果来源，但其任务仍限于文本多跳推理，不能直接外推到代码 agent。

### 2.2 公平预算下，讨论经常不如独立采样

**[实证]** [Reasoning in Token Economies](https://aclanthology.org/2024.emnlp-main.1112/) 在多个任务和 Token 预算下发现，CoT Self-Consistency 经常比 Multi-Agent Debate 和 Reflexion 更高效；增加讨论轮次会快速增加历史上下文，答案熵下降却不必然提高正确率。

**[实证]** [Large Language Models Cannot Self-Correct Reasoning Yet](https://openreview.net/forum?id=IkmD3fKBPQ) 复现三 agent 辩论时，用相同累计响应数做 Self-Consistency：GSM8K 上辩论的约 <code>83.2%/83.0%</code>，低于对应独立采样的约 <code>85.3%/88.2%</code>。这说明早期辩论论文的部分提升来自“多生成了几次答案”。

**[实证]** NeurIPS 2025 的 [Debate or Vote](https://proceedings.neurips.cc/paper_files/paper/2025/hash/934252acd87f254d5d4672fbde283bd2-Abstract-Conference.html) 直接拿同一批独立初答做多数票，再与多轮通信比较。两个主要模型中，初答投票均高于最佳辩论，更多轮通常继续退化。初始候选的多样性有价值，通信却常把多样性压低而没有朝真值产生稳定漂移。

**[实证]** [Are More LM Calls All You Need?](https://papers.nips.cc/paper_files/paper/2024/hash/51173cf34c5faac9796a47dc2fdd3a71-Abstract-Conference.html) 进一步说明，增加样本只会更可靠地找到模型分布的众数；当错误答案本来就是众数，样本越多反而越稳定地错。

因此，RONDO 的调优实验最好能回答：

> 改善来自真正的协作机制，还是只来自更多调用？哪一部分协议值得保留？

这些基线用于诊断和优化，不是“达不到就不做”的淘汰门槛。

### 2.3 正面结果没有失效，但适用范围更窄

早期 [Improving Factuality and Reasoning through Multiagent Debate](https://proceedings.mlr.press/v235/du24e.html)、[ReConcile](https://aclanthology.org/2024.acl-long.381/)、[Mixture-of-Agents](https://arxiv.org/abs/2406.04692) 和 [MacNet](https://openreview.net/forum?id=K3n5jPkrU6) 确实报告了明显增益。合理解读是：

- 多个候选比单次贪心回答更好；
- 异构模型有时提供不同错误分布、知识或工具能力；
- 宽度优先、工件传递和结构化拓扑可能优于稠密自由聊天；
- 在开放生成和研究宽搜中，更多计算与覆盖能显著提高结果。

但这些研究常没有严格匹配总 Token、调用次数和最强单体；开放生成指标还可能受答案长度与 LLM judge 偏置影响。[Rethinking Mixture-of-Agents](https://arxiv.org/abs/2502.00674) 发现，仅重复使用任务上最强模型的 Self-MoA 往往优于混入弱模型，说明“候选质量”通常比表面异质性更重要。

> 异构只有在贡献了可验证的专业能力、独立来源或不同错误模式时才有价值；“模型名字不同”不是充分条件。

### 2.4 通信可能制造错误共识

**[预印本]** [Talk Isn't Always Cheap](https://arxiv.org/abs/2509.05396) 将同一批独立初答与看过彼此理由后的结果比较，多个任务中出现正确→错误的改答多于错误→正确；正确 agent 没有同立场同伴时更容易被翻错。

**[实证]** [Examining Inter-Consistency of Large Language Models Collaboration](https://aclanthology.org/2023.findings-emnlp.508/) 发现能力不匹配的组合可以低于最强成员单独表现，加入强 judge 也不能自动恢复损失。

**[实证]** ACL 2026 的 [Social Dynamics as Critical Vulnerabilities](https://aclanthology.org/2026.acl-long.1756/) 显示错误多数、感知到的“专家能力”、论证长度和模型家族都会影响代表模型；一个更强但错误的“专家”也可能压过多个正确同伴。

**[实证]** NeurIPS 2025 的 [Collaborative Reasoner](https://openreview.net/forum?id=dye9w8IOV0) 观察到，即使推理错误，模型也很容易达到超过 90% 的表面 agreement。Agreement 不是正确性指标。

这里更准确的风险词是从众、sycophancy、信息级联、相关错误、上下文污染和错误传播。除非系统真的存在共同隐蔽目标，否则不应把普通失败笼统称作战略性“串通”。

### 2.5 运行型系统的瓶颈往往是验证、状态和停止

**[预印本/会议版本]** [Why Do Multi-Agent LLM Systems Fail? / MAST](https://arxiv.org/abs/2503.13657) 审阅 1,642 条真实轨迹，多个框架的任务失败率约为 <code>41%–86.7%</code>。高频问题包括重复步骤、reasoning-action mismatch、错误停止、任务不完整、错误验证和没有完成验证。显式目标校验与拓扑调整能恢复一部分表现。

**[预印本]** [On the Resilience of LLM-Based Multi-Agent Collaboration with Faulty Agents](https://arxiv.org/abs/2408.00989) 表明一个 faulty agent 就可能抹掉原有增益；尤其危险的是自然语言声称“bug 已修复”，其他 agent 随后相信该消息，而不是检查实际代码。层级结构相对更稳，Challenger + Inspector 可以恢复一部分损失。

这恰好支持 RONDO 的核心取舍：

- “agent 报告完成”只是协调信号；
- “补丁已修复问题”是主张；
- 文件差异和测试 invocation 才是可检查的观测；
- 测试结果是观察；任务是否完成仍由 root 按用户要求判断。

### 2.6 头部实验室公开系统提供工程先例

**[厂商经验]** Anthropic 的 [multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) 使用 lead + 独立 subagent context + CitationAgent，在内部宽搜评测中报告相对单 Opus 提升 <code>90.2%</code>，同时多智能体约消耗普通聊天 <code>15 倍</code> Token。该系统最值得借鉴的不是该百分比，而是：

- lead 负责分解和综合，worker 保持独立上下文；
- 子任务给出清晰目标、输出格式、工具和边界；
- 原始产物可持久化，向上只传摘要与引用，减少“多层传话”；
- 失败任务保留状态并有限重试，不整轮重启；
- CitationAgent 将最终陈述重新挂回原始来源。

**[厂商经验]** OpenAI 当前 [Responses API multi-agent beta](https://developers.openai.com/api/docs/guides/responses-multi-agent) 同样强调独立、有边界的并行任务和 root synthesis，并提醒 Token 成本与共享可变写入问题。[Agents SDK orchestration](https://developers.openai.com/api/docs/guides/agents/orchestration) 区分 manager-as-tools 与 handoff，建议只有专家确实需要不同指令、工具或政策时才拆分。产品文档说明的是当前主流编排形态，不能当作性能实验，也不能直接外推到冻结 Codex。

**[预印本/厂商研究]** Google 的 [Towards a Science of Scaling Agent Systems](https://arxiv.org/abs/2512.08296) 支持按任务结构选择拓扑；[Chain of Agents](https://research.google/blog/chain-of-agents-large-language-models-collaborating-on-long-context-tasks/) 则展示了分块处理和压缩交接。后者适合超长材料，但也提醒 RONDO 必须允许从摘要下钻到原始证据，避免早期遗漏永久传播。

**[厂商经验]** Microsoft [Magentic-One](https://www.microsoft.com/en-us/research/articles/magentic-one-a-generalist-multi-agent-system-for-solving-complex-tasks/) 的 Task Ledger、Progress Ledger 和停滞后重规划很实用；RONDO 只应借任务/进度思路，不把“事实、猜测、计划”混成同一种记录。Microsoft [Magentic Marketplace](https://www.microsoft.com/en-us/research/blog/magentic-marketplace-an-open-source-simulation-environment-for-studying-agentic-markets/) 观察到明显首提案偏好，说明先返回不能自动获得更大权重。

**[厂商研究]** Meta [Compute as Teacher](https://ai.meta.com/research/publications/compute-as-teacher-turning-inference-compute-into-reference-free-supervision/) 展示了保存完整候选、由 anchor 组合局部正确内容、允许综合器违背多数意见，以及对可验证任务使用程序校验。它直接启发“保留强底稿 + 局部补丁”，而不是把所有答案交给弱模型自由重写。

### 2.7 这些研究对实现的启发

| 研究现象 | RONDO 的实现动作 |
|---|---|
| 独立初答常比多轮讨论更有价值 | 第一轮彼此不可见，冻结原始 finding |
| 更多 agent 可能重复同一错误 | 以证据引用去重，不按人数算独立支持 |
| 摘要会丢关键信息 | summary 带 evidence ID，可按需读取原始输出 |
| 弱模型可能动摇强模型 | 弱模型优先找反例、跑检查、补约束，不做总编 |
| 中心验证更稳 | coordinator 统一安排验证和最终拼装 |
| lead 可能成为单点失败 | 主候选原文、反例和未决异议都保留，不只保留 lead 摘要 |
| 自由讨论容易空转 | 每轮必须产出新证据、具体反例、约束或可合并工件 |
| 成本随上下文快速增长 | 短 finding、证据句柄、懒加载、少量并发 |

这些动作可以从短运行协议起步，但长期会自然进入工具、持久化、上下文和恢复等内核边界；不需要建设研究级审计系统，也不应把它永远限制成提示词技巧。

## 3. 推荐架构：核心语义与可演进内核边界

“共享可信证据”若成为产品，应是运行时协作能力而不是审计产品。下图表达候选职责边界，不表示这些模块需要
同时建设，也不规定当前实施顺序：

~~~text
TUI / app-server
        ↑ typed team projection
Context Projection  ←  Collaboration Runtime  ←  AgentControl façade
                            │
           ┌────────────────┼────────────────┐
           │                │                │
      Task Runtime    Evidence / Result   Scheduler
           │              Catalog            │
           └────────────────┼────────────────┘
                            │
       ThreadStore / AgentGraphStore / optional CollaborationStore
                            │
                     Workspace Manager
~~~

root、少量只读 worker、结果类型和内存索引足以说明最小语义；Task Runtime、Scheduler、CollaborationStore 与
Workspace Manager 只有在对应语义真实出现时才值得独立成层。`AgentControl` 适合作为兼容 façade，避免承载全部新增状态。

### 3.1 私有 agent 上下文

每个 agent 保留自己的：

- 该 thread 自身的工作上下文，以及 provider 实际返回的 reasoning item（如有）；
- 局部假设、搜索路径和待办；
- 尚未发布的判断；
- 与自身任务相关的历史。

默认不把其他 agent 的完整对话、思维链和工具流水复制进来。需要共享时只传：

- 当前任务卡；
- 少量直接相关的 evidence refs；
- 第二阶段才开放的其他 finding；
- 必要的原始输出下钻句柄。

这既保留独立性，也避免在每个上下文中重复几千行工具输出。

### 3.2 持久证据记录与运行时投影

Evidence Catalog 不是“事实数据库”，也不是“审计账本”。它只记录宿主实际观察到的结果、原件位置和发布关系，不判断内容真假。SharedContextBoard 则是 agent tree 内由 root 按任务和协作阶段生成的**可丢弃热投影**；child 只能读取已发布给自己任务的 ID。目标只有三个：

1. 已发生的结果只登记一次，可被 root 选定的多个任务按 ID 读取；
2. agent 引用原结果，不在消息里反复复制和摘要；
3. 代码或输入改变后，不误用旧结果。

产品侧只需看到：稳定 ID、类型、工具名、cwd/worktree、可选的上下文提示、短预览和源结果定位。预览由 handler 的确定性 formatter 或保守截断生成，只用于导航；定位指向现有 rollout/tool-output、child final 或项目已有工件。

持久化与内存不是二选一。推荐从第一天就区分三层：

1. **持久原件**：工具输出继续放 durable ThreadStore/rollout；参与可恢复协作的 child final 放自身持久 thread；补丁、报告和大型输出放项目已有工件或后续 artifact abstraction。
2. **持久协作状态**：EvidenceRecord、ResultCard、发布关系和必要的 task/workspace 绑定；优先编码在现有 rollout，语义稳定或查询变重后再抽出轻量 CollaborationStore。
3. **热运行状态**：SharedContextBoard、等待队列、LRU payload、single-flight waiter 和活跃状态；可以丢弃，恢复后从前两层重建。

因此，team 结束或内存淘汰只释放热索引，不能让已完成且仍在保留期内的结果消失。已经发布的 EvidenceId 必须先有可恢复 locator；恢复时无法解析的引用要显式标成 missing，不能悄悄继续当作有效证据。

### 3.3 Coordinator 到 Collaboration Runtime

早期 Coordinator 不需要通用任务数据库：任务目标、角色、输入引用和输出格式继续放在现有 spawn/follow-up 参数中；每个 child 只需提交第 5.1 节的一张 ResultCard。随着恢复、排队、更多工具结果类型和多 writer 出现，再把确定性状态逐步收进 Collaboration Runtime：

Coordinator 的职责是：

- root 模型拆解任务、选择角色并做语义裁决；
- runtime 控制并发、取消、恢复和上下文预算；
- 将 ResultCard 中的 finding 归并成相同、互补或冲突；
- 对冲突安排有界、最有区分力的检查；
- 保留主候选和有价值的少数异议；
- 生成最终结果或交给单一 integrator。

它不需要读取每个 agent 的私有思维链，也不需要成为无所不知的“超级裁判”。身份、格式、scope、持久状态和资源约束由代码判断；开放语义才交给模型。

### 3.4 架构不变量与阶段策略

| 架构不变量 | 起步策略 | 可演进方向 |
|---|---|---|
| 私有上下文与共享证据分离 | root + 两个只读 worker | 独立的 Context Projection 层 |
| 已发布证据具有可恢复来源 | 最窄候选只覆盖已落盘 FunctionCallOutput | 更多 observation adapter 与 artifact |
| 内存板只是持久记录的投影 | 有界 ID 索引和 payload LRU | checkpoint + tail scan / 可重建查询投影 |
| 写 agent 必须隔离 | root 唯一 writer | 每 writer 独立 worktree + 单一 integrator |
| 副作用不能因复用自动重放 | 显式引用既有结果 | 按工具证明 ExactReuse/幂等性 |
| 协作轮次必须有界 | 默认一次定向验证 | 按新证据与收敛状态自适应停止 |

这些是不随实现阶段变化的语义边界；具体模块数量、内部 API 和存储形态不应在这份前置调研中提前锁死。

## 4. 共享证据的实用语义

### 4.1 共享什么

| 类型 | 共享内容 | 不应顺便推断 |
|---|---|---|
| 工具输出 | 工具、参数、scope、退出状态、已存输出引用 | 工具输出中的自然语言一定正确 |
| 测试结果 | 被测代码状态、命令、环境摘要、exit code、报告引用 | 未覆盖的需求也已正确 |
| 文件读取 | 路径、工作区版本、内容/片段引用 | 另一个 worktree 仍相同 |
| 网页/论文 | URL、读取时间、原文片段或快照引用 | 来源权威、主张已被来源支持 |
| diff/patch | 基线、目标、变更工件 | 变更已经安全或应当合并 |
| agent 输出 | finding 与证据引用 | 它是客观证据 |

最值得保留的一句话是：

> 共享的是“在这个输入和代码状态下观察到了什么”，不是“团队已经认定什么是真理”。

### 4.2 最简单可靠的 scope

最小显式引用语义不做判等缓存，只在显示时携带足够上下文：

- 工具名与 cwd/worktree；
- 调用参数的短导航信息；
- 结果产生时的 HEAD/代码状态（若工具适配器已有）；
- 时间敏感来源的读取时间；
- 源 thread + call ID。

若为某个明确纯读工具增加自动复用，应由该适配器定义 <code>CallKey</code> 和 <code>SnapshotKey</code>。共享可变 cwd 不存在一个轻量而可靠的通用快照计数：shell 或项目外进程都可能绕过 RONDO 写工具，所以不能把简单计数器当作测试复用依据。

若 root 打算让另一个 agent 据此跳过重跑，测试结果的上下文提示应尽量包含：

~~~text
workspace/worktree
HEAD + 当前代码状态指纹
command
关键环境摘要（不含密钥）
runner/tool version
exit code
stdout/stderr 或报告引用
~~~

这不是缓存键或审计要求，只是帮助 root 避免把“在 A 代码上通过的测试”误用到 B 代码上的最小上下文。

### 4.3 复用规则

最低风险的复用是**显式引用**：A 跑完后得到 E17，B 看到 E17 并读取原结果，因此不再自己运行。它不要求
runtime 猜测任意 shell/MCP/Web 调用是否等价。透明命中和 single-flight 只适合少量明确标成 shareable 的工具：

| 调用 | 默认规则 |
|---|---|
| 相同不可变输入的纯读工具 | 可评估自动复用 |
| task-owned 只读 snapshot 的文件读取 | 默认引用既有结果；专门适配后才自动复用 |
| 测试与构建 | 默认由 agent 引用；仅专门适配后才自动复用 |
| 网页/远端状态 | 默认只引用已有内容；专门适配后才按短 TTL 复用 |
| 会写文件的工具 | 不缓存执行，只共享结果/receipt |
| 真实外部副作用 | 永不因恢复或其他 agent 请求而自动重放 |

同一 payload 被五个 finding 引用仍是一份证据，不算五次独立支持。若确实重新执行了测试，则是第二次 observation；可以共用同一 payload 存储，但保留两个运行结果。

透明命中必须限制在 task-owned 的只读 snapshot，或所有写入都能由 RONDO gateway 精确观察的隔离 worktree；
只有明确证明幂等/隔离的类别才可扩展。共享可变 cwd 只允许显式引用旧观察。支持复用的工具还应提供
<code>fresh=true</code>，用于 flaky test、用户明确要求复核或 verifier 独立重跑。

### 4.4 持久化、写入顺序与上下文效率

首版优先复用 Codex 已有 tool output/rollout 存储，但不能把“已经进入内存 history”直接等同于“已经可靠落盘”。冻结源码中的关键事实是：

- <code>Session::record_conversation_items()</code> 先更新内存 context，再调用持久化；
- <code>Session::persist_rollout_items()</code> 调用 <code>LiveThread::append_items()</code> 后只记录错误并返回 <code>()</code>，调用方拿不到可用于发布 EvidenceId 的成功回执；
- 本地 ThreadStore 以 rollout JSONL 为 canonical history，SQLite 只是可重建投影；常规 writer 会 flush，但不承诺每条记录都 <code>fsync</code> 到稳定介质；
- AgentGraphStore 只保存父子拓扑和有限状态，不保存 ResultCard、evidence、投递确认或完整 completion 状态；
- child terminal event 后给 parent 发送 completion 是异步动作，当前没有持久 delivery ack，存在“child 已落盘完成、parent 尚未收到便崩溃”的窗口。

因此，共享结果应遵循明确的顺序：

~~~text
源 tool output / child final 写入既有持久层
        ↓ checked append / 阶段性 flush 成功
EvidenceRecord / ResultCard / publication 关系可恢复
        ↓
更新 SharedContextBoard 热投影
        ↓
向其他 agent 发布 EvidenceId 或 completion
~~~

这需要增加一个能返回规范化 locator 与分层结果的窄 <code>checked append</code> 接缝，并在 child/team 完成边界设置适度的持久化 barrier。<code>LiveThread::append_items()</code> 可能已写完 canonical JSONL、却因后续 thread metadata 更新失败而整体返回错误；paginated SQLite materialization 失败目前则只记 warning，append 仍可能返回成功。新回执至少应区分 canonical append 与 metadata 状态；若还要暴露 SQLite 投影状态，需要继续改造现有 writer。遇到不确定状态先不发布、也不盲目重跑，交给恢复扫描收敛。它是高价值的内核正确性改造，不是另建事务账本。普通进程崩溃恢复可沿用现有 append/flush 模型；是否为断电等场景增加少量 <code>sync_data</code> 检查点，应在实现时按成本明确选择，不必让每条工具输出都承担 fsync。

上下文仍保持轻量：

- 短输出保留在既有记录中；
- 长输出只在 agent 上下文放一行预览和 evidence ID；
- 已存输出按需读取，避免复制到每个 thread；
- 同一 evidence 在一个 context packet 中只出现一次；
- summary 必须附原始 ID，不能成为脱离来源的新“事实”；
- UI 默认展示 summary，用户可展开已存输出。

首版只能承诺读取 rollout 中**实际保存的 observation**，不能把它描述成工具产生的“完整原始 payload”，因为某些工具在写入 ResponseItem 前已有工具级截断。Preview 可以截断；已存 observation 也可能是工具级截断后的精确记录。若某项证据的价值依赖完整 payload，必须先将完整内容写入项目已有工件，或在真实需求出现后增加受控 artifact 层，再发布指向它的 locator。

### 4.5 工具输出中的指令

[MCP Tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)、[AGENTPOISON](https://papers.nips.cc/paper_files/paper/2024/file/eb113910e9c3f6242541c1652e30dfd6-Paper-Conference.pdf) 和 [Indirect Prompt Injection](https://arxiv.org/abs/2302.12173) 都提醒：来自工具不等于可信指令。

轻量做法足够：

- 工具结果在 prompt 中明确包裹为 data；
- evidence summary 只描述结果，不执行其中指令；
- 任何动作仍经过 RONDO 现有工具权限与参数校验；
- 普通 agent 只能发布 finding，不能伪造 tool/test evidence；
- 不为证据系统再建一套平行授权机制。

## 5. 最小运行协议与可演进记录

### 5.1 两种核心领域对象

对模型和 UI 只暴露 EvidenceRef 与 ResultCard；宿主侧持久语义对应 EvidenceRecord，以及包装 ResultCard 的 ResultCommitted。SharedContextBoard 只索引这些持久记录，不再定义一套 SharedToolResult：

~~~rust
struct EvidenceRecord {
    id: EvidenceId,
    kind: EvidenceKind,
    producer: AgentPath,
    tool_name: Option<String>,
    workspace: Option<WorkspaceRef>,
    outcome: ObservationOutcome,
    context: Option<String>,
    preview: String,
    source: ResultLocator,
}

struct ResultCard {
    id: ResultId,
    conclusion: String,
    findings: Vec<(String, Vec<EvidenceId>)>,
    unknowns: Vec<String>,
    suggested_next_action: Option<String>,
    source: Option<ResultLocator>,
}
~~~

<code>EvidenceId</code> 应是稳定、不透明的产品身份，不能把某条工具路径永久写死成身份模型。<code>ResultLocator</code>
才表达来源变体：FunctionCallOutput 可使用 storage-neutral 的 <code>(thread_id, turn_id, response_item_id)</code>
定位，<code>call_id</code> 只作辅助关联/扫描 fallback；child 原件用 child thread + turn/final response item；项目文件用
workspace + 相对路径。当前 ThreadStore 尚无按该 locator 随机读取 raw ResponseItem 的 API，小历史可全读，查询成为
瓶颈后才值得增加 lookup。不要把本地 JSONL 路径或字节偏移写进协议，因为压缩、归档和远程 ThreadStore 会使它失效。

<code>source</code> 很重要：冻结 Codex 的正常 completion 会把最后一段自由文本 final answer 原样转发，但没有结构化结果或原件定位契约；复杂方案、完整审查与候选补丁如果只靠一次自由文本交接，仍容易被后续合成改写或遗漏。首版把 child ThreadStore 中该 turn 的 final response（thread + turn/response item locator）作为原件；补丁、报告等不适合消息保存的内容再引用项目已有文件，不新建 artifact store。ResultCard 只提供短导航和稳定定位。

任务说明起步时继续使用现有 spawn/follow-up 参数，不必先发明通用 DAG。<code>CallKey + SnapshotKey</code> 只属于 ExactReuse 适配器，也不进入基础 evidence 身份。

记录载体的研究结论是分层而非一次建全：已有持久 FunctionCallOutput 与已被接收方写入 rollout 的通信可以用于
验证 capture/locator 接缝，但不构成恢复承诺；若 WBS 选择可恢复产品闭环，需要小型、版本化且默认不进模型上下文的
<code>CollaborationRecord</code> 表达 observed/committed/published 关系，大 payload 继续留在原 ResponseItem 或项目工件。
只有跨 thread 扫描或多消费者查询出现真实压力时，才值得评估 checkpoint 或可由 rollout 重建的 store 投影。

这不是从头建设事件溯源平台，而是让产品状态能够恢复。新 reader 应能跳过未知版本/字段，旧 rollout 正常加载；checkpoint 只是加速器，不是新的真相来源。

### 5.2 一轮协作

1. Root 用现有 spawn 参数生成若干任务说明，明确目标、只读/写入边界、可用工具和输出格式。
2. 多个 agent 获得同一初始任务事实和必要 evidence，但看不到彼此判断。
3. 工具调用完成、源输出得到持久化回执后经 gateway 登记；agent 优先读取已有 EvidenceRef。起步阶段只按 ID 引用；后续只有工具明确声明 shareable 时，才按适配器定义的 <code>CallKey + SnapshotKey</code> 使用 single-flight 或自动命中。
4. 每个 agent 通过 <code>report_result</code> 提交 ResultCard draft；child final 落盘后，宿主用同一 ResultId 追加权威 <code>ResultCommitted</code>，其中包含作者/thread/schema version 与 final/项目工件 locator。
5. Root 对 ResultCard 做声明级归并：一致、互补、冲突、未知。
6. 冲突优先触发一个最小检查；结果先持久化，再投影到 SharedContextBoard。
7. 首版默认只进行一轮定向 follow-up；协议本身允许在持续产生新证据时做有界多轮，而不是全员自由讨论。
8. Root 选择主候选为底稿，吸收证据支持的局部改进，并列出仍未解决的差异。

### 5.3 怎样选“最小检查”

不需要复杂信息增益模型。要求 agent 在 ResultCard 的 <code>suggested_next_action</code> 中给出一个具体动作，root 用简单优先级选择：

1. 已有 evidence 能直接回答的，不再调用工具；
2. 便宜、只读、确定性的检查优先；
3. 能同时区分多个分歧的检查优先；
4. 测试/类型/schema 校验优于再问一个模型；
5. 会修改文件、访问远端或有副作用的动作沿用现有安全流程，不由证据缓存自动触发。

### 5.4 停止条件

首版采用短而硬的默认停止规则，后续调度器可在同一语义上做有界自适应：

- 默认一轮独立产出 + 一轮定向复核；出现新的可区分证据时才允许继续，并受轮数/预算上限约束；
- 没有新 evidence、新反例、新约束或新工件就停止；
- 模型调用或明确幂等、且确认尚未产生副作用的工具失败可重试一次；其他失败交给 root；
- 达到任务预算或用户中断立即取消子任务；
- 仍无法判断时由强 root 决断并附未决项，不制造虚假共识。

永久禁止的是无新信息的无限反思和自由群聊，不是所有多轮协作。这比固定轮数 debate 更省上下文，也更容易解释。

## 6. 强弱模型与分歧处理

### 6.1 不用一人一票

相同模型、相同 prompt 或相同 EvidenceRecord 产生的多个结论不是独立证据。首版根本不需要数值权重系统，只需三条规则：

- 重复意见折叠成一条；
- 有新证据/反例的局部 finding 优先于无证据多数；
- 无法验证时保留主候选，由强 root 负责最终语义判断。

### 6.2 角色分工

| 角色 | 适合产物 | 模型选择倾向 |
|---|---|---|
| 主解决者 | 完整方案、根因、候选实现 | 任务上最强模型 |
| 探索者 | 并行源码/资料定位、不同假设 | 快速或上下文充足模型 |
| Challenger | 反例、遗漏约束、失败场景 | 可较弱，但需具体 |
| Verifier | 测试建议、schema/type/引用核对 | 工具使用稳定的模型 |
| Synthesizer/root | 选底稿、吸收增量、最终表达 | 强模型，保留原件访问 |

“异构”应优先体现为角色和工具不同，而不是为了凑多样性混入模型。DeepSeek、Qwen、GPT 等具体搭配可以后续逐任务试验，首版使用静态 role profile，避免建立模型信誉数据库。

### 6.3 主候选保护

Root 的合成输入不是“几段摘要”，而是：

~~~text
base candidate（完整原件）
other ResultCards
accepted local improvements + evidence IDs
rejected suggestions + short reason
unresolved minority report
~~~

主候选默认是由最强配置的 primary solver 产出的完整原件，但“模型更强”不等于答案一定正确。弱 agent 可以凭一个复现测试修正或替换主候选的局部错误，却不能靠更长的文字、更高自信或更多同意票整体覆盖它。合成器只改已定位的部分，避免重新生成时丢失原有正确细节。

### 6.4 无客观检查时

开放设计问题仍需模型判断。首版无需建设复杂 judge 集群，只做：

- 隐藏候选作者与模型身份；
- 使用同一结果卡格式，限制 preview 长度；
- root 先列硬约束再看候选；
- 必要时交换候选顺序复看；
- 判断不稳时保留分歧，不强求共识。

[FairEval](https://arxiv.org/abs/2305.17926)、[LLM-as-a-Judge](https://arxiv.org/abs/2306.05685) 与 [Rethinking Mixture-of-Agents](https://arxiv.org/abs/2502.00674) 的意义在这里是提醒实现者防止位置、长度和弱聚合偏置，不是要求建立学术裁判平台。

## 7. 适合 RONDO 的实际工作流

### 7.1 并行源码/资料调查

~~~text
root：拆成架构、测试、历史、外部资料
  ├─ explorer A：源码定位
  ├─ explorer B：测试与行为
  └─ explorer C：论文/官方资料
SharedContextBoard：文件片段、命令结果、来源快照
root：按原始引用综合，必要时追问一个冲突点
~~~

特点：

- 全部只读，共享同一 workspace snapshot；
- 每人搜不同区域，避免重复；
- <code>rg</code>、文件读取和网页来源可按 ID 引用；
- 适合宽搜，是首版最容易体现价值的场景。

### 7.2 主方案 + 独立审查

1. 主解决者基于任务和已有 evidence 产出完整候选。
2. 两个 reviewer 不先看彼此意见，分别检查：
   - 需求/架构/兼容性；
   - 反例/测试/安全与边界。
3. reviewer 返回短 ResultCard 和精确 evidence refs。
4. root 将 review 定位到候选的具体声明，不要求重写全文。
5. 能验证的争议执行一次检查；主候选只做局部修订。

这适合 plan 审查和代码审查，也正面解决弱 reviewer 重写强作者的问题。

### 7.3 Bug 诊断

角色可以是：

- reproduction：稳定复现并登记失败输出；
- code path：追踪相关状态和调用链；
- alternate hypothesis：寻找不同根因；
- verifier：设计最小区分测试。

所有人共享同一失败 evidence，但私下形成根因判断。Root 对假设做差异表，只选择一个区分度最高的检查。确认根因后再派实现 agent，避免多个 agent 同时盲改。

### 7.4 计划审查

主方案保留为 child final 或项目文件，审查者只提交：

~~~text
结论：缺少恢复失败语义
证据：源码目前只有一次性 run 路径 [E17, E23]
未知：resume 接口是否由另一个模块承接
判别动作：读取 registry/residency 的恢复路径
~~~

Root 读取一次补充源码证据后决定是否在原计划中加入对应小节。审查意见不会成为一个与原计划竞争的全文。

### 7.5 并行实现（后期能力）

只读协作稳定后再做：

1. 每个写 agent 自动获得独立 worktree；
2. 任务说明标明基线 commit、允许修改范围和输出 commit；
3. 每个 agent 的测试结果只绑定其 worktree；
4. 单一 integrator 选择/合并 commit；
5. 组合后的新 tree 重新运行必要检查；
6. 分支/工作树的创建与清理由 RONDO 自己标记所有权，不碰来源不明对象。

不要让多个写 agent 共享 cwd。独立 thread 并不等于文件系统隔离；task owner 也不等于文件 owner。

## 8. 冻结 Codex 与教师源码的可复用部分

### 8.1 RONDO / 冻结 Codex v0.147.0

**[源码]** 本次逐文件比对确认，RONDO 当前的 multi-agent handlers、agent control/spawn、inter-agent context 与相关 TUI 关键实现和冻结 Codex 快照一致；以下行为判断以该冻结源码为准。

- <code>codex-rs/core/src/tools/handlers/multi_agents_v2/spawn.rs</code>
- <code>codex-rs/core/src/agent/control/spawn.rs</code>
- <code>codex-rs/core/src/tools/handlers/multi_agents_v2/{send_message,followup_task,wait,interrupt_agent,list_agents,message_tool}.rs</code>
- <code>codex-rs/core/src/tools/handlers/multi_agents_common.rs</code>
- <code>codex-rs/core/src/agent/{registry.rs,control/execution.rs,control/residency.rs}</code>
- <code>codex-rs/core/src/context/{inter_agent_message.rs,inter_agent_completion_message.rs}</code>
- <code>codex-rs/core/src/thread_manager.rs</code>
- <code>codex-rs/core/src/session/{mod.rs,turn.rs}</code> 与 <code>core/src/tools/parallel.rs</code>
- <code>codex-rs/thread-store/src/{live_thread.rs,local/live_writer.rs}</code>
- <code>codex-rs/rollout/src/{recorder.rs,policy.rs}</code>
- <code>codex-rs/agent-graph-store/src/store.rs</code>

现有能力：

- <code>spawn_agent</code> 支持 <code>fork_turns=none|all|N</code>、模型、effort、service tier 和角色；
- agent 有独立 thread、稳定 task path、生命周期和容量控制；
- 有定向消息、follow-up、等待、中断、恢复和树状枚举；
- child 继承 provider、approval、sandbox 和 cwd；
- fork 时会过滤 reasoning、工具调用/输出和 inter-agent communication，而不是复制完整思维轨迹。

这个 fork 过滤行为与本方向天然兼容：私有工具轨迹目前不会盲目灌入子 agent；缺少的是单独、可选择投影的共享 evidence。

当前缺口：

- inter-agent message 主体仍是自由文本 <code>content: String</code>；
- 正常 completion 会原样转发最后一段自由文本 final answer，但没有结构化结果/原件引用契约；源码中的 1000-token 常量只截断 errored status 文本，不限制 completed message；
- 没有 EvidenceRecord/ResultCard/原件定位契约；
- 工具结果属于各 thread history，没有 session task 级共享索引；
- 子 agent 共享 cwd，没有每个 writer 自动 worktree；
- 没有声明级分歧、最小验证和主候选保护。
- 当前 MultiAgentV2 的 <code>non_code_mode_only</code> 默认开启；编码协作不能只靠 UI 放开，必须先补写入隔离与集成语义。

因此实现策略应该是：先沿现有控制面切入一条最小完备纵向闭环，再把稳定下来的协作语义抽成内核边界。它不是重写全部 multi-agent，也不承诺永远只是薄层：

~~~text
tool execution result
  └─ checked persistence → EvidenceRecord
       ├─ current thread keeps normal ToolOutput
       └─ CollaborationRuntime updates hot projection

spawn/followup context projection
  └─ attach selected evidence refs/previews

agent completion
  └─ persist ResultCommitted + final locator → recoverable notification

root / scheduler
  └─ compare cards → bounded checks → synthesize
~~~

#### 启动接缝与目标内核边界

本次只读核验还确认：同一 agent tree 的根与 child 会 clone 同一个 <code>AgentControl</code>；每个 child 则有独立 Session、ContextManager 和 rollout。因此 <code>AgentControl</code> 是启动共享 runtime 的自然接缝：

~~~text
core/src/agent/control.rs
  AgentControl
    + collaboration: Arc<CollaborationRuntime>

CollaborationRuntime
  ├─ Evidence/Result Catalog + SharedContextBoard
  ├─ Context Projection
  ├─ Scheduler / Task Runtime（按阶段抽出）
  └─ Workspace Manager（开放多 writer 前抽出）
~~~

源码接缝分析表明，runtime 可以位于 core 内并由 <code>AgentControl</code> façade 隔离，避免把任务、证据、调度和
workspace 状态全塞进一个结构。EvidenceId 应使用稳定、不透明身份，工具来源由第 5.1 节的 typed locator 表达；
不应把 <code>thread_id + call_id</code> 固化成所有证据的永久身份。具体切片由 WBS 决定。

工具结果管线至少有三个不同职责，不能伪装成一个 hook：

~~~text
core/src/tools/parallel.rs
  ToolCallRuntime：成功返回 AnyToolResult 时保留 call/tool/workspace 元数据

core/src/session/{turn.rs,mod.rs}
  drain_in_flight() → record_conversation_items()
  checked record API：返回补齐 turn/item ID 后、确已写入的 locator 或错误

core/src/agent/collaboration/*（候选边界）
  persist EvidenceRecord / update board / project selected refs
~~~

<code>ToolRegistry::dispatch_any_with_terminal_outcome()</code> 是直接工具成功结果的来源，但 <code>AnyToolResult</code> 还要在 <code>ToolCallRuntime</code> 中转换成模型可见的 ResponseInputItem，最终由 <code>drain_in_flight()</code> 写入 conversation history。原始 ResponseItem 的宿主 ID 是在 <code>record_conversation_items()</code> 内部 clone 后才补齐，现有 API 又返回 <code>()</code>；所以“drain 后读原对象并登记”拿不到可靠 locator，checked API 应返回规范化且已持久化的 item/receipt。

直接工具路径形成且获得持久回执的 FunctionCallOutput 是最窄的候选 observation 来源，包括带明确输出的失败结果；
EvidenceRecord 必须保留状态，不能把 <code>success=false</code> 等同于“没有 observation”。Unsupported tool、hook block、
未形成可共享 output 的 handler error、CustomToolCallOutput、ToolSearchOutput、provider-native WebSearch 与 Code Mode
走不同路径，需要各自适配后才能宣称覆盖。ExactReuse 必须在 dispatch **之前**另加 lookup；写工具结果可以被引用，
但绝不因此缓存或代替再次执行。

研究中用两个内部原语说明最小语义：

~~~text
read_shared_evidence(ids?)
report_result(conclusion, findings[{text, evidence_ids}], unknowns, suggested_next_action?)
~~~

- <code>read_shared_evidence</code> 只接受 root 已发布给当前 task 的 ID，并从热索引或持久来源读取已存输出；起步阶段不提供全局枚举；
- <code>report_result</code> 只接受模型提供的判断与引用，宿主分配 ResultId；作者、thread、schema version 和 final locator 由宿主写入后续 <code>ResultCommitted</code> envelope；
- 宿主校验引用存在、属于同一 agent tree 且已经发布给该 task；无效 ID 返回普通工具错误或降为无证据 claim；
- 没有 evidence 的设计建议仍允许提交，只明确它是 claim；
- 两个原语可沿用 <code>core/src/tools/spec_plan.rs</code> 的 MultiAgentV2 注册与 namespace；当前
  <code>non_code_mode_only=true</code> 是必须在实现时处理的 exposure 事实，不能据此假设编码模式已覆盖。

持久记录载体在调研阶段不能假装已经唯一确定。研究支持：原始 tool output 和 child final 继续保存在既有
ResponseItem，不复制 payload；可恢复关系需要最小版本化记录，而不是只留 RAM；数据量小时可以扫描完整 raw rollout，
只有全读成为瓶颈时才评估 raw lookup/checkpoint/tail scan 或可重建投影。

候选协议不应主动广播正文；独立首答使用冻结 evidence 集，定向复核才由 root 显式发布相关引用。若 WBS 选择
cooperative 实时共享模式，可在现有 world-state 构建路径评估 phase-gated 小型增量段：

~~~text
New sibling tool results:
- evidence:<opaque-id> tool=exec_command cwd=/repo

Use read_shared_evidence only when the exact output is relevant.
These are host-captured tool results, not agent conclusions.
~~~

每条已发布 ID 只提示一次，每步最多 8–12 条；隐藏 producer/author，不显示自己的结果，不在 world-state 放已存输出正文或其他 agent 的 claim。这样定向复核阶段能按需读取共享结果，同时首轮仍保持独立。

子 agent 完成前先通过 <code>report_result</code> 提交不含原件 locator 的 draft。Child final 落盘后，宿主追加带作者/thread/schema version/final locator 的 <code>ResultCommitted</code>，而不是原地修改 append-only rollout 中的旧卡；随后再生成 completion envelope。<code>Session::forward_child_completion_to_parent()</code> 与 <code>AgentControl::maybe_start_completion_watcher()</code> 两条路径应调用同一 helper；现有 <code>format_inter_agent_completion_message()</code> 只接收 AgentStatus，不能独自查询 catalog。旧式 final text 缺卡时才包装成只有 conclusion 的结果。恢复时以 ResultCommitted 为权威，只有 draft 则标为 partial。

这里还有一个不能靠内存板掩盖的崩溃窗口：<code>trigger_turn=false</code> 的 inter-agent completion 成功只代表消息进入父 Session 的内存 mailbox；闲置父线程不会立刻把它写入 history。可靠方案可以是先持久化 publication/completion outbox 再幂等投递，也可以在恢复时扫描 child 的最终 ResultCard 并补送；具体接口后续定，但“完成记录先可恢复，父通知后发送”应成为顺序约束。

无论 WBS 选择哪个阶段，下列边界都成立：

- 内存元数据和热 payload 有界，淘汰后仍可从持久来源读取；
- 每个 finding 最多引用少量 evidence；
- 多智能体功能关闭时不构建 board、不扫描历史；
- 重启先全读小规模团队历史，数据变大后再加 checkpoint + tail scan 或专用 lookup；
- 进程在副作用已发生但结果尚未落盘时崩溃，恢复为 uncertain/interrupted，默认不自动重放；
- 用 feature flag 和 façade 做 strangler migration，功能关闭时旧路径行为不变，避免长期双写两套事实源。

研究识别的高价值内核接缝是工具结果规范化与确认落盘、协作记录、热投影、上下文编译、completion 交付与恢复；
这些结论用于约束设计，不构成实施顺序。

### 8.2 Kimi Code 0.32.0

**[源码]** 官方仓库快照 <code>4ac7240fff595b41a94a63c4b4ca74840ad95cf8</code>，MIT。

值得借：

- 每 agent 独立 context/memory；
- profile 化工具和模型；
- foreground/background、resume/cancel/retry；
- 有界 swarm 并发、排队、rate-limit handling；
- lifecycle event 与逐任务 usage；
- agent 独立 homedir/journal。

不要照搬：

- 子 agent 仍共享项目 cwd；
- 父侧主要收到蒸馏后的自然语言 summary/XML；
- summary 可能丢失主候选原件和 evidence provenance。

### 8.3 OpenCode 1.18.13

**[源码]** 官方仓库快照 <code>a105350812f05f914c768e468559dbd6bd508d8e</code>，MIT。

值得借：

- child session 的 <code>parentID</code> lineage；
- 子 agent 权限只能收窄；
- 默认限制 subagent depth；
- background promotion、notification、cancel/resume；
- 已有 project copy/git worktree primitive。

缺口是 TaskTool 没把 child session 自动接入 worktree primitive，结果仍以文本 <code>&lt;task_result&gt;</code> 注入父侧。RONDO 可借 session 与 worktree 基础，但应自己连接“写 worker → 独立 worktree → 单一 integrator”。

### 8.4 OpenHands SDK 1.40.0

**[源码]** 官方仓库快照 <code>2f27653959f7596769427ee4657247b32c94504e</code>，MIT。

最值得借的是 Action/Observation event stream：它已经把“发起动作”和“环境返回结果”分开，是 EvidenceRecord 的自然输入。还可借独立 conversation、task resume/close/metrics 与 conversation-level worktree。

不要误以为已有每个 delegate 一棵 worktree：同一 conversation 中多个 task/delegate 仍共享 workspace，父侧也主要得到 final text。

### 8.5 Claude Code 社区重建的来源边界

本地 <code>reference-agent-harness/claude-code</code> 不是 Anthropic 官方源码，没有可确认的官方版本、git provenance 或许可证；README 明示它是社区近似重建并限制直接复制。因此本文只把下列内容当概念启发，不把行为写成官方事实，也不复制实现：

- task DAG、owner 和原子领取；
- coordinator-only workflow；
- mailbox/lifecycle；
- 可选 per-agent worktree；
- 退出前检查 dirty/unmerged；
- leader 消化研究后给实现者 self-contained spec。

该重建的 team 路径也没有自动为每个成员建立 worktree，task owner 不能解决文件冲突。

### 8.6 跨项目结论

四个可运行开源实现已经较好解决了：

- 独立 session/thread；
- 生命周期、并发与后台任务；
- 角色、工具和权限；
- 消息与自然语言 summary。

它们共同缺少的是：

- 运行时工具结果的一次注册、多 agent 引用与 single-flight；
- “短摘要 + 完整原件 + evidence refs”的交付；
- 私有初答后才开放分歧；
- 主候选为底稿的增量合成；
- 并行 writer 的默认隔离与单一集成。

这说明 RONDO 可以做出有辨识度的创新，而不必先造一个庞大的新框架。

## 9. 研究交接

本调研曾据研究结果推导出从最小只读闭环到多 writer 的候选分层。为避免研究报告成为第二套实时路线，
阶段顺序、首个产品切片、分层触发条件与验收口径已统一迁入
`doc/WBS/multi-agent-trusted-evidence.md`。本文其余章节只保留该路线背后的对象语义、源码证据、候选产品形态、
测试关注点和复杂度边界；它们不决定何时实施。

## 10. 候选运行语义（研究结论，不是实施路线）

### 10.1 持久来源与数据热路径

SharedContextBoard 只需要热索引，不保存第二份权威 payload：

~~~rust
struct SharedContextBoard {
    by_id: HashMap<EvidenceId, Arc<EvidenceRecord>>,
    visible_to: HashMap<AgentPath, HashSet<EvidenceId>>,
}
~~~

<code>visible_to</code> 是持久 EvidencePublished/定向交接关系的运行时投影，不是第三种事实。Root 的发布 helper 应先让关系可恢复，再更新集合和发送 ID；<code>read_shared_evidence</code> 只做 membership check，不提供全局列表。这样第一轮独立与定向发布是可执行边界，而不只是提示词约定。

设计重点：

- payload 用 <code>Arc</code> 或持久 locator，不在 agent 间复制；
- preview 在登记时确定性生成一次；
- context builder 只拷贝小字段，大 payload 懒加载；
- board 可随 team 结束、LRU 或进程退出释放，持久原件与协作记录不因此删除；
- 研究非目标包括跨 session 全局缓存。

若未来 WBS 选择 ExactReuse，可为适合的工具增加独立 <code>by_call</code> 状态。可以用 watch/oneshot 广播可克隆结果，或显式 <code>Running { leader, waiters } / Ready</code>；失败、取消和 waiter 清理属于该工具适配器，不能假定任意 Future/Error 天然可共享。

### 10.2 上下文预算

每个 EvidenceRef 默认只投影：

~~~text
[E17 test] fixed-pytest: exit 1, 2 failed / 141 passed
scope: worktree X @ snapshot Y
get: evidence.get(E17)
~~~

一条 evidence 在同一 prompt 中只出现一次。ResultCard 要有短字段上限；完整内容由 child final locator 或已有工件承载。Root 合成时先读 cards，只对关键冲突下钻。这样 agent 数量增长不会线性复制所有工具输出。

### 10.3 并发与背压

从工程经验看，默认 root + 2 workers 足够形成并行价值；允许配置到 3–4，但不应默认大 swarm。调度器至少限制：

- 同时运行的模型调用；
- 同时运行的重工具；
- 单任务 agent 数量；
- ResultCard 与预览大小；
- follow-up 轮数。

若 provider rate limit，排队而不是立刻复制任务；取消 root 时向所有 child 传播 cancellation；一个 child 失败不取消已经完成的其他结果。

### 10.4 恢复是产品能力，不是内存缓存的附加项

下面是 RONDO **需要实现**的恢复规则，不是冻结 Codex 已经具备的行为。AgentGraphStore 只保存部分父子边及 Open/Closed，child 正常完成并不会自动把边标成 Closed；现有 V2 residency 主要恢复身份和模型 history，不会重建 ResultCard，也不会把旧 Running 自动标成 interrupted。

小团队的首个正确实现可以很朴素：

1. 优先从 AgentGraphStore 的全状态边发现 descendants，用 SessionMeta 的 parent 关系修复/兜底；缺边、graph 不可用或恢复不完整时显式降级。只有实作证明这两层仍不足，才增加 TeamMemberAttached 一类协作记录。
2. 对 root 和所有可发现 descendant 调用 <code>ThreadStore::load_history(include_archived=true)</code>，全读 raw rollout。现有 loader 会累计但未向该调用方充分暴露 parse errors；恢复接缝必须返回 completeness/parse diagnostics。扫描量超过上限或尾部损坏时报告 partial/incomplete，而不是静默丢弃早期 evidence。
3. 按稳定 EvidenceId/ResultId 幂等重建 observation、ResultCard 和 publication 关系；重复扫描或重复投递不会复制逻辑记录。
4. 有 FunctionCall 而无对应 output、旧 Running 状态或崩溃窗口中的副作用调用恢复为 interrupted/uncertain；只读或已证明幂等的动作才允许显式重新核验。
5. 已提交 ResultCard 但父 completion 缺失时，按 ResultId reconcile 并补建父视图；child final locator 不可解析时保留卡片但明确标为 missing。
6. 可恢复协作要求 child 使用 durable ThreadStore。若允许 ephemeral/InMemory child，结束前必须把 ResultCard 及被引用的 final/observation 内容复制到 root 的持久记录或项目工件；只复制一个会失效的 locator 不够。否则应明确属于不可恢复模式。

典型崩溃窗口及语义：

| 崩溃位置 | 恢复行为 |
|---|---|
| 工具有副作用，output 尚未落盘 | uncertain，不自动重放 |
| canonical output 已写，board 尚未更新 | 扫描后补回 |
| ResultCard 已提交，child final 尚未形成 | 保留 partial，agent 标 interrupted |
| child result 已提交，parent mailbox 尚未持久化 | reconcile 后幂等补送/补建视图 |
| SQLite/metadata 投影落后 | 从 canonical rollout 重建 |
| JSONL 尾部损坏/存在 parse error | 忽略不可解析尾部并显式标 partial，禁止声称完整恢复 |
| locator 目标缺失或歧义 | 标 missing/ambiguous，不当作有效证据 |

数据增长后再把全读升级为 raw locator lookup、checkpoint + tail scan 或可重建 SQLite 投影。不要用 <code>load_latest_model_context()</code> 代替完整 evidence 恢复：compaction 后它可能只保留恢复模型所需的 suffix。

### 10.5 兼容、版本与保留

- 未开启 team/evidence 模式时，现有行为不变；
- 老模型仍可返回文本，adapter 将其包装为只有 conclusion 的 ResultCard；
- 不认识 EvidenceId 的模型看到可读 preview，不会完全失效；
- 旧 rollout 没有 CollaborationRecord 时正常加载，可按支持的 ResponseItem 做尽力恢复并明确能力边界；
- 每条持久 CollaborationRecord envelope 统一携带小整数 <code>schema_version</code>、作者与 thread 等宿主字段，EvidenceRecord/ResultCard payload 不再维护第二份版本来源；reader 用 lazy upcast/optional 字段，尽量不重写历史；
- rollout 是 canonical history，SQLite/CollaborationStore 只是可重建投影，不把双写结果变成两份真相；
- 内存可自由 LRU，evidence 生命周期跟随所属 team/thread；现有 hard-delete 引用保护只理解 fork history，不理解 root evidence → child rollout。若实现持久证据，需要以整棵 team 为保留/删除单位，或加入窄的引用保护；压缩/归档继续复用现有机制，不另建 evidence GC。大型 artifact 与跨 session 保留需由真实需求触发；
- 自由文本 inter-agent message 保留用于协调，关键结果和发布关系走可恢复记录。

## 11. 候选产品形态（研究结论，不是实施路线）

### 11.1 一个明确入口

候选入口形态是：

~~~text
/team <任务>
~~~

其候选语义是“本轮使用多智能体协作”，不是学术式准入判断。天然可并行时可以分片，不适合并行时可采用
“主方案 + 审查者”；是否采用该命令形态由 WBS 后续任务决定。

可选的 <code>/team on|off</code> 作为会话级实验开关，但用户不应被要求手选模型、角色、并发数或配置文件。自然语言明确要求多智能体时，与 <code>/team</code> 等价。

### 11.2 复用现有 TUI

**[源码]** RONDO 与冻结 Codex 的：

- <code>tui/src/multi_agents.rs</code>
- <code>tui/src/app/agent_status_feed.rs</code>

当前相同，已经具备 <code>/agent</code> 线程选择、Alt+左右切 thread、状态/最近活动预览，以及 Spawn/Wait/Resume/Close 生命周期事件的渲染。Picker 本身不是这些操作的控制面。这证明现有线程导航与事件投影可作为候选复用点。

若实际使用证明需要聚合视图，候选形态是原地更新、默认折叠的 team card；下例只说明信息层级，不是 UI 实施计划：

~~~text
┌ 协作：修复配置加载错误              2/3 完成
│ ✓ repo_scan [只读]     找到 config/load.rs 的失败路径
│ ● implement [worktree] 正在运行相关测试
│ ! review [只读]        发现一个兼容性分歧
│
│ 共享结果 6 · 已复用 2 · 分歧 1
└ Enter 展开 · /agent 查看线程 · Esc 停止
~~~

展开后才展示完整任务说明、最近工具活动、ResultCard、共享结果与分歧；正常主对话只在整体完成、真正需要用户选择或整体失败时新增消息，避免被 Spawn/Wait 流水刷屏。

### 11.3 分歧卡

~~~text
分歧：缺少配置项时应报错还是回退默认值？

A · implement：保持兼容并回退
    依据：E4、现有调用方 foo.rs

B · review：立即报错
    依据：E6、README 的失败语义

判别动作：只新增一个旧配置测试来区分
~~~

用户平时不需要看到 EvidenceId；复用时显示：

~~~text
↻ 复用 implement 的测试结果：pytest tests/config -q ✓
~~~

需要时再展开原始输出。

### 11.4 并发研究边界

冻结 Codex 当前 V2 的默认总并发配置为 4；subagent limiter 限制活跃执行，不限制持久 thread 数。研究只支持
“小团队、无 all-to-all、保留 verifier 容量”作为低风险起点，不能据此冻结 RONDO 的默认 worker 数、深度或模型组合；
这些参数必须由 WBS 中的实际任务和资源测量决定。

### 11.5 候选失败、停止和恢复语义

- 一个非关键 child 失败，root 使用已有结果继续；
- 临时模型错误可在同一 thread 自动恢复一次；工具只在明确幂等且能确认未产生副作用时重试；
- 第二次模型失败或不安全重试的工具失败停止自动处理并显示原因；
- 超时 child 返回 partial，已登记 evidence/finding 仍可用；
- <code>Esc</code> 或 <code>/team stop</code> 停止整组，保留已完成结果；
- 在 <code>/agent</code> 中可单独中断成员；
- 若实现 resume reconciler，应复用 AgentPath、thread、raw rollout 和协作记录重建卡片；这不是现有 Codex residency 已有保证；
- 恢复规则把旧运行中调用标为 interrupted/uncertain，不能假装已完成；
- 不等待最慢 child 才开始处理先返回结果。

### 11.6 候选写入隔离边界

若开放编码协作，必须做到：

- 干净 Git 项目：写 agent 自动进入项目规定的独立 worktree；
- root 是唯一 integrator；
- 成功集成且无剩余修改的临时 worktree 才能自动清理；
- 冲突、失败或未集成改动必须保留并展示路径；
- 起始工作区有未知修改：退化为当前工作区只有一个 writer，其他 child 只读，不 stash、不覆盖；
- 非 Git 项目：同样退化为单 writer，不引入 overlay filesystem。

多智能体不增加平行授权体系。Child 以根会话现有 sandbox/工具/审批语义为基础；只读 child 必须由宿主强制收窄，
writer 必须绑定 owned worktree。证据层不缓存、合并或解释审批，只有实际执行完成并得到持久回执的工具结果才可能共享。

## 12. 候选验收关注点（研究结论，不是测试计划）

若 WBS 启动实现，以下是研究识别出的正确性风险，不是当前测试计划。

### 12.1 功能正确性测试

内核接缝需要覆盖：

- 功能开关关闭时旧 multi-agent 行为与 rollout 形状不变；
- checked record 返回规范化 locator，并至少区分 canonical append 与 metadata 结果；若阶段实现了 SQLite 状态出口，再验证投影失败不污染 canonical 真相；
- 持久结果不确定时不向其他 agent 发布，但也不盲目重跑可能已有副作用的工具。

可恢复只读闭环需要覆盖：

- EvidenceId 能读取到正确的已存 FunctionCallOutput；
- 引用存在、属于同一 agent tree 且已经发布给当前 task；
- 未显式发布的 agent 推理和私有历史不会进入其他 child；
- ResultCard 能定位 child 已存 final，主候选不会因自由文本合成丢失；
- child 失败/取消后已经完成的结果仍可用；
- 进程重启后能重建 evidence、ResultCard、发布关系和主候选 locator；内存 board 淘汰不造成持久信息丢失；
- output 已落盘但 board 未更新时可补回，ResultCard 已提交但 parent completion 丢失时可 reconcile；
- dangling/旧 Running 调用恢复为 interrupted/uncertain，missing/ambiguous locator 不被当作有效结果；
- 旧 rollout 与未知可选字段仍能加载，扫描不完整会显式报告 partial；
- read-only worker profile 的 child 不能写当前工作区；
- root 是唯一 writer，重型工具仍走原有入口和全局互斥。

只有实现对应能力时才需要覆盖：

- ExactReuse 的 CallKey/SnapshotKey 命中和 <code>fresh=true</code>；
- 副作用调用不自动重放；
- publication/completion 重投按稳定 ID 幂等；
- checkpoint/tail scan 或索引投影与 canonical rollout 一致，投影损坏可重建。

开放多 writer 时还必须验证每 writer 独立 worktree、单一集成和合并后复验。

这些是普通测试体系的一部分，不是建立一套“可信审计测试”。

### 12.2 少量调优观察

可观测性候选包括：

- 任务完成质量与用户返工情况；
- 总 Token 与 wall time；
- 重复工具调用、显式复用和已实现时的 single-flight 命中；
- child failure 和冲突/返工情况。

这些数据回答“哪里值得继续优化”：

- 若共享结果几乎不被复用，检查任务拆分是否重叠；若已实现 ExactReuse，再检查键是否过严；
- 若大量 follow-up 无新信息，收紧 ResultCard 和停止规则；
- 若 reviewer 常修正主候选，增强 challenger/verifier profile；
- 若 reviewer 常制造噪声，缩小其任务和输出范围。

可以保留强单体、Self-Consistency、独立候选和自由 debate 作为小规模对照，帮助理解哪条协议起作用；无论结果是否全面占优，都不影响该功能继续作为工程与创新路线演进。

## 13. 研究复杂度边界

### 稳定非目标

这些能力与本路线的核心价值不一致，除非产品目标发生根本变化，否则不建设：

- 合规/取证型本地审计平台、完整 provenance graph、W3C PROV/in-toto/SLSA 全模型；
- PKI、签名链、透明日志、区块链、分布式共识或一套平行 ACL/ABAC/审批系统；
- 全局真假标签、trust score、长期 agent 信誉排名、在线学习路由器或 judge 集群；
- 全量 transcript/CoT 广播、一智能体一票、自由群聊、无限反思或固定大 swarm；
- 通用缓存一致性、任意副作用透明重放；
- 多 writer 共享 cwd；
- 为证明全面胜过单体而建设庞大学术 benchmark 或 admission/kill gate。

### 候选扩展点与触发条件

这些不是当前路线，只是研究阶段识别出的接口与触发条件；是否采用及顺序只见 WBS：

- 最小 CollaborationRecord 与可重建 CollaborationStore：只有扫描/消费者增多后才值得拆层；
- artifact/blob 层与跨 session 工件复用：已有 rollout/项目文件不足时再加入；
- Task Runtime、通用 DAG、更多 observation adapter 与动态验证轮次：按实际协议复杂度触发；
- Workspace Manager、多 writer 文件边界与非 Git workspace：只在开放额外 writer 前触发；
- 更精确的外部文件变更探测、更丰富 cache policy 和模型/角色默认值；
- 多进程、远程 worker、跨主机 agent 及其必要身份机制。

checked persistence、ResultCard 的持久提交和基本重启恢复不在延后清单里，它们是“共享证据最终不能只存在内存”的最低完整性。反过来，“未来可能有用”也不足以让某个阶段同时建设全部扩展点。

## 14. 研究结论

若 RONDO 按 WBS 启动多智能体实现，研究证据支持把它做成紧凑、好用、有辨识度的工程功能：

1. 复用冻结 Codex 已有的 thread、agent graph、spawn/wait/resume 和 TUI；
2. 以 AgentControl façade + CollaborationRuntime 建立演进接缝，逐步抽出证据、任务、调度、上下文和 workspace 职责；
3. 用持久 EvidenceRecord/ResultCard + child final/工件 locator 保存可恢复语义，SharedContextBoard 只负责热索引和上下文投影；
4. 补齐规范化 ID、checked canonical append、completion reconcile 和基本重启恢复，不把内存状态伪装成持久状态；
5. 保持 agent 私有上下文，先独立产出，再围绕具体分歧做有界验证；
6. 以主候选为底稿吸收局部证据增量，不投票、不让弱 summarizer 重写；
7. 首个候选闭环适合调研、plan review、code review 和 bug diagnosis，并由宿主强制 read-only worker；Task Runtime、更多 observation adapter 与 ExactReuse 是否扩展由使用证据决定；
8. 开放第二个 writer 前完成 Workspace Manager，以每 writer 独立 worktree、单一 integrator 和组合后复验保证编码协作。

这个方向同时满足三个目标：

- **有实际价值**：减少重复工具调用和上下文复制，提高审查、诊断与调研协作质量；
- **有创新性**：共享运行时观察、隔离 AI 判断，并把分歧编译成验证动作；
- **有工程锻炼价值**：涉及异步调度、结构化协议、持久化、上下文编译、缓存、恢复、TUI 和 worktree 集成，并允许逐步形成真正的协作内核。

研究上最小且可验证的候选闭环不是“让更多 agent 开会”，而是：

> **原件与协作记录先可恢复 → 工具结果一次注册、多方引用 → 独立 finding → 有界判别验证 → 主候选局部合成。**

这条闭环与现有开源实现形成明显差异。这里的高效不等于永远少改代码，而是每一份新增复杂度都应直接服务证据复用、恢复、协作质量或写入正确性；拒绝的是低收益的系统重造，不是必要的深层改造。何时实现以及采用哪些层次只由 WBS 决定。

---

## 附录 A：关键资料卡

以下资料用于解释设计来源与边界，不构成是否实现多智能体的门槛。

### A.1 多智能体与聚合实证

| 来源 | 对实现最有用的结论 | 局限 |
|---|---|---|
| [Capable language models can outgrow the benefits of collaboration](https://www.nature.com/articles/s42256-026-01268-y), 2026 | 任务可分解性与验证拓扑比 agent 数量重要；中心验证减少错误传播 | 六类 benchmark，经验阈值不可普适化 |
| [Reasoning in Token Economies](https://aclanthology.org/2024.emnlp-main.1112/), EMNLP 2024 | 多轮历史开销快，独立采样是必须理解的基线 | 不能覆盖长期代码 agent 的全部状态问题 |
| [Large Language Models Cannot Self-Correct Reasoning Yet](https://openreview.net/forum?id=IkmD3fKBPQ), ICLR 2024 | 无外部反馈的反思/辩论不稳定；新一轮应带来新观察 | 严格对照集中于少量协议 |
| [Debate or Vote](https://proceedings.neurips.cc/paper_files/paper/2025/hash/934252acd87f254d5d4672fbde283bd2-Abstract-Conference.html), NeurIPS 2025 | 初始独立候选贡献了辩论的大部分价值，更多轮常退化 | 同模型样本仍相关 |
| [Improving Factuality and Reasoning through Multiagent Debate](https://proceedings.mlr.press/v235/du24e.html), ICML 2024 | 候选互评有潜力，适合转化为定向反例检查 | 未严格匹配总响应/Token |
| [ReConcile](https://aclanthology.org/2024.acl-long.381/), ACL 2024 | 真正异构模型在部分任务提供互补信息 | 小样本、预算和自报置信度不可直接比较 |
| [Mixture-of-Agents](https://arxiv.org/abs/2406.04692) | 分层候选和 aggregator 是可行工程形态 | 预印本、总 Token 未匹配、judge/长度偏置 |
| [Rethinking Mixture-of-Agents](https://arxiv.org/abs/2502.00674) | 强模型原件质量通常比混入弱模型的表面多样性重要 | 任务与指标仍有限 |
| [MacNet](https://openreview.net/forum?id=K3n5jPkrU6), ICLR 2025 | 工件传播、宽度和稀疏拓扑优于无差别稠密通信 | 公平成本控制有限 |
| [Talk Isn't Always Cheap](https://arxiv.org/abs/2509.05396) | 正确 agent 可能被错误同伴翻错；先独立后有限交流 | 预印本、短协议 |
| [Social Dynamics as Critical Vulnerabilities](https://aclanthology.org/2026.acl-long.1756/), ACL 2026 | 人数、感知能力、长度与模型家族会诱发从众 | 人工注入错误同伴，不能外推所有任务 |
| [Faulty Agents](https://arxiv.org/abs/2408.00989) | 不应相信“已修好”的文字，要看实际测试/代码；Challenger/Inspector 有用 | 预印本、旧模型与短任务 |
| [MAST](https://arxiv.org/abs/2503.13657), NeurIPS 2025 | 真实失败集中在重复、动作错位、验证与停止；显式验证能改善 | 框架、模型和任务混杂 |
| [Self-Consistency](https://arxiv.org/abs/2203.11171), ICLR 2023 | 独立候选本身就是强方法；必须与协作效果区分 | 高采样成本、相关系统错误 |
| [Prover-Verifier Games Improve Legibility](https://openai.com/index/prover-verifier-games-improve-legibility/) | 主候选应面向较弱 verifier 生成可检查、可引用的结果 | 单数据集研究，不能当通用保证 |

### A.2 头部实验室与产品工程

| 来源 | 可借鉴点 | 不应过度解读 |
|---|---|---|
| [Anthropic multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system) | lead/worker、独立上下文、artifact 直交、引用检查、有限重试 | 90.2% 与 15× Token 是厂商内部数据，不是匹配预算因果证明 |
| [Anthropic effective context engineering](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) | 最小高信号上下文、按需读取、压缩与原件并存 | 工程经验，不是受控协议对照 |
| [Anthropic demystifying evals](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) | 结果状态与轨迹结合、trial 隔离、重复试验 | 方法论，不是多智能体性能结论 |
| [OpenAI Responses multi-agent](https://developers.openai.com/api/docs/guides/responses-multi-agent) | 独立有界子任务、root synthesis、并发与成本提醒 | 动态 beta 文档，不代表冻结 Codex 行为 |
| [OpenAI Agents SDK orchestration](https://developers.openai.com/api/docs/guides/agents/orchestration) | manager-as-tools、handoff、不同工具/政策才拆角色 | 设计规范，无性能对照 |
| [Google scaling agent systems](https://arxiv.org/abs/2512.08296) | 任务结构与中心验证；可作为调度启发 | 仍是预印本，跨领域预测有限 |
| [Google Chain of Agents](https://research.google/blog/chain-of-agents-large-language-models-collaborating-on-long-context-tasks/) | 长材料分片与压缩消息 | 早期遗漏和顺序压缩可能传播 |
| [Microsoft Magentic-One](https://www.microsoft.com/en-us/research/articles/magentic-one-a-generalist-multi-agent-system-for-solving-complex-tasks/) | Task/Progress ledger、停滞后重规划、专门工具角色 | 没有匹配 Token 消融；事实/猜测/计划不可混型 |
| [Meta Compute as Teacher](https://ai.meta.com/research/publications/compute-as-teacher-turning-inference-compute-into-reference-free-supervision/) | 保存完整 rollout、anchor 组合局部正确、程序验证 | worker/anchor/judge 仍可能共享偏差 |

### A.3 数据与协议概念的有限借鉴

这些标准只用于澄清“来源、范围、原件引用”，不建议首版完整实现：

- [A2A Protocol](https://github.com/a2aproject/A2A/blob/main/docs/specification.md)：Message 与 Artifact 分离，agent 内部可不透明；
- [MCP Tools](https://modelcontextprotocol.io/specification/2026-07-28/server/tools)：structuredContent、output schema 和 resource link；
- [W3C PROV-DM](https://www.w3.org/TR/prov-dm/)：观测来源帮助判断适用性，但 provenance 不等于内容为真；
- [CloudEvents](https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md)：一次发生、事件身份与 payload 不是同一概念；
- [RFC 8785](https://www.rfc-editor.org/rfc/rfc8785.html) 与 [OCI Descriptor](https://specs.opencontainers.org/image-spec/descriptor/)：只有未来确需内容寻址和稳定缓存键时再借规范化与 digest 语义；
- [Lost in the Middle](https://aclanthology.org/2024.tacl-1.9/)：不要把完整 evidence 与所有 agent 历史广播进长上下文；
- [Language Models Don't Always Say What They Think](https://arxiv.org/abs/2305.04388)：不要把私有 CoT 当作共享事实。
