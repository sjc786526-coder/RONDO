# 方向 3：RONDO Multi（Event 驱动的团队世界状态产品线）

最后更新：2026-08-20 ｜ 产品线：RONDO Multi（`multidev/`）｜ Codex 基线：`v0.147.0` ｜
第一期已完成并合入 `main` ｜ 当前进入第二期

## 定位

RONDO Multi 不重做 Agent 执行面。Codex 原生继续负责 thread、spawn/fork、并行执行、shared workspace、
mailbox、wait/resume/interrupt、工具执行、sandbox 与审批。本产品线只解决一个问题：**多个拥有私有上下文和
独立推理过程的 Agent，如何把真正值得团队持续知道的信息，变成一份 Harness 拥有、可追溯、不会因模型遗忘或
上下文压缩而静默消失的团队世界状态**，同时不广播 transcript 与隐藏推理。

设计原文见 `doc/research/RONDO Multi 当前最新完整设计（补充修订版）.md`，工程风险清单见同目录
《RONDO Multi 修正方案意见稿（工程落地版）》；两者是形成时点的冻结材料。本页是当前产品语义、后续路线与
验收边界的唯一规划来源；已完成实现和验收见 `doc/WBS-COMPLETED.md`。

当前产品定位是工程实践、Harness 创新与技术训练，不以“跑赢冻结 Codex Multi-Agent”作为存在前提。
预期团队规模为 2–8 个 Agent，通常更少；不为大规模 swarm 提前引入层级 coordinator、topic subscription
或 learned routing。Multi 是与 RONDO Local 并列的独立产品线，内核形态不受 Local 约束。

## 现行产品语义合同

下列语义已经随第一期产品落地，后续工作不得在 plan、提示词或观测工具中另立一套冲突定义。

### 状态、身份与生命周期

1. Team State 是 Event、Version、生命周期、可见性和指派的唯一 canonical 来源。原始 observation 仍由
   Codex 保留的历史或工具结果承载，Fact 只是可解析引用，不复制 payload；Event 与 Handoff 是 Agent 的语义
   判断，不是客观事实或当前真理，模型看到的角色投影也不是事实来源。
2. Event 是团队级身份，`created_by` 不代表所有权；Version 是不可变 authored 条目。追加顺序不隐含因果或
   替代关系，已进入终态的 Version 不原地重开，事项重新相关时追加新 Version。
3. Event、Version 和 Fact 引用都属于一个团队实例。同一存活 Root 树内成员卸载后重载仍属原实例，身份、
   权限与既有状态不变；只有权威实例确实丢失或不匹配时才重置，旧引用不得解析到新对象。
4. 当前团队实例内的历史追加式保留并按权限查询；退出活动视图不等于删除。
5. producer 轴为 `open/closed`，Root 轴为 `pending/tracking/resolved`；普通成员新建 Version 对 Root 默认
   `pending`，Root 自建默认 `tracking`。Root retire 是 producer 真正不可用后的独立终态，不属于 producer
   自己的关闭动作。各轴只允许合同规定的前进迁移，`closed/resolved/retired` 不倒退；同一 Version 不原地重开。
6. producer 与 Root 生命周期相互独立。Root resolved 不替 producer 关闭，producer 关闭也不替 Root 完成协调；
   Root retire 必须记录操作者与理由，不冒充 producer 自己关闭。
7. 活动视图由统一谓词生成：参与者自己仍有未终态 Version、存在面向它的活动 assignment，或作为 Root 仍有
   未 resolved Version。结束一个纳入理由不得错误移除其余理由。
8. 任意有资格的 Agent 追加新 Version，都使 Event 重新进入 Root 注意力；producer 关闭 Root 仍在
   `pending/tracking` 的 Version 时应提供一次 wake，Root 已 `resolved` 的旧 Version 仅发生 producer 轴变化时
   不重新进入 Root 活动视图。

### 投影、提交与唤醒

9. 活动投影必须在模型决定是否调用团队工具之前进入本次采样。稳定协议在版本化指令前缀，易变投影位于本轮
   完整正常输入之后的协议安全位置，不插入或重排工具调用与结果配对。
10. 投影不写入普通 conversation history，也不随 compaction 固化；每次逻辑采样从 canonical 状态构造一次
   不可变快照，同一次采样的 provider retry 复用该快照。这里的“普通 history”不等于本地原生 rollout-trace
   bundle；后者可以按启用的 trace 策略记录实际 inference request。
11. 投影计入整次上下文预算。超预算时显式报告省略项并提供有界历史下钻，不静默截断，不让投影顶爆请求。
12. mutation 是增量提交而非 replace-all。对采用 Team revision 的 canonical coordination mutation，新的成功
    变更恰好推进一次 revision；participant registration、availability 与 Fact 状态等独立轴不混入该计数。
    rejected、deduplicated 与稳定 no-op 不推进 Team revision，失败不得留下部分写入。
13. 每次提交携带稳定 request identity 与适用的 revision/precondition。重试不重复创建身份；陈旧追加按合同
    标记后提交，陈旧生命周期变更拒绝并返回当前状态，不静默覆盖。
14. wake 是状态变化后的协调信号，不是第二份状态。发布先于等待或发生在等待期间都不能丢；已消费变化不重复
    唤醒；Root 自建 Version 不自唤醒。

### 路由、权限与证据

15. Root 以 Event 为单位选择性 route：先 canonical 提交可见性与 assignment，再尝试通知。通知不复制 Event
    chain，at-least-once 投递不得重复创建状态。
16. route 后可见性不可撤销，并决定读取资格与当前贡献资格；可见性、assignment、活动性与通知投递彼此分离。
    每个 Event 与 target 至多一个活动 assignment；delivery success 不被迟到的 failure 覆盖，结束 assignment
    只撤掉对应活动理由。
17. 权限由当前 Session 的权威身份推导；只有登记在册的团队参与者获得团队能力。取得不到权威身份时
    fail-closed，不信任模型自报的 author、producer 或 Root 标志。
18. Root 可读本团队证据；子 Agent 只能读自己产生的、或从其可见 Event 可达的 Fact。读取只开放目标
    observation，不连带开放 sibling 其他上下文。
19. Fact 是 Codex 实际保留且 Harness 可稳定定位的历史 observation，只承诺身份与可用性状态，不承诺原始字节
    永久可恢复；不可得时必须诚实标注。Fact 不是当前真理，Harness 不自动判断其是否仍适用。
20. 一次发布窗口关联哪些新增 Fact 由确定性规则决定；同一 retained 执行轨迹重放必须得到同一关联，
    不得产生悬空引用。
21. 复用 Codex 原生执行与通信机制；不另建 Agent-to-Agent 协议、调度器、全局订阅或 workspace 协调层。
    Event 是否值得发布、Root 如何 route 和 resolve，仍由 Agent 作语义判断。

## 持续产品约束

- Multi 能力默认关闭；关闭态不应改变冻结 Codex 的常规行为。继承的 evidence capture 与 Guardian provider
  覆盖保持默认关闭，不为保留它们而让 Multi 内核妥协。
- Multi 不携带 RONDO Local 的 GGUF 路径、本地模型 runtime 或部署默认。
- 产品身份贯通源码、构建、冻结 binary、manifest、adapter/RunSpec 与结果归档；数据资产继续遵循
  `doc/eval-data-layout.md`。
- 第一期冻结工件、历史 runtime、正式 receipt、trace 与结果保持不可变，只作为完成证据，不冒充第二期运行身份。
- 重型 Cargo 构建与测试继续复用仓库共享 build-lock；工程并行不等于重型任务并发。

## 第一期结论边界

第一期已随 `a220b774…` 合入并推送 `main`。它证明：

- 在明确要求委派的真实运行中，完整 RONDO 协作链能够被模型实际触发并正确收尾；
- 在冻结十题、20 个基础有效 run 中，没有观察到相对冻结 Codex 的稳定单向退化。

它没有证明真实自然任务中的 Root 会主动委派，也没有证明 RONDO 带来质量、速度或成本收益。详细产品阶段、
运行过程、正式数字与资源证据只保留在 `doc/WBS-COMPLETED.md`、冻结 plan、agent log 和结果资产中。

## 第二期：稳定性、可观测性与主动委派收益

第二期由两个**并行工程包**和一个**后置测评包**组成。前两个任务没有逻辑依赖，分别增强正确性保障与团队行为
可观测性；后置测评必须等待二者完成，不能混成一个过大的实施任务。

### 并行工程包 A：Team State 序列性质测试

**目标**：在现有 `codex-team-state` 测试体系内，探索 publish、双生命周期、route、delivery、retry、wake、
availability 与 retire 的跨功能组合，补充固定产品纵切不容易覆盖的操作序列。

**形态**：

- 一个默认 ignored 的 property test、一份只记录可观察抽象状态的薄 reference state、共享符号绑定与主动入口；
  availability 作为外部环境轴保存，不混入 canonical revision；
- 固定 Root 与少量成员，并由 harness 提供不可被 shrink 删除的有效 Event 起点；后续操作使用符号引用，
  reference model 与真实 store 通过同一绑定表解析；
- 不适用的符号操作由 harness 明确记为 `NotApplicable`，双方均不调用产品 API，也不把它伪装成产品错误；
- 每步只核对 revision、outcome class、canonical identity、对象数量、活动/权限视图和关键不变量；
- 失败保留 seed 并 shrink；真实缺陷的最小反例转成既有模块中的普通确定性回归。

**完成口径**：

- 默认 Team State 门禁仍通过，性质测试只编译并显示为 ignored；
- 主动入口在冻结的有限 case 与序列长度合同下通过，固定 seed 可复现同一操作序列；
- invariant checker 自测能拒绝人为构造的错误抽象状态；
- 除发现真实产品缺陷后的窄修外，不改变产品行为。

**边界**：

- 不建新 crate、独立 runner、corpus、JSON 归档、fuzz daemon 或通用 generator 框架；
- 不随机轰炸已有确定性测试覆盖的一般错误输入，也不重复 re-register 身份保持测试；
- 首批不纳入 Fact、批量生命周期、真实 residency/mailbox、provider retry、compaction、Tokio 调度、
  工具 runtime 异步接缝、Docker、API 或模型调用；
- 精确依赖、锁文件、case 数、操作权重和命令名在实施 plan 中根据 live workspace 冻结，不在 WBS 写死。

### 并行工程包 B：RONDO Team Lens

**定位**：Team Lens 是 Codex 原生 rollout trace 的本地离线 reducer/viewer，输出 Team Report。它不是第二套
tracing facility、benchmark、审计平台或常开 telemetry，也不参与 runtime 调度。

**首批路线**：

1. 先对冻结 Codex 与 RONDO 当前原生 rollout bundle 做字段盘点和缺口验证，复用现有 trace/reducer 及第一期
   collector 经验；不预设需要产品 hook。
2. 从同一原生数据源归约出规范化、body-free 的 `team_view.json`，再生成可直接离线打开和归档的单文件
   `team_report.html`。
3. 两侧共同展示线程/Agent、inference、token、工具、code cell、terminal、spawn/message/followup/wait、
   时间与峰值并发；RONDO 额外展示 sampling 时的 Team projection、revision、Event/Version/route 与 Fact flow。
   冻结 Codex 不具备的 Team State 面板明确显示“不适用”，不伪造空事件。

**完成口径**：

- 同一个消费者可以读取冻结 Codex 与 RONDO 的原生 trace，且不修改冻结 Codex；
- 固定 bundle 重复归约得到确定性相同的规范化结果，缺失或不支持字段显式降级，不猜测、不静默拼接；
- 报告可展示 Agent swimlane、团队注意力、Event/Version/Fact 流和摘要卡中的适用子集；
- reduced JSON 与 HTML 不复制 prompt、response、命令输出或 Fact 正文，不分析隐藏推理；
- 原始 trace 仅在指定运行中显式开启并保留在本地，按其可能含 prompt、response 与工具 payload 的敏感原始资产处理，
  不由 Team Lens 自动提交或长期归档；
- 离线 fixture 与定向测试覆盖 reducer 和报告生成；首批不需要 API、Docker 或模型调用。

**扩张门**：只有零 hook 原型机械证明缺少的结构化 projection 或 canonical mutation 时点确实阻断核心报告，
才另立一个第二批窄任务，在 RONDO 精确位置补最少语义事件。不得提前新增 trace writer、第二套序号、
thread identity、mailbox 记录或独立 Team Trace JSONL；冻结 Codex 始终不改源码。

Team State 现有 `team_inspect`、dump/log/stats 用于解释 canonical 状态；Team Lens 用于还原跨线程的实际团队行为。
二者观察对象不同，不互相替代，也不重复建设。

### 后置测评包 C：主动委派收益对比

**依赖**：A、B 均完成，尤其先冻结 Team Lens 的跨产品共有字段与 RONDO 专有字段；真实 API、Docker、任务范围、
轮数与预算另行授权。

**公平合同**：

- 冻结 Codex 与 RONDO 都启用同一 Multi-Agent V2 工具面，并使用同一主模型、`medium` effort、同一成员模型与
  effort、同一并发上限、同一非任务特化的冻结 proactive developer instruction、同一自然任务 prompt、deadline
  与外部评分；只有 RONDO 额外启用 Team State；
- 用户任务不指定 spawn、工具顺序或 RONDO 协作协议，由 Root 自主决定是否、何时及如何委派；
- 两侧均开启原生 rollout trace；冻结 Codex 不修改源码。主结论描述为“medium + 相同 proactive policy”，
  不冒充 medium 默认行为；`ultra` 不属于主比较，如未来使用只能作为独立诊断或上界。

**运行与判读**：

1. 先做小规模 activation pilot，机械确认策略已注入并出现 trace-backed 的主动委派。若双方都不委派，只能记录
   当前策略或任务未激活，不进入“Team State 带来收益”的解释，也不通过临时强制 spawn 改写自然任务。
   若只有一侧委派，只能报告委派倾向和整包产品结果，不能把差异单独归因为 Team State 或“委派后的收益”。
2. 有效成对运行分别报告外部任务结果、wall time、token、inference/tool/command/file 操作、spawn、
   峰值并发、message/followup/wait，以及 Team Lens 报告。
3. “更愿意主动委派”与“委派后质量或性能更好”是两个独立结论。内部 Event、Fact 或消息数量只能解释行为，
   不能替代外部任务结果，也不能由一次漂亮轨迹推出因果收益。
4. 任务、轮数、模型、价格、预算、重试和统计口径在该测评自己的冻结 plan 中确定；未运行、未激活、infra 或
   样本不足必须按各自语义如实报告。

## 并行与交接边界

- A、B 从同一个第一期收口基线创建独立 worktree，同时开发。
- A 独占 Rust 测试依赖锁、主动测试入口等共享写集；B 首批不碰 Team State crate、Rust 依赖锁或 trace runtime。
- 两项代码工作可并行；重型 Cargo 仍通过全局共享 build-lock 串行。最终共享 WBS 由一个整合任务同步。
- C 只在 A、B 完成后开始；不得为赶测评而把未证实需要的 Team Lens hook 或新测试基础设施塞进前两项。

## 候选池（不排期，由真实运行证据触发）

- **投影成本压缩**：现有硬预算和显式省略已经保证正确性；只有真实运行证明完整 chain 成为主要成本时再优化。
- **批量结束注意力**：只有逐项消费被证明是 Root 的实际负担时立项，且只作用于显式目标。
- **Event 关系**：重复 Event 已成为真实痛点、自然语言关联跨 compaction 不可靠时立项。
- **证据新鲜度线索**：模型频繁重复验证同一件事时立项；不得给 Harness 观察不到的写入伪造精确感。
- **Root 注意力状态对 producer 可见**：信息不对称被真实轨迹证明造成损失时再做，只暴露状态，不暴露协调理由。
- **只读贡献档位**：真实出现“只告知、不允许追加”的需求时再加。
- **团队状态跨进程持久化与恢复**：会话中断导致的状态丢失成为实际痛点时立项。
- **多 writer 隔离与集成**：共享 workspace 的真实写冲突频率不可接受时立项。
- **朴素自然语言转述对照模式**：只作测评期临时开关，不作为长期设计约束。
- **远期**：通用 DAG、嵌套团队、跨 session 复用、多进程或远程 worker；均由真实使用证据触发。

## 稳定非目标

- 合规/取证平台、完整 provenance graph、PKI/签名链、区块链或平行 ACL。
- trust score、长期 agent 排名、在线学习路由器、judge 集群或一智能体一票。
- 全量 transcript/CoT 广播、自由群聊、无限反思、固定大 swarm。
- 通用副作用缓存、任意工具透明重放。
- 复杂鉴权、数据资产审计或可信度评分体系。
- 为证明全面优于单体而建设庞大 benchmark；只做目标工作流所需的正确性保障与轻量测评。
