# 方向 3：RONDO Multi（Event 驱动的团队世界状态产品线）

最后更新：2026-09-03 ｜ 产品线：RONDO Multi（`multidev/`）｜ Codex 基线：`v0.147.0` ｜
状态：**当前无 active 工作包**。

第一期、第二期、第四期均已完成。三期 Publication Critic 的质量重构原定串行为“任务合同重构 → v8 后继数据改造与有限扩充
→ 一次主方案训练 → 模型资格验收与横评”；前三个工作包已依次执行，工作包三形成有效训练 `NO-GO` 且没有候选，
因此本轮路线在工作包三停止，**工作包四未解锁**。历次工作包与 Plan 的执行经过、指标、费用、资源终态和独立验收结论
统一见 `doc/WBS-COMPLETED.md`；本页只维护仍然有效的产品语义、边界、锁定状态与未完成项。

## 当前定位

RONDO Multi 不重做 Agent 执行面。Codex 原生继续负责 thread、spawn/fork、并行执行、shared workspace、
mailbox、wait/resume/interrupt、工具执行、sandbox 与审批。RONDO Multi 只负责把值得团队持续知道的信息变成
Harness 拥有、可追溯、不会因模型遗忘或上下文压缩而静默消失的团队世界状态，同时不广播 transcript 与隐藏推理。

Multi 是与 RONDO Local 并列的独立产品线。当前定位是工程实践、Harness 创新与技术训练，不以跑赢冻结 Codex
Multi-Agent 作为存在前提。预期团队规模为 2–8 个 Agent，通常更少；不为大规模 swarm 预建复杂调度体系。

三期建设一个专用本地 **Publication Critic**：Producer 提交 `team_publish` 前，由小模型审查拟发布内容是否达到最低公共状态
质量。稳定产品语义见 [`doc/rondo-multi-publication-critic-product-contract.md`](../rondo-multi-publication-critic-product-contract.md)；
Producer、Critic、Harness、Root 的职责及现行 Team State 不变量以该合同为共同前置。

四期 Durable Team Runtime 已正式收口，终态为 `M4_W1_PASS / PHASE_4_COMPLETE`，没有后续必需工作包；
简要归档入口见 [`doc/WBS/durable-team-runtime.md`](durable-team-runtime.md)。

## 当前有效结论与锁

以下是方向 3 的现行状态，未经新的立项与授权不得改变：

| 项 | 当前状态 |
|---|---|
| Publication Critic 产品默认 | `OFF`；生产启用 `NO` |
| 本地候选模型质量 | `NO-GO / 待替换`——工作包三没有形成候选，也没有 best checkpoint 或 inference-ready 权重 |
| 云端 scorer 质量资格 | `NOT QUALIFIED`（headroom HIGH）；只作 eval/reference-only，不是产品 backend |
| 云端判官接缝方向 | 五维 hard decision；**单标量接缝废弃**（保留历史身份与可复算路径，不再作为接入方向） |
| 云端五维接缝工程状态 | `ENGINEERING_SEAM_PASS`——接缝工程可用，**不含任何质量或资格结论**，云端 backend 仍须显式选择 |
| M3-D 产品价值 | 未验收 |
| 工作包四（资格验收与横评） | 未解锁 |

**唯一权威训练语义**为 `rondo-publication-critic-task@v2`（单 backbone、五个 hard decision heads、确定性非补偿 gate），
下游正式判定只能使用绑定 frozen decision config 的 `rondo-publication-critic-decision@v1` decoder；
历史 raw argmax 仅保留为 zero-margin diagnostic/historical reference。scalar 只是 gate 投影，不是独立学习的整体质量语义。

**冻结数据资产**：`publication-critic-v8` 原样保留为历史证据；`publication-critic-v9` 为 216 candidates / 96 pairs；
development-only `publication-critic-v10` 只含 162 train / 27 validation candidates；
family-isolated `publication-critic-qualification-v1` 为 50 groups / 200 candidates / 100 pairs，**正文封存到工作包四**；
v9 test 已降格为 metadata-only 同分布辅助 holdout，不读取、不改写。旧 unseen 继续封存。

## 当前 Linux 正确性基线

方向 3 已入主线的最新基线由 Plan 105 建立：发布候选在 default features、standard local Nextest、checksum-verified V8、
`CARGO_INCREMENTAL=0` 的完整 workspace 上取得 `14713/14713` passed、0 failure/error/timeout/retry，另有 1/1 setup passed；
24 个 skip 不计 passed。Multi 实质代码与功能自此冻结，并已据此发布 `multi-v0.1.1`。
更早的 Plan 093 冷 workspace 基线（`14660/14660`）已被取代，只作历史证据。

正式证据、JUnit SHA 与精确边界见 `doc/WBS-COMPLETED.md` 及对应 `agent_log/`。

## 三期目标与冻结决定

本节是规范性约束，不是历史记录。若未来重新启动训练或资格路线，以下内容继续适用；要改变其中任何一条，
必须先更新本 WBS，不能由单次 ExecPlan 或训练现场临时决定。

### 产品目标

- Critic 审查完整 canonical publication candidate，四类 publication 使用统一最低质量原则；`PASS/REWRITE`、两次 Producer
  重写、最终非阻断发布、服务故障继续发布与取消不提交均按产品合同解释。
- 输入只来自有界、permission-scoped 的公共状态；V1 不读取 evidence 正文或验证 claim→Fact 语义，Critic 不自动改写、
  不决定事项是否值得发布，也不接管 route、分工或 Root 协调。

### 模型与训练边界

- 最终目标仍是形成一个可在本地运行的专用 Publication Critic。具体学生基座、训练参数和模块布局不由本 WBS 预先冻结；
  任何新的训练任务只允许在其 ExecPlan 内选择并冻结**一套**主方案，不恢复多路线云端搜索。
- 继续扩大同家族 base、做相邻 scope/LR/权重搜索或只调 threshold 的优先级很低——这是历次云端训练与测评的共同结论。
  历史结果保持冻结证据，不作为新合同的数据或质量 GO。
- 新训练仍须支持开发期趋势、checkpoint、fresh-process 恢复和 base/best/latest 的有界保留；开发 validation 只用于形成候选，
  不冒充独立资格或冻结测试证据。模型、数据和付费条件一经正式冻结，只执行一次主方案；技术故障可在授权总额内自主修复、恢复或重跑，
  语义失败不得通过临时改目标、改标签或反复搜索掩盖。
- 数据继续允许教师合成为主体，但合成数据的唯一上游是任务合同，不是旧 revision 的类别、pair、配比或模板；旧数据只提供待重新判定的
  候选素材，不得机械扩展。新 revision 还须保留少量真实或真实形态锚点、独立 split 与模块化盲审；不建设人工标注平台、教师委员会或
  重型数据可信系统。

### 冻结任务设计方向

以下核心设计已由 `rondo-publication-critic-task@v2` 落地并冻结，后续工作包不得自行改写；实现者只对具体模型基座、head 代码形态、
连续近似、loss 数值权重、margin、batch、优化器和训练资源作任务内技术选择。

1. **单 backbone、五个 hard decision heads**：一次模型 forward 产生五项结构化 hard 判断，不建立五个独立模型，也不以五次条件化推理代替
   当前主方向。五项分别为 `useful_state_transfer`、`honest_uncertainty`、`conditional_continuity`、`scope_and_signal`、
   `internal_consistency`；continuity 必须表达 `PASS / FAIL / N/A`，其余维度至少表达 `PASS / FAIL`。
2. **确定性非补偿 gate**：最终 `PASS` 当且仅当全部适用 hard heads 都通过，任一 head 失败即 `REWRITE`。内部可使用 violation probability
   或 satisfaction probability，但不得平均或学习一组可相互补偿的总质量权重。若现有 scorer 接缝需要 scalar，只允许把结构化判断投影为
   `quality = min(applicable satisfaction)`，等价于 `1 - max(applicable violation)`；该 scalar 是 gate 投影，不是独立学习的整体质量语义。
3. **不设置决定资格的自由 global-quality head**：Binary `PASS/REWRITE` 监督作用于五个 heads 派生出的 gate；可以为训练可微性使用
   `max/min` 的平滑近似，但正式 verdict 必须回到确定性 all-hard-pass。诊断性输出不得覆盖任一 hard failure。
4. **五维绝对监督是主体**：每个 candidate 都应提供完整的五维 `PASS/FAIL/N/A` 标签矩阵，逐维分类损失是主损失。`defects`、
   `hard_focus` 或“本样本主要注入的缺陷”不能替代完整标签，未列出的维度不得自动推定为 PASS。
5. **总体 Binary 只监督派生 gate**：总体标签用于约束五个 heads 的合取结果，不再训练另一个可以用风格、语法或其他优点补偿 hard failure 的
   单标量。训练目标可以保留派生 gate loss，但其梯度来源和推理语义必须可追溯到五项 hard 判断。
6. **Boundary 是定向 hard 监督**：Boundary pair 的主要差异只落到声明的 target hard head，并要求两端各自达到绝对资格结论；非目标 heads
   应保持一致。Pair loss 使用达到即停止继续扩张的有限 margin，不得以“总分 Q+ > Q-”替代 `Q+ PASS && Q- REWRITE`。
7. **Within-PASS 是资格不变性监督**：两端都必须是五项 hard 全部通过；其 soft-only 差异用于约束各 hard heads 和派生 gate 保持一致，
   不再要求 preferred PASS 的资格分更高。当前产品没有 PASS 内排序 consumer，因此 soft preference 完全退出资格损失、threshold 和
   verdict；未来若确需偏好排序，另立独立 head/模型和产品消费者，不反向并回 gate。
8. **损失结构保持同向**：训练合同围绕 `L_dim + λ_gate L_gate + λ_boundary L_boundary + λ_inv L_invariance` 建立；
   `L_dim` 是主体，其余只提供与 hard gate 同向的合取、定向边界和不变性辅助。精确权重与连续实现由执行者冻结，但不得重新加入
   Within-PASS ranking 或任何可补偿 overall-quality 目标。
9. **输入必须使标签可识别**：模型完成五项判断必须看到的 bounded、permission-scoped 公共任务事实由任务合同冻结，尤其不能让数据负责人
   依据 scorer 不可见的 `public_state`、candidate brief 或隐藏生成意图决定 useful-state/continuity 标签。若某项无法由正式输入判定，必须
   修改输入合同、标签或适用性，而不能期待模型通过规模或训练猜出隐藏事实。
10. **外部产品合同保持轻量**：多维判断和失败维度可以留在 scorer 内部与 eval 证据中；现有产品仍只消费 typed `PASS/REWRITE`，
    不因内部结构化而扩张 wire、引入自动改写、复杂解释协议或新的在线决策系统。
11. **全部数据活动从属于任务合同**：data schema、字段、样本类型、生成分块、数量与配比、标签、pair、renderer、盲审标准、split、统计门和
    验收指标都必须能追溯到任务合同中的明确需要；不能说明服务哪项输入可识别性、hard 判断、非补偿 gate、Boundary 或 invariance 目标的内容，
    不进入新 revision。不得把旧数据复用率、旧分布延续、历史投资保留或凑足规模当成独立目标。

## 未完成工作包

### 工作包四：模型资格验收与横评（未解锁）

**目标**：冻结候选与判定配置后，使用未参与训练和方案选择的集合完成本地资格、相对 base/历史候选及必要异构 reference 的同口径横评，
给出最终模型和 GO/NO-GO。

**解锁前置**：必须先有一个通过开发准入门的本地候选模型。工作包三没有形成候选，因此本包不启动，也不读取
`publication-critic-qualification-v1` 或 v9 test 正文。历次诊断与工程接入（含云端五维接缝）都不自动解锁本包。

**边界与宏观验收**：测试集只允许一次正式释放，不得用于返调任务、数据、模型或 threshold；资格以 false PASS、各 hard dimension 的失败召回、
两端 Boundary 闭合、总体 operating point、稳定性和有界运行资源为主，Within-PASS 只作 invariance/独立报告。任何真实本地模型、付费 API、
冻结测试释放和外部资源都在该任务开始前单独授权，历史余额与请求配额一律不转移。通过只解锁后续产品价值/启用决策，
不自动改变 default-off 或生产状态。

**重启方式**：若用户决定继续三期，须先决定路线（重新训练、更换基座，或直接以现有接缝做资格测量），再另立 ExecPlan 并重新取得授权；
本 WBS 的记录不构成任何授权。

## 串并行与资源关系

- 若工作包四或任何新的训练任务重新启动，其内部的本地准备与云端付费执行必须严格串行，付费阶段在本地阶段通过独立审查
  并取得明确批准前保持锁定。
- 数据类工作允许按独立模块并行：多个负责人和对应盲审员各自处理自己的块，冻结块之间互不返工；执行者最终只做机械整合与全局覆盖门。
- 三期与已经正式收口的方向 1 没有产品依赖。如果未来重新启动方向 1，普通工作仍可并行安排，但共享 API 预算、
  本地 GPU、Docker、构建锁和磁盘时必须显式错峰。
- 重型 Cargo、Docker 与真实本地模型加载/推理继续按根 `AGENTS.md` 全局串行。

## 现行产品语义合同

以下语义是现有产品事实，也是后续任何工作必须保持的基础。若确需改变，必须先更新本 WBS，不得由单次 plan 或提示词静默改写。

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
- Multi 不携带 RONDO Local 的 GGUF、本地模型 runtime 或部署默认。
- 产品身份贯通源码、构建、冻结 binary、manifest、adapter/RunSpec 与结果归档；数据资产继续遵循
  `doc/eval-data-layout.md`。
- 历史 binary、receipt、trace 与结果保持不可变，只作为对应阶段的完成证据，不冒充新任务的运行身份。
- Team Lens 是本地离线 reducer/viewer，不参与 runtime 调度，不保存正文，不建立第二套 tracing facility。
- 重型 Cargo、Docker 和真实本地模型继续按项目全局资源门禁串行。Multi 的受支持 Unix 重型入口共享物理仓库根
  `.codex/cargo-target/rondo-multi`；日常 Cargo 使用 `jobs=2`、GNU/Linux LLD 单线程和 2 个机器级 rustc 槽，要求尽量一次跑完的
  完整 workspace 使用受跟踪的 `test-with-codex-v8-conservative`（`jobs=1`、LLD 单线程）。付费 API 服从对应任务的范围、预算和授权，
  在不争用本地重型资源时可以与普通非重型工作并行。
- 不引入合规/取证平台、PKI/签名链、trust score、在线学习路由器、judge 集群、全量 transcript/CoT 广播、
  自由群聊、固定大 swarm 或通用副作用缓存。

## 外部授权与实施边界

- 历次三期任务的一次性外部授权（真实 API、GPU、本地模型、上传、卷处置等）**均已随各自终态关闭**，
  余额、provider 请求配额与数据权限一律不转移。逐任务的费用、资源终态与授权关闭记录见 `doc/WBS-COMPLETED.md`。
- **云端资源终态**：本项目当前不持有任何 RunPod Pod 或网络卷，也没有持续费用。历次任务中曾由用户决定保留的网络卷
  `mwemzrn33y` 已不存在，只存在于该卷上的大型 checkpoint 与权重不再可恢复；本地保留的是各任务当时已逐对象校验回传的证据。
  详见 `doc/WBS.md` 的「云端资源终态」。
- 以下动作在方向 3 内每次执行前都须针对具体任务单独授权：RunPod 创建或计费、云端训练、权重上传或下载、
  真实本地模型加载或推理、Docker、按量付费真实 API 批量测评、冻结测试集（`publication-critic-qualification-v1` 与 v9 test 正文）
  释放、Publication Critic 默认启用与任何生产动作。
- 训练数据、权重、逐样本输出与私有运行材料留在 `eval-data/` 或仓库外；`training/` 只保存体积合规的轻量合同与数据。
- 正确性测试随产品能力建设；测评只保留能指导模型选择和产品验收的轻量指标，不建设数据资产审计或可信证明平台。
