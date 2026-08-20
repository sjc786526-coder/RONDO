# 方向 3：RONDO Multi（Event 驱动的团队世界状态产品线）

最后更新：2026-08-20 ｜ 产品线：RONDO Multi（`multidev/`）｜ Codex 基线：`v0.147.0` ｜
第一期已完成并合入 `main` ｜ 第二期 A/B 已完成 ｜ C 阶段 A 本地验收完成、待独立审查

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

第二期由两个**并行工程包**和一个**后置测评包**组成。A/B 已分别完成并通过验收；当前依赖门已满足，下一包是 C。
C 自身是一项完整任务，但按“无费用准备 → 单独授权后的付费执行”顺序分成两个阶段，不能把未验证设施直接带入付费运行。

### 并行工程包 A：Team State 序列性质测试

**状态：已完成（Plan 047）。** 默认 Team State 门禁 128 passed、1 skipped，新增性质测试保持 ignored；主动入口
1 passed。固定 seed、有限 case/步数、薄 reference state 与 invariant checker 已落地，未发现产品缺陷、未改产品语义。
详细实现与验收证据只在冻结 plan、agent log 和 `doc/WBS-COMPLETED.md` 保留。

**目标**：在现有 `codex-team-state` 测试体系内，探索 publish、双生命周期、route、delivery、retry 与 wake
的跨功能组合，补充固定产品纵切不容易覆盖的操作序列。availability/retire 作为首选扩展轴；若首版体量接近上限，
先后移该轴，不削弱核心组合链。既有确定性测试继续负责单点合同和永久回归。

**形态**：

- 一个默认 ignored 的 property test、一份只记录可观察抽象状态的薄 reference state、一个主动入口，以及固定 Root
  与少量成员；复用既有 fixture、测试模块和共享 build-lock；
- 生成与 shrink 后的步骤必须保持有效引用，reference model 与真实 store 必须命中同一个 canonical 对象；不适用步骤
  不调用产品 API，也不改变任一侧状态。如何 bootstrap、索引和绑定由实施 plan 结合 live API 决定，WBS 不指定数据结构；
- 只比较可观察 outcome、revision、canonical identity、对象数量、权限视图和关键不变量；精确逐步矩阵在实施 plan 冻结；
- 若纳入 availability，它保持外部环境轴，不混入 canonical revision；
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
- availability/retire 不构成首版硬门；若 reference model、运行时间或审查体量超限，优先后移；
- 精确依赖、锁文件、case 数、操作权重、命令名和生成策略在实施 plan 中根据 live workspace 冻结，不在 WBS 写死。

### 并行工程包 B：RONDO Team Lens

**状态：已完成（Plan 048，零 hook）。** 25 项定向测试通过；24 个代表性 RONDO bundle 可归约且 JSON/HTML 重复生成
字节一致，冻结 Codex 侧使用结构忠实并明确标记的合成原生 fixture。实现没有修改 Rust runtime、Team State 或原生
trace writer。详细实现与验收证据只在冻结 plan、agent log 和 `doc/WBS-COMPLETED.md` 保留。

**定位**：Team Lens 是 Codex 原生 rollout trace 的本地离线 reducer/viewer，输出 Team Report。它不是第二套
tracing facility、benchmark、审计平台或常开 telemetry，也不参与 runtime 调度。同一个 Team Lens 任务分成
数据 MVP 和完整静态可视化两个顺序阶段；任务只有两个阶段都完成才收口。

#### 阶段 1：数据 MVP

先对冻结 Codex 与 RONDO 当前原生 rollout bundle 做字段盘点和缺口验证，复用既有 trace/reducer 与第一期 collector
经验；不预设需要产品 hook。随后由同一个消费者归约出规范化、body-free、确定性的 `team_view.json`：

- 记录可机械取得的线程/Agent、turn/inference、工具与 terminal、Agent interaction、时序和用量信息；
- 对 RONDO 记录可机械取得的 Team revision、projection、Event/Version/route/Fact 身份与关系；
- 每类字段显式标记可用、部分可用、不支持或不适用；不猜测缺失语义，也不把 Codex 缺少的 Team State 伪造成空事件；
- 精确 schema 和字段表由本任务 plan 根据真实 bundle 冻结，不在长程 WBS 预先展开。

阶段 1 完成口径：

- 同一个消费者可以读取冻结 Codex 与 RONDO 的原生 trace，且不修改冻结 Codex；
- 固定 bundle 重复归约得到确定性相同的规范化结果，缺失或不支持字段显式降级，不猜测、不静默拼接；
- `team_view.json` 不复制 prompt、response、命令输出或 Fact 正文，不分析隐藏推理；
- 离线 fixture 与定向测试覆盖归约、跨产品读取和降级路径；不需要 API、Docker 或模型调用。

**条件 hook 门**：阶段 1 必须先完成零 hook 缺口验证。只有机械证据证明核心视图被缺少的 RONDO 结构化语义阻断，
才允许在同一个 Team Lens 任务内增加一个窄 hook 子批：先在 plan 中冻结缺口与最小字段，复用原生 writer、上下文和
reducer，只补 RONDO 必需语义。不得预选具体 hook，不修改冻结 Codex，也不得建立第二套 trace writer、序号、
thread identity、mailbox 记录或独立 Team Trace JSONL。

#### 阶段 2：完整静态可视化

阶段 2 只消费阶段 1 的 `team_view.json`，不重新解析 raw rollout bundle。输出可直接打开、归档、截图和用于汇报的
单文件 `team_report.html`，至少覆盖：

- 两侧共有的 Agent swimlane/timeline、模型与工具活动、通信/等待和摘要卡；
- RONDO 专有的 Team Attention Map、Event/Version 关系和 Fact flow；
- 冻结 Codex 不适用的 Team State 区域、缺失数据和部分失败的清晰说明。

报告应具备适合真实运行汇报的图例、身份/时序一致性和必要的浏览能力，但图形库、布局、筛选交互及视觉细节由任务
plan 和实现审查决定。它是离线静态产品，不引入服务端、数据库、在线 UI、遥测后台或独立前端构建体系。

阶段 2 完成口径：

- 代表性的冻结 Codex 与 RONDO fixture 均能生成可离线打开的报告，同一输入重复生成的结果确定；
- 各视图对同一对象身份和时间顺序的解释一致，缺失、部分可用和不适用状态可见；
- HTML 不复制 prompt、response、命令输出或 Fact 正文，不依赖外部网络资源；
- 报告生成与关键视图有定向测试；不需要 API、Docker 或模型调用。

**共同数据边界**：

- 原始 trace 仅在指定运行中显式开启并保留在本地，按其可能含 prompt、response 与工具 payload 的敏感原始资产处理，
  不由 Team Lens 自动提交或长期归档；
- `team_view.json` 是 reducer 与可视化之间唯一的数据合同；可视化需求不得反向要求保存正文或重建运行时 tracing。

Team State 现有 `team_inspect`、dump/log/stats 用于解释 canonical 状态；Team Lens 用于还原跨线程的实际团队行为。
二者观察对象不同，不互相替代，也不重复建设。

### 后置测评包 C：主动委派收益对比

**依赖**：A、B 均已完成，Team Lens 的跨产品共有字段与 RONDO 专有字段已可用。C 是一个计划与任务合同，顺序分为
阶段 A 和阶段 B；阶段 A 已完成本地无费用验收并等待独立审查，阶段 B 的真实 API 开始动作仍须单独明确授权。

#### 阶段 A：无费用准备（本地验收完成，待独立审查）

- 冻结自然任务集、共同 proactive policy、模型/effort、成员配置、并发、deadline、外部判定、成对顺序、结果分类、
  Team Lens 产物和阶段 B 的费用/恢复边界；不得借准备阶段偷偷运行付费样本。
- 完成共享编排、身份绑定、trace/Team Lens 接线、body-free 归档、账本/resume 与结果聚合的最小设施；优先复用已有
  Multi M-5 和 eval 组件，不建立第二套 runner、trace 或重型 benchmark 平台。
- 用 pure/fake/loopback/replay、合成 fixture 和最小无费用彩排验证配置错误、部分运行、resume、确定性、降级和报告生成，
  使可预见的设施问题在阶段 B 前暴露。只跑受影响模块的必要门禁；任何重型资源仍按仓库全局串行规则执行。
- 阶段 A 的退出条件必须给出明确的 paid-ready/blocked 结论和阶段 B 启动清单，但不得创建“已开始付费”的 receipt、
  请求或结果身份。付费 provider 连通性若无法在零费用条件下证明，应诚实留作阶段 B 首个小型 activation pilot 的门。

#### 阶段 B：付费测评与观测（尚未授权）

- 获得明确开始授权后，先运行小规模 activation pilot，确认两侧收到冻结策略、原生 trace 可读且至少形成可解释的主动
  委派观测，再进入冻结的成对任务；不为追求激活临时强制 spawn 或改写自然任务。
- 阶段 A 应预留宽容的自主修正与恢复空间：可恢复的 provider/网络/归档/编排问题可在不改变公平合同的前提下修复、
  resume 和重跑，不采用过窄的单错即停或每类极小重试上限。费用仍须在阶段 A 冻结为宽松但有限、且不高于可用余额的
  总边界；未知用量、合同漂移、数据边界或不可安全恢复的状态继续 fail-closed。
- 阶段 B 完成后分别报告主动委派激活、外部任务结果和时间/token/工具/文件操作等成本；Team Lens 是描述性观测，
  不能单独推出因果收益。

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

- A、B 已从同一基线在独立 worktree 完成并统一整合；其历史写集边界与验收只保留在各自冻结 plan。
- C 的阶段 A/B 属于同一任务合同并严格串行；阶段 A 退出前不得启动阶段 B，阶段 B 未获明确授权不得产生真实 API 费用。
- C 若分派多个执行者，必须冻结各自 worktree/写集并明确彼此存在；重型 Cargo、Docker、真实本地模型与付费 API
  继续按仓库资源门禁全局串行。

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
