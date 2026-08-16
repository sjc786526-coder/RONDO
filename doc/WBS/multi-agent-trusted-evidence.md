# 方向 3：RONDO Multi（Event 驱动的团队世界状态产品线）

最后更新：2026-08-15 ｜ 产品线：RONDO Multi（`multidev/`）｜ Codex 基线：`v0.147.0` ｜ 顶层路线见 `doc/WBS.md`

## 定位

RONDO Multi 不重做 Agent 执行面。Codex 原生继续负责 thread、spawn/fork、并行执行、shared workspace、mailbox、
wait/resume/interrupt、工具执行、sandbox 与审批。本产品线只解决一个问题：**多个拥有私有上下文和独立推理过程的
Agent，如何把真正值得团队持续知道的信息，变成一份 Harness 拥有、可追溯、不会因模型遗忘或上下文压缩而静默消失的
团队世界状态**，同时不互相广播 transcript 与推理过程。

设计原文见 `doc/research/RONDO Multi 当前最新完整设计（补充修订版）.md`，工程风险清单见同目录
《RONDO Multi 修正方案意见稿（工程落地版）》；两者都是形成时点的冻结证据，不随本页更新改写。
**本页是当前语义、阶段顺序与验收边界的唯一规划来源**：两份研究文档与本页不一致时，以本页为准。

第一版定位是工程实践、Harness 创新与技术训练，不以"跑赢原生 Codex Multi-Agent"作为存在前提。
成功率、成本、重复工具调用与发布负担都要测量并驱动迭代，但都不是准入门。

第一版预期团队规模 2–8 个 Agent，实际通常更少。不为几十上百 Agent 提前引入层级 coordinator、
topic subscription 或 learned routing。

**内核形态不受 Local 约束**：允许内核级重构，不要求与 `mydev/` 长期保持提交级一致。

## 设计语义合同

以下语义已定，后续每个阶段都受其约束。要改只在这里改，不在 plan、代码注释或提示词里另立一套。

### 状态与身份

1. 团队世界状态是 Harness 拥有的唯一事实源；模型看到的只是它面向某个角色、某次采样的投影。投影不是事实来源。
2. Event 是团队级身份，Version 是这件事演化过程中不可变的阶段性条目。创建者只是 `created_by`，不拥有该 Event。
3. Version 的追加顺序只是登记顺序，不隐含因果继承，也不隐含后者替代前者；替代关系由显式状态表达。
4. Version 的 authored 内容（作者、Handoff、证据引用）写入后永不改写；生命周期状态是附着其上、可更新的投影。

### 双生命周期与注意力

5. producer 侧与 Root 侧状态相互独立：Root resolved 不改 producer 状态，producer 关闭也不替 Root 完成消费。
6. 任何有资格的 Agent 追加新 Version，都使该 Event 重新进入 Root 的活动视图。
7. Root 自己创建的 Event/Version 默认进入 tracking 而非 pending，且不自我唤醒。
8. producer 关闭一个 Root 仍在 pending/tracking 的 Version 时，应使 Root 重新获得一次协调机会。
9. Root 对某个 Version 的 attention 状态，对该 Version 的 producer 只读可见，避免双方都以为对方在处理。
10. producer 已不可用而 Version 仍未终结时，由 Root 显式退休该 Version，并记录为 Root 的协调行为，
    不写成 producer 自己关闭。
11. 不做自动 escalation：Harness 不判断 Root 是否判断错误；持续异议通过发布新 Version 表达，不靠系统覆盖 Root。

### 投影与上下文

12. Agent 的活动事件列表必须在模型决定是否调用团队工具**之前**就已进入本次采样上下文，而不是工具调用之后才展示。
13. 团队投影与可压缩的消息上下文并列：不进入 conversation history 与 rollout，不被 compaction 改写，
    每次采样从当前团队状态重新生成，同一次采样使用同一份一致快照。
    （因此 Codex 既有那条"渲染成 diff 片段并写回历史"的 world-state 通道不适合作为它的载体。）
14. 语义上默认投影完整 Version chain；工程上允许硬预算，但超预算时必须显式报告被省略的部分并保留下钻入口，
    不得静默截断。历史长度不直接转化为上下文长度。

### 传播与权限

15. Root 以 Event 为单位选择性 route。正式 route 先授予 canonical 可见性，再发送紧凑通知；
    完整内容始终从团队状态获取，通信正文不复制 Event chain。
16. 可见性与任务指派分离：可见性是不可撤销的知识；Event 是否继续占据目标 Agent 的活动视图，
    由可结束的 route 指派决定。第一版贡献资格跟随可见性，只读贡献档位后置。
17. 一切权限从当前 Session 身份推导，不信任模型自报的 author / producer / root 标志。
18. 复用 Codex 执行面：不新建 Agent-to-Agent 传输协议、不另建调度器、不建全局订阅机制。
    Agent 的运行、等待、结束等宏观生命周期直接沿用现有机制，不作为特殊 Event 类型。

### 证据

19. Fact 是"Harness 能稳定定位到的、Codex 实际保留的历史 observation"。它只承诺身份与定位，
    **不承诺完整原始字节永久可恢复**；不可得时必须显式标注，不允许悬空引用。
20. Fact 永远是历史 observation，不是当前真理。Harness 不自动判定它是否仍然适用。
21. 一次发布周期携带哪些新增 Fact，必须由确定性规则决定：同一条执行轨迹重放应得到相同关联。

### 边界

22. Harness 不做语义判断：不把 Fact 自动升级成 Event、不自动聚类合并 Event、不按固定时间或工具次数强制发布。
    是否已形成值得外部化的语义检查点由实际工作的 Agent 判断；全局相关性、优先级与传播由 Root 判断。
23. 团队状态第一版可以是 session 内存态；但进程或会话恢复后，旧投影绝不能冒充当前团队状态。
24. Shared workspace 沿用 Codex 原有多 writer 语义，第一版不引入 worktree、写入锁或新的 workspace 协调。

## 持续约束（M-0 产品基线，已完成）

`multidev/` 由 `mydev/` 的 Git 跟踪文件精确复制而成。落地证据见 `doc/WBS-COMPLETED.md`，
取舍论证见 `agent_log/2026-08-13-strategy-consensus-landing.md`。下列三条对每个后续阶段继续生效：

1. **默认关闭可断言**：`[auto_review]` 的 `model`、`model_provider`、`reasoning_effort`、`evidence_dir`
   在空配置下经真实配置加载后全为 `None`。
2. **基线在关闭态取得**：Multi 的基线测试与退化验收在该关闭态下运行；eval 不为 Multi 注入这四项，
   结果工件用版本化 `auto_review_config` 记录该状态。
3. **不携带本地模型依赖**：`multidev/` 的配置与测试不引用任何 GGUF 路径或本地推理 runtime。

**产品身份**贯通源码/构建路径、Cargo target、binary freeze、manifest、共享 catalog、adapter/RunSpec、
campaign 与结果归档，唯一映射是 `eval/rondo_eval/contracts.py` 的 `product_layout()`；
Multi 的工件命名空间是 `eval-data/bin/rondo-multi/`。规则见 `doc/eval-data-layout.md`。
Multi 目前**没有冻结的 runtime bundle**，首次 Docker 或付费验收前必须先冻结一套。

**继承代码的处置**：evidence capture 与 Guardian provider 覆盖默认关闭、不影响 Multi 开发，本质是预留接口。
不预设删除，处置原则只有一条：**不为保住它而对 Multi 内核做设计妥协**。

## 阶段

每个阶段只定义目标、交付能力、完成标准与边界；具体做法由该阶段的 plan 决定。
阶段顺序是硬依赖顺序，不并行。

### M-1 团队世界状态纵切（当前下一步）

- **目标**：证明"团队状态不依赖任何模型记住"这一核心命题在真实多 Agent 运行中成立。
- **交付能力**：Event / Version 身份与不可变 authored 内容；producer 与 Root 双生命周期；
  Root 与各 Agent 各自的活动视图在采样前进入上下文；Root 在协调等待期间不遗漏团队状态变化；
  同一 Root 树内所有 Agent 共享同一份 canonical 团队状态。
- **完成标准**：一条端到端链路真实跑通并可复现 —— Root 派生子 Agent 并进入等待；子 Agent 发布首个 Event；
  Root 被唤醒并在下一次采样中看到它；Root 标记 resolved 后该事项仍留在子 Agent 自己的活动视图；
  子 Agent 追加新 Version 后该 Event 重新获得 Root 注意力，且完整 chain 可见。
  发布先于等待、发布发生在等待期间两种时序都不丢唤醒；并发提交不互相静默覆盖，重复提交不产生重复条目。
  团队投影不出现在 conversation history 与 rollout 中，compaction 后仍能正确重建。
  上述状态规则以测试固化，而不是只写在提示词里。
- **边界**：不含 route、不含 Fact Index、不含 orphan 退休与 Event 关系；不改动 Codex 的 spawn/fork/lifecycle；
  证据引用在此阶段可以为空 —— 这是阶段边界，不是产品终态。

### M-2 选择性路由

- **目标**：让团队信息按 Root 的判断在 Agent 之间流动，且不产生第二份 canonical 副本。
- **交付能力**：Root 以 Event 为单位授予可见性并投递紧凑通知；被 route 的 Agent 能读到完整 chain
  并在同一 Event 下贡献自己的 Version；route 指派有可结束的生命周期，使 Event 能干净退出目标 Agent 的活动视图；
  投递失败可见、可重试。
- **完成标准**：同一 Event 下的多作者 Version 链跨 Agent 跑通；通信正文不含 Event chain 正文；
  "先提交可见性、再投递通知"的顺序有测试覆盖；投递失败不产生半写入、不丢失 route 记录；
  重试不重复建立指派。
- **边界**：不引入新的 Agent-to-Agent 传输协议；不实现只读贡献档位；不实现 Event 关系图。

### M-3 证据锚定

- **目标**：让 Event 里的语义判断可以回溯到 Harness 实际观察到的执行结果，使团队状态成为 evidence-backed，
  而不只是结构化便签。
- **交付能力**：为高价值 observation 分配稳定引用与定位信息；发布周期内新增的证据机械关联到 Version；
  Root 与 Agent 可按引用下钻原始结果；引用不可解析时显式标注。
- **完成标准**：同一条执行轨迹重放得到相同的证据关联；每个引用要么可解析、要么带明确的不可得标注，
  不存在无标记悬空；RONDO 自身的团队工具不产生递归证据。
- **边界**：不复制全量工具输出，不建 artifact store，不自动判定证据是否仍然有效。

### M-4 协调闭合与可观测性

- **目标**：让长时间运行中的团队状态能干净收尾，并让一次错误协调可被事后解释。
- **交付能力**：producer 不可用时 Root 显式退休其未终结 Version；Root 能低成本地成批结束注意力
  而不误覆盖并发产生的新 Version；确定性的团队状态转储与变更日志；每个 Agent 的发布频率与体量可观测。
- **完成标准**：orphan 场景不产生永久悬挂事项；投影超预算时显式报告而非静默丢弃；
  从转储与变更日志可以回答"谁在哪个版本号下做了什么改动""Root 为什么没被唤醒""某 Agent 为什么看不到某个 Event"。
- **边界**：不做产品级 UI，不做自动重要性分类，不做自动 Event 合并。

### M-5 真实运行与不退化验收

- **目标**：在真实任务上跑通完整协作语义，并确认相对冻结 Codex 未出现稳定单向退化。
- **前置**：先按产品身份冻结一套 Multi runtime bundle；按 `doc/WBS.md` §6 单独取得真实 API 授权。
- **完成标准**：见下节退化验收口径。
- **边界**：不主张质量优势，不做大规模统计证明。

## 候选池（不排期，由真实运行证据触发）

- 投影压缩：materialized head、history folding 或其他上下文成本优化 —— 只在真实运行证明 chain 长度
  确实成为主要瓶颈后才立项，不提前优化。
- Event 关系：Root 显式记录重复、替代、阻塞等关系，跨 compaction 保留协调判断。
- 轻量 workspace chronology：帮助模型判断证据新鲜度。注意它对 Harness 观察不到的写入天然不完整，
  立项前要先确认它不会给模型虚假的精确感。
- 只读贡献档位（可见但不可追加 Version）。
- 团队状态持久化与跨进程恢复。
- 多 writer 隔离与集成（worktree/lease、integrator 串行合并）—— 由真实冲突频率决定是否引入。
- 朴素自然语言转述对照模式：只作为测评期的临时开关按需实现，**不作为设计约束长期维护**。
- 远期：通用 DAG、嵌套团队、跨 session 复用、多进程或远程 worker。每项都必须由真实使用证据触发。

## 退化验收口径

"相对冻结 Codex 不明显退化"的判定方式：**固定一小组 TB 2.1 任务，Multi 与冻结 Codex 跑同题，
只记录任务是否完成。**

- **不计算 `σ` / `delta`，不做统计显著性，不继承旧 M2 的机械判据** —— 那套与"不要求昂贵统计证明"的定位冲突，
  且小样本下 `σ` 极不稳定。
- 只在 Multi 出现**稳定的单向失败**（Codex 完成、Multi 不完成，且重复出现）时判定为退化并回头修；
  没有观察到这种失败时，只表述为"该小样本下未观察到稳定单向退化"，不扩大成统计意义或全面能力上的通过。
- **任务集：直接复用 P2/B7 的同一个金丝雀集**（`eval/tasksets/p2-b7-canary-catalog-v*.json`），不另选任务。
- **频次：只在 M-5 以及后续重大改动时跑。** 平时回归完全依赖测试体系（单测、fake/loopback/replay），
  不做周期性付费跑。
- 这是跨二进制对比，v22 暴露的那批设施缺陷会原样适用（catalog 非对称、harness/deadline 混杂、非交错执行
  都可能把设施伪影伪装成"Multi 单向失败"）。公平比较设施已闭合；运行时仍须冻结范围、轮数与预算并单独授权。

轻量指标（token 数、工具调用次数、发布频率与体量）随各阶段低成本记录归档，不依赖大规模付费测评。

## 稳定非目标

- 合规/取证平台、完整 provenance graph、PKI/签名链、区块链或平行 ACL。
- trust score、长期 agent 排名、在线学习路由器、judge 集群或一智能体一票。
- 全量 transcript/CoT 广播、自由群聊、无限反思、固定大 swarm。
- 通用副作用缓存、任意工具透明重放。
- 复杂鉴权、数据资产审计或可信度评分体系。
- 为证明全面优于单体而建设庞大 benchmark；只测目标工作流的正确性与轻量开销。
