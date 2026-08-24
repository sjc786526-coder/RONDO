# 方向 3：RONDO Multi（Event 驱动的团队世界状态产品线）

最后更新：2026-08-23 ｜ 产品线：RONDO Multi（`multidev/`）｜ Codex 基线：`v0.147.0` ｜
状态：**第一期、第二期及 M3-A1、M3-A2、M3-B1a、M3-B2a、M3-B2b 已完成并主线整合；Plan 060 / M3-B1b 已完成规划、待执行**

## 当前定位

RONDO Multi 不重做 Agent 执行面。Codex 原生继续负责 thread、spawn/fork、并行执行、shared workspace、
mailbox、wait/resume/interrupt、工具执行、sandbox 与审批。RONDO Multi 只负责把值得团队持续知道的信息变成
Harness 拥有、可追溯、不会因模型遗忘或上下文压缩而静默消失的团队世界状态，同时不广播 transcript 与隐藏推理。

Multi 是与 RONDO Local 并列的独立产品线。当前定位是工程实践、Harness 创新与技术训练，不以跑赢冻结 Codex
Multi-Agent 作为存在前提。预期团队规模为 2–8 个 Agent，通常更少；不为大规模 swarm 预建复杂调度体系。

第一期、第二期 A/B/C 及 Plan 050 明确委派案例均已完成。实现、测试、运行结果、费用与独立验收统一见
`doc/WBS-COMPLETED.md`，本页不再维护其任务分解。

三期建设一个专用本地 **Publication Critic**：Producer 提交 `team_publish` 前，由小模型审查拟发布内容是否达到最低公共状态
质量。稳定产品语义见 [`doc/rondo-multi-publication-critic-product-contract.md`](../rondo-multi-publication-critic-product-contract.md)；
Producer、Critic、Harness、Root 的职责及现行 Team State 不变量以该合同为共同前置。

## 三期目标与冻结决定

### 产品目标

- Critic 审查完整 canonical publication candidate，四类 publication 使用统一最低质量原则；`PASS/REWRITE`、两次 Producer
  重写、最终非阻断发布、服务故障继续发布与取消不提交均按产品合同解释。
- 输入只来自有界、permission-scoped 的公共状态；V1 不读取 evidence 正文或验证 claim→Fact 语义，Critic 不自动改写、
  不决定事项是否值得发布，也不接管 route、分工或 Root 协调。

### 模型与训练边界

- 学生模型冻结为 `Skywork/Skywork-Reward-V2-Qwen3-1.7B`，目标是形成一个可在本地运行的专用发布质量模型。
- 云端训练冻结为单张 RunPod H100 PCIe 80GB 上的 BF16 全参数微调；付费 smoke 与正式训练共用 **23 USD** 总硬上限。
- FlashOptim/FlashAdamW 是主优化器路径；训练优先利用 80GB 显存保持配置宽松，减少不必要的量化、offload 和重算。
  具体依赖版本、优化器参数、batch、上下文长度、步数与工件格式由相应任务根据实测决定，不在长程 WBS 固定。
- 同一训练 lineage 依次加入 Binary qualification、Boundary/Q± 和少量 Within-PASS 监督，并保留前序样本避免遗忘。
  阶段 checkpoint 用于选择最好用的产品候选，不把每一阶段包装成独立产品、退役流程或完整学术消融矩阵。
- 数据以少量真实协作样本为锚点、教师合成为主体，保留必要的独立复核和冻结测试集；异构模型只承担最终辅助横评，
  不建立教师委员会、人工标注平台或严格盲测体系。

## 三期工作包与顺序

```text
M3-A1 产品合同与质量边界
        ├──────────────────────────────┐
        ↓                              ↓
M3-A2 数据/评价设施与基座测评      M3-B2a 本地 Critic 服务
        ↓                              ↓
M3-B1a 训练数据冻结               M3-B2b Multi 发布流程接入
        ↓                              │
M3-B1b H100 训练资格 smoke             │
        ↓                              │
M3-B1c 正式分阶段训练与工件回收          │
        └──────────────┬───────────────┘
                       ↓
                 M3-C1 本地部署资格
                       ↓
                 M3-C2 联合横评与最终选择
                       ↓
                 M3-D 端到端收口
```

四阶段叙事保持不变：A 阶段收口产品合同并建立轻量基准；B 阶段让模型链与产品链接力并行；C 阶段串行完成本地资格和
最终选择；D 阶段做端到端收口。阶段本身不是 ExecPlan 单位，以下每个工作包各对应一个独立 plan。

### A 阶段：共同前置与轻量基准

#### M3-A1：产品合同与质量边界（已完成）

**结果**：[`Publication Critic 产品合同`](../rondo-multi-publication-critic-product-contract.md) 已冻结完整被审 candidate、
最小公共输入与禁入边界、统一 qualification、hard/soft 分层、重写/故障/取消语义、角色职责及 Team State 不变量。

**边界**：只定义稳定产品语义和任务边界；不建设数据设施、不下载或运行模型、不修改产品代码，也不冻结模块布局、
API schema、训练超参数或部署格式。

**交接**：M3-A2 与 M3-B2a 可依赖同一产品合同分别建立自己的 task plan，不需互相等待。Plan 055 已冻结并通过独立验收的
M3-B2a 服务协议、identity 和资源数值；M3-A2 的数据/评价细节和状态不由该任务改写，M3-A1 本身未实现这些设施或
`team_publish` 接入。

#### M3-A2：数据/评价设施与基座测评（已完成）

**结果**：Plan 054 已冻结 Rust/Python PublicationPacket v1 机械约束 parity、control-token-safe render、exact tokenizer/scalar
identity、24 条代表/边界样本、两条产品 cap census case 和专用评价/归档设施。exact Skywork 1.7B 在 CPU FP32 下通过全部
scored-row single/repeat/左右 padding/替代 batch composition parity 与独立 16,384-token smoke；正式 16 样本 v4 基座结果为
accuracy / balanced accuracy `0.6875`、ROC AUC `0.765625`、atomic pair `7/8`，`16/16` 有效、零 typed failure，10 个冻结
error slice 均存在。tracked v4 同时保留 8 条 calibration 投影、context 与两阶段 watchdog 资源事实，并区分真实 batch wall time
和 amortized compute。v1-v3 保留为 superseded 历史 attempt；正式身份、切片、资源和 go/no-go 见
[`baseline v4`](../../eval/results/publication-critic/skywork-reward-v2-qwen3-1.7b-baseline-v4.md)。

**边界**：只建设 Publication Critic 必要设施和小规模代表性样本；不冻结正式训练数据，不启动付费训练，不扩张为通用
数据平台、审计系统或大型 benchmark。

**交接**：基座工程路径与 M3-B1a 数据建设 GO，未微调模型直接产品使用 NO-GO。M3-B1a 应复用 v4 输入/评价合同并建立独立
train/validation/unseen-test split，优先补足 `internal_consistency` 精致 hard negative、new/completed useful-state 边界、
threshold-near handoff 与 continuity/evidence omission 对照，并避免长度、角色和模板捷径。M3-A2 cohort 不得冒充未来 unseen test；
M3-C1 继续等待 M3-B1c 提供至少一个训练候选。

### B 阶段：模型链与产品链并行

#### M3-B1a：训练数据冻结（已完成）

**目标**：在 M3-A2 的设施和基线之上形成并冻结训练、验证与测试数据，覆盖 Binary、Boundary/Q± 和少量 Within-PASS 监督。

**边界**：少量真实协作样本只作锚点，教师合成为主体；保留必要独立复核，不建立教师委员会、人工标注平台或严格盲测体系。

**宏观验收**：数据覆盖核心质量边界，没有明显模板、标签或近重复捷径；训练输入规模、split 和各阶段监督范围明确，能够独立
交给 M3-B1b，而不需要在付费 smoke 中继续改数据合同。

**结果**：Plan 059 revision v7 已正式冻结并完成最终独立验收与主线整合：36 scenario group、72 candidate
（train / validation / unseen-test 为 42/16/14，39 PASS / 33 REWRITE）、30 Boundary 与 6 Within-PASS；C1/C2/C3 为
42 Binary、再加 18 Boundary、再加 3 Within-PASS。受影响的 12 个 Scope endpoint、6 个 Boundary 与 1 个 Within-PASS 已独立复核，
其余 review 只在模型可见输入逐字节相等后复用。group closure、Plan 054 reference 隔离、文本与 exact-token 长度 shortcut、50,073-token
census、manifest、factory-only consumer 和 train-only smoke bundle 均通过；最终结论为数据 GO，`remaining_findings=[]`。

**交接**：M3-B1b 的数据前置已经解锁，但本结论不是训练或模型质量证据，也不授权付费运行。M3-B1b 仍须独立 ExecPlan 与
RunPod/H100、训练、上传和预算授权，并只执行有界资格 smoke。

#### M3-B1b：H100 训练资格 smoke（独立 go/no-go 门）

**目标**：在单张 RunPod H100 PCIe 80GB 上验证 Skywork 1.7B BF16 全参数训练、FlashOptim/FlashAdamW 主路径、阶段保存与恢复
是否适合进入正式训练。

**边界**：只运行有界资格 smoke，不顺带启动正式训练；本包需要单独的付费授权，并与 M3-B1c 的正式训练授权分离。

**当前状态**：Plan 060 已在专用 worktree 建立任务合同，采用本地 readiness→单 Pod commissioning→冻结身份后的干净正式 smoke→止费验收；
资格执行尚未开始，也没有产生 H100、FlashAdamW、checkpoint、费用或清理证据。进入执行仍须用户一次性授权唯一 H100 PCIe 80GB Pod、
train-only 上传、6 USD 任务硬上限和完整资源回收；M3-B1c 保持锁定。

**宏观验收**：模型、数据、环境、显存、吞吐、保存/恢复和预算余量形成明确 go/no-go 结论。no-go 时停止训练链并更新 WBS，
不得自动消耗剩余预算继续训练或静默更换未授权路线。

#### M3-B1c：正式分阶段训练与工件回收

**目标**：在 M3-B1b 给出 go 结论并另行授权后，沿同一 lineage 连续完成研究设计中的 C1→C2→C3 训练，回收各阶段候选与
必要运行结果。这里的 C1/C2/C3 是训练 checkpoint 名称，不是 M3-C1/M3-C2 工作包编号。

**边界**：三个训练 checkpoint 留在同一 ExecPlan 内，不拆成行政任务；不扩展候选底模池、不建设通用训练平台、不追加
论文式大规模消融。M3-B1b 与本包共用 23 USD 总硬上限。

**宏观验收**：正式训练在预算内完成或按门禁诚实停止；各阶段候选、必要恢复工件和同口径指标安全回收，至少一个候选可进入
M3-C1。最后一个 checkpoint 不自动获得产品资格。

#### M3-B2a：本地 Critic 服务（已完成并通过独立验收）

**结果**：Plan 055 新建专用 `codex-publication-critic` crate，以 loopback framed JSON 提供版本化协议、调用方可信配置绑定的
service/model/scoring identity、可替换 scorer、typed client 与有界生命周期。受控 backend 的真实服务进程测试覆盖
PASS/REWRITE、严格解析、identity/score 漂移、并发/队列、timeout/cancel、异常退出和关闭回收；尚未运行真实模型。

**边界**：本包只负责模型服务与稳定调用边界，不修改 Multi 发布流程，不复用 RONDO Local 的审批模型产品合同，也不建设
第二套 trace、复杂鉴权或通用模型服务平台。typed packet 没有任意 metadata 扩展袋，但 B2a 不声明能识别合法文本字段中被
手工粘入的私密语义；canonical 来源与 packet 构造仍属于 M3-B2b。

**交接**：M3-B2b 已按 Plan 057 消费公开 typed verdict/failure 与 expected identity 配置边界，完成实现、定向门禁、审查整改和最终独立验收；
最终 threshold、真实训练权重和部署资格仍留给后续评价/资格工作包。

#### M3-B2b：Multi 发布流程接入（已完成并通过独立验收）

**结果**：Plan 057 已把默认关闭的 typed Critic 配置接入 `team_publish` 前置流程。关闭态保留原工具合同和 store 路径；启用态审核
Team State 共享 canonical preparation，以 event-local 单页公共 history 构造 Plan 055 packet，最多返回两次固定 rewrite，第三次审核
非阻断，typed failure 只回退到唯一一次现行 store commit。committed/attempt replay、取消、并发与 body-free 观测均有聚焦回归，代表性
产品路径启动 Plan 055 正式服务进程并走正式 typed client；尚未运行真实模型。

独立审查发现的 cycle 隔离、continuation 阶段授权、锁内 bounded history 与 body-redacted trace 终态问题均已修复：无关请求不清理
active cycle，每次阻断反馈轮换 continuation，Team State 专用 history 不携 route/Fact ID，PostToolUse feedback 保留安全终态。

**边界**：只增加 Publication Critic 所需产品能力；不接管 Producer/Root 语义，不新建 Agent 间协议、第二套 Team State、
调度器或自动重写器。实现可以为保持边界干净而重构，不要求堆叠在现有 handler 上。

**交接**：修复与定向门禁已完成，同一独立审查者最终复验结论为 PASS，成果已进入主线；产品链已具备进入 M3-C1 的前置能力，但仍等待模型链完成。
本包不冻结真实 threshold/model identity，不扩张为自动改写器、第二套 Team State/trace 或通用服务监督器。

### C 阶段：本地收敛与最终选择

#### M3-C1：本地部署资格

**目标**：在模型链和产品链均完成后，把候选训练模型部署到目标本地环境，关闭格式、量化、资源和服务兼容性问题。

**边界**：只判断候选是否具备本地产品资格，不在本包进行最终模型排名；出现模型或服务问题时回到对应能力修正后重新验收，
不边修部署边改最终横评口径。

**宏观验收**：明确各候选是否具备本地资格，且至少一个候选能稳定处理有界 publication；其延迟、显存和失败率适合
2–8 Agent 场景，格式转换或量化没有造成不可接受的判定漂移，离线 runner 与产品 runtime 判定一致。

#### M3-C2：联合横评与最终选择

**目标**：对已经通过本地部署资格的基座与训练阶段候选做同口径横评，选定最终模型、判定边界和运行配置。

**边界**：只使用冻结评价口径和已取得资格的候选；异构 Judge 仅作辅助参考，不建立评审委员会，也不把最后 checkpoint
或单一总分默认为赢家。

**宏观验收**：发布质量、False PASS/REWRITE、边界样本、延迟和本地资源开销得到联合比较；最终选择有清晰理由且可由现有
轻量设施复测，未达标则回到对应工作包迭代而非建立模型退役制度。

### D 阶段：端到端收口

#### M3-D：端到端收口

**目标**：在少量代表性 RONDO Multi 协作流程中验证 Critic 确实改善发布质量且没有破坏团队状态与协作节奏，随后把能力
收口为可持续使用的产品功能。

**边界**：只做足以验证产品价值的轻量真实案例，不扩张成大规模任务成功率研究，也不把离线改善外推成普遍协作提升。

**宏观验收**：

- Producer 能按有限反馈完成重写，Root 仍只消费正常公共状态并保持原协调职责；
- 开启与关闭 Critic 的代表性流程均正确，额外延迟、失败回退和发布质量达到可接受水平；
- 相关正确性测试纳入既有测试体系，必要测评可复跑并自动归档；
- 完成证据归档到 `doc/WBS-COMPLETED.md`，本页只保留最终产品事实和后续仍有效的边界。

## 串并行与资源关系

- M3-A1、M3-A2 已完成共同前置。数据/训练链当前按 `M3-B1a → M3-B1b → M3-B1c` 串行；产品链的 M3-B2a、M3-B2b 均已完成。
  两链彼此并行，产品链等待模型链完成后再进入 M3-C1。
- M3-B1b 是独立付费资格门，M3-B1c 只有在 go 结论和新的正式训练授权后才能开始；no-go 不自动继续消费预算。
- M3-C1 等待 M3-B1c 与 M3-B2b，M3-C2 等待 M3-C1，M3-D 最后串行收口。
- RunPod 云端 smoke/训练可以与不占用本地重型资源的产品代码、数据整理和受控替身测试并行；真实本地模型、Docker 与
  重型 Cargo 仍按根 `AGENTS.md` 全局串行。
- 三期与方向 1 没有产品依赖。方向 1 重启后可以并行安排普通工作，但共享 API 预算、本地 GPU、Docker、构建锁和磁盘时
  必须显式错峰。
- M3-A1、M3-A2、M3-B1a、M3-B1b、M3-B1c、M3-B2a、M3-B2b、M3-C1、M3-C2、M3-D 各自对应一个任务级 plan；
  阶段叙事不单独创建总 plan，长程 WBS 也不替执行者冻结模块布局、API schema、训练超参数或部署技术路线。

## 现行产品语义合同

以下语义是现有产品事实，也是三期必须保持的基础。若后续确需改变，必须先更新本 WBS，不得由单次 plan 或提示词静默改写。

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
- 历史 binary、receipt、trace 与结果保持不可变，只作为对应阶段的完成证据，不冒充三期运行身份。
- Team Lens 是本地离线 reducer/viewer，不参与 runtime 调度，不保存正文，不建立第二套 tracing facility。
- 重型 Cargo、Docker、真实本地模型和付费 API 继续按项目全局资源门禁串行。
- 不引入合规/取证平台、PKI/签名链、trust score、在线学习路由器、judge 集群、全量 transcript/CoT 广播、
  自由群聊、固定大 swarm 或通用副作用缓存。

## 外部授权与实施边界

- M3-A1 产品合同与 Plan 054 / M3-A2 已完成；M3-B2a 已按 Plan 055 完成实现、独立验收与主线整合；M3-B2b 已按 Plan 057 完成实现、
  审查整改、最终独立验收与主线整合。其余后续工作包启动时仍须按 `plan/plan-example.md` 建立任务合同并取得授权。
- RunPod 创建或计费、模型与数据上传、云端训练、权重下载、真实本地模型加载/推理、Docker 和付费 API 均须在对应任务
  开始前取得明确授权；23 USD 是三期训练的总预算上限，不等于已经授权消费。
- 训练数据、权重、逐样本输出与私有运行材料留在 `eval-data/` 或仓库外；`training/` 只保存体积合规的轻量合同与数据。
- 正确性测试随产品能力建设；测评只保留能指导模型选择和产品验收的轻量指标，不建设数据资产审计或可信证明平台。
