# 方向 3：RONDO Multi（Event 驱动的团队世界状态产品线）

最后更新：2026-08-27 ｜ 产品线：RONDO Multi（`multidev/`）｜ Codex 基线：`v0.147.0` ｜
状态：**第一期、第二期已完成；Publication Critic 三期 Plan 095 云端参考 scorer backend 已完成全部窄修、最终代码真实 API smoke、
Sol 最终复验与本地 main 集成，当前为 `COMPLETED / FINAL_REVIEW_ACCEPTED / GOAL_COMPLETED / INTEGRATED_LOCAL / NOT_PUSHED`。Plan 094 的
`ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT / ZERO_POD / VOLUME_RETAINED / FINAL_REVIEW_ACCEPTED` 终态保持有效；Plan 095 与训练路线正交，
不验证独立 cohort、unseen 或产品资格，M3-D 保持锁定**

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
Plan 095 已在同一服务边界增加 eval/reference-only 的云端 scorer backend，不改变上述本地产品目标或默认关闭姿态。

四期 Durable Team Runtime 已正式收口，终态为 `M4_W1_PASS / PHASE_4_COMPLETE`，没有后续必需工作包；完整历史见
`doc/WBS-COMPLETED.md`，简要归档入口见 [`doc/WBS/durable-team-runtime.md`](durable-team-runtime.md)，本页只继续维护三期路线。

## 当前 Linux 正确性基线

Plan 093 在 RONDO Multi 的 default features、standard local Nextest 与 checksum-verified V8 口径下，从空的产品级共享 target
完成冷 workspace，并在有界修复后于实现提交 `b25b5bb2e57490b8615a8c5c1c432c0fe39440db` 完成正式全 workspace：
`14660/14660` passed、0 failure/error/timeout，另有 1/1 Unix setup passed；24 个 skip 按平台、手工/生成/property、child helper、
已延后不稳定项和真实 API smoke 分类，不计 passed。唯一 loopback proxy retry 已在新进程 `retries=0` 下 1/1 一次通过。

正式证据保留在 `test-data/_retained-test-evidence/plan093-clean-full-workspace-baseline/runs/final-b25b5bb2e574-20260827T071344Z/`，
JUnit SHA-256 为 `ef2d16c4e1f4d1bfb411ddf7fe47127a0b7832cf7f35e649d1fe239e44f55e4b`。随后只持久化等效构建资源配置和文档，
没有改产品测试语义或重复完整 workspace；合同测试 7/7、日常入口窄编译/链接/测试 18/18、保守 V8 入口 18/18 均通过，独立验收
High/Medium/Low correctness finding 为 0。

## 三期目标与冻结决定

### 产品目标

- Critic 审查完整 canonical publication candidate，四类 publication 使用统一最低质量原则；`PASS/REWRITE`、两次 Producer
  重写、最终非阻断发布、服务故障继续发布与取消不提交均按产品合同解释。
- 输入只来自有界、permission-scoped 的公共状态；V1 不读取 evidence 正文或验证 claim→Fact 语义，Critic 不自动改写、
  不决定事项是否值得发布，也不接管 route、分工或 Root 协调。

### 模型与训练边界

- 学生模型冻结为 `Skywork/Skywork-Reward-V2-Qwen3-1.7B`，目标是形成一个可在本地运行的专用发布质量模型。
- Plan 079 已以 exact `Skywork/Skywork-Reward-V2-Qwen3-4B@fd958fef475f323f4e6b195930e3dd918485c668`
  原始 BF16 base 独立验证更大同家族基座的云端质量，终态为 `4B_BASE_QUALITY_NO_GO`；它没有改写 1.7B 训练历史，也没有训练、
  量化或授予本地产品资格。
- Plan 060/066 已历史性证明单张 RunPod H100 PCIe 80GB 上的 BF16 全参数 FlashAdamW 训练、checkpoint 与恢复技术可行；
  该固定 recipe 后续出现模型质量与排序退化，因此不再作为当前冻结路线，也不改写其当时的技术/执行成功事实。
- Plan 087 已在 exact BF16 1.7B、既有 pair/input 与冻结 v8、非 PEFT/非量化边界内完成 15 条自适应路线。Plan 090 随后冻结 Route O
  的九张量、`33,558,784` 原参数配方并从 exact base 完成两次 clean BF16 execution；两次均重复同一小幅 validation 正向 signature，
  第二候选经不同进程恢复，结论为 `ROUTE_O_CONFIRMATION_PASS`。正式路径没有 seed-sensitive consumer，因此不宣称随机 seed 稳定；
  条件性 FP32 对照的 raw/projected 分歧只作为精度路径诊断。
- Plan 094 保持 exact 1.7B、冻结数据/pair/input/objective 家族、unseen 隔离和 Route O 九张量唯一更新范围，通过连续训练、完整 checkpoint
  后测评、fresh-process 恢复和同轮 exact base 比较，判断上述微弱信号能否形成有意义的 ranking、strict 或 operating 改善。训练强度、
  checkpoint 密度和调度由执行者依据实测决定；material/停止/保留规则须在正式结果前冻结。
- 训练控制须支持多个连续更新/观测点、同口径 validation 质量趋势、模型评价快照与完整恢复 checkpoint 分层，以及
  base/best/latest/少量关键转折点保留。base 继续作为研究 incumbent，只有同口径优于 base 的训练结果才成为目标候选；
  未优于 base 时诚实记录 no-improvement。当前研究不要求候选直接达到产品 GO，开发期 validation 不冒充 M3-C2 或 unseen 证据。
- 数据以少量真实协作样本为锚点、教师合成为主体，保留必要的独立复核和冻结测试集；异构模型只承担最终辅助横评，
  不建立教师委员会、人工标注平台或严格盲测体系。

## 三期工作包与顺序

```text
M3-A1 产品合同与质量边界
        ├──────────────────────────────┐
        ↓                              ↓
M3-A2 数据/评价设施与基座测评      M3-B2a 本地 Critic 服务
        ↓                              ↓
M3-B1a v7 数据冻结                M3-B2b Multi 发布流程接入
   ┌────┴─────┐                        │
   ↓          ↓                        │
M3-B1b      Plan 064 v8 数据扩充         │
技术 GO      已冻结，DATA_GO              │
   └────┬─────┘                        │
        ↓                              │
M3-B1c 正式分阶段训练与工件回收          │
        └──────────────┬───────────────┘
                       ↓
                 M3-C1 本地部署资格（已完成）
                       ↓ Plan 071 base 同口径重验已通过
        M3-C2 联合横评与最终选择（Plan 073 `NO-GO`）
                       ↓
        Plan 079 Skywork 4B 云端基座质量测评（`4B_BASE_QUALITY_NO_GO`）
                       ↓
        Plan 081 exact 1.7B 非 LoRA 本地训练就绪（已完成）
                       ↓ `LOCAL_TRAINING_READINESS_PASS` 已成立
        Plan 082 云端连续训练与候选形成（已完成；`VALID_NO_IMPROVEMENT`，0 Pod，用户决定保留卷且仍未删除）
                       ↓
        Plan 087 云端自适应原参数路线搜索（已完成；`PROMISING_CANDIDATE_RETAINED`，0 Pod）
                       ↓
        Plan 090 Route O 干净复现与执行/数值重复确认（已完成；`ROUTE_O_CONFIRMATION_PASS`，0 Pod）
                       ↓
        Plan 094 Route O 连续训练与实质增益候选形成（有效负向终态；zero-Pod 收口及最终验收完成）
                       ↓
                 M3-D 端到端收口（未解锁）

并列 reference 支线：M3-B2a 已有可替换 service → Plan 095 云端参考 scorer backend（最终验收通过，已集成本地 main；不解锁 M3-D）
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
M3-B1c 已提供通过独立验收的训练候选；Plan 068 / M3-C1 随后完成本地交接、真实部署资格、独立验收与远端止费。

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

**交接**：M3-B1b 的数据前置已经解锁，Plan 060 已据此完成正式 smoke 并通过独立验收；本结论本身不是训练或模型质量证据。
Plan 060 的技术 GO、v8 DATA_GO 与 Plan 066 授权现已共同解锁正式训练。

#### M3-B1c 数据规模前置：Plan 064（已完成，DATA_GO）

**结果**：`publication-critic-v8` 已正式冻结并完成最终独立验收：123 scenarios、228 candidates、104 pairs，
train/validation/unseen-test 为 128/55/45，exact-token 总量 178,646；C1/C2/C3 为 128 Binary、50 Boundary、
再加 8 Within-PASS。默认 consumer 只暴露 train，显式 evaluation 模式才可访问完整 228 candidates。v7 物理 tree、继承成员与
split 保持不变，Plan 060 继续使用原 smoke bundle。

**资格结论**：覆盖、review、lineage、group/split、dedup/shortcut、tokenizer-only、manifest、bundle 和 consumer 门禁均通过。
v8 冻结时的“证据不足（训练预算适配未决）”已由 Plan 060 final-19 的正式吞吐、checkpoint/恢复、费用和 23 USD 连续总账有界复核闭合；
三个阶段各一遍约 451,743 tokens，当前结论为 `DATA_GO`。这只证明冻结规模适合进入有界训练，不保证模型质量改善。

**交接**：有界预算适配不生成新数据、不改 split/label/review、不重做 freeze。Plan 060 技术 GO、v8 DATA_GO 和新的正式训练授权均已成立；
Plan 066 已复用当时的热资源执行 M3-B1c，计算资源终态见下文。

#### M3-B1b：H100 训练资格 smoke（独立 go/no-go 门）

**状态**：Plan 060 final-19 已完成正式 smoke、本地提交和独立验收，`remaining correctness/functionality findings=[]`，M3-B1b 结论为
`TECHNICAL_GO`。用户当时决定把 RUNNING Pod、胜者卷和连续费用总账直接交给 Plan 066；后者现已删除计算 Pod，并统一收口 resource terminal facts
与控制台任务期账单。

**目标**：在单张 RunPod H100 PCIe 80GB 上验证 Skywork 1.7B BF16 全参数训练、FlashOptim/FlashAdamW 主路径、阶段保存与恢复
是否适合进入正式训练。

**边界**：只运行有界资格 smoke，不顺带启动正式训练；本包需要单独的付费授权，并与 M3-B1c 的正式训练授权分离。

**当前状态**：Plan 060 已在 Secure 单卡 `NVIDIA H100 PCIe` 80GB、US-KS-2 上完成 BF16 全参数 FlashAdamW commissioning 和
final-19 干净 formal start/resume。C1→C2→C3、1,720,577,024 个 trainable 参数/311 个 optimizer tensor 覆盖、约 10.56GB 完整
checkpoint、新 OS 进程恢复与 step 3→4 继续更新均通过；最终 archive 与三项审查整改独立复核 `remaining_findings=[]`。
正式 receipts 已回收，独立验收结论为 `TECHNICAL_GO`。final-19 checkpoint、exact 模型、venv、FlashOptim 与 cache 曾随胜者 Standard 卷
直接交给 Plan 066；新恢复点验证后 final-19 checkpoint 已删除，其余可复用资产继续保留。Plan 060/066 的最终任务费用以用户确认的控制台任务期账单为准，
provider terminal facts 已由 Plan 066 收口。

**宏观验收**：模型、数据、环境、显存、吞吐、保存/恢复和预算余量形成明确 go/no-go 结论。no-go 时停止训练链并更新 WBS，
不得自动消耗剩余预算继续训练或静默更换未授权路线。

#### M3-B1c：正式分阶段训练与工件回收

**目标**：Plan 060 / M3-B1b 技术 GO、冻结 v8 DATA_GO 与新的正式训练授权已经成立；Plan 066 沿同一 lineage 连续完成研究设计中的
C1→C2→C3 训练，回收各阶段候选与必要运行结果。
这里的 C1/C2/C3 是训练 checkpoint 名称，不是 M3-C1/M3-C2 工作包编号。

**边界**：三个训练 checkpoint 留在同一 ExecPlan 内，不拆成行政任务；不扩展候选底模池、不建设通用训练平台、不追加
论文式大规模消融。Plan 060 GO 与 Plan 064 DATA_GO 已成立；M3-B1b 与本包共用 23 USD 连续总硬上限。

**宏观验收**：正式训练在预算内完成或按门禁诚实停止；各阶段候选、必要恢复工件和同口径指标安全回收，至少一个候选可进入
M3-C1。最后一个 checkpoint 不自动获得产品资格。

**当前状态**：Plan 066 `final-01` 已从 exact base 干净完成 C1→C2→C3，实际消费 128 Binary、C2 加 50 Boundary、C3 再加 8
Within-PASS，共 451,743 tokens；三阶段均完成 1,720,577,024 个 BF16 参数和 311/311 optimizer tensors 的 FlashAdamW 有限更新。
C1/C2/C3 三个 model-only safetensors 候选、55-candidate 固定 validation、正式 C3 full checkpoint 和新进程 step 3→4 恢复继续均已形成并复验；
validation 不进入梯度或训练决策，unseen-test 未导出、未运行。计算 Pod 已停止并永久删除；Plan 068 随后把 formal checkpoint、三个候选、
exact 模型与必要环境安全交接到本地，并在独立复验接受后永久删除 winner 卷。final-01 terminal receipt 已 superseded，final-02 保留生成时的控制台费用快照。独立终审按用户指定冻结最新 provider 快照总费用
`$10.9647715263`，距 `$23` 上限 `$12.0352284737`；correctness/functionality `remaining_findings=[]`，M3-B1c 完成并验收通过。
该结论本身不授予产品资格；四对象的本地资格结论见 M3-C1。

#### M3-B2a：本地 Critic 服务（已完成并通过独立验收）

**结果**：Plan 055 新建专用 `codex-publication-critic` crate，以 loopback framed JSON 提供版本化协议、调用方可信配置绑定的
service/model/scoring identity、可替换 scorer、typed client 与有界生命周期。受控 backend 的真实服务进程测试覆盖
PASS/REWRITE、严格解析、identity/score 漂移、并发/队列、timeout/cancel、异常退出和关闭回收；本包验收时尚未运行真实模型，
真实 scorer 后由 Plan 068 接入同一服务边界。

**边界**：本包只负责模型服务与稳定调用边界，不修改 Multi 发布流程，不复用 RONDO Local 的审批模型产品合同，也不建设
第二套 trace、复杂鉴权或通用模型服务平台。typed packet 没有任意 metadata 扩展袋，但 B2a 不声明能识别合法文本字段中被
手工粘入的私密语义；canonical 来源与 packet 构造仍属于 M3-B2b。

**交接**：M3-B2b 已按 Plan 057 消费公开 typed verdict/failure 与 expected identity 配置边界，完成实现、定向门禁、审查整改和最终独立验收；
最终 threshold、真实训练权重和部署资格仍留给后续评价/资格工作包。

#### M3-B2b：Multi 发布流程接入（已完成并通过独立验收）

**结果**：Plan 057 已把默认关闭的 typed Critic 配置接入 `team_publish` 前置流程。关闭态保留原工具合同和 store 路径；启用态审核
Team State 共享 canonical preparation，以 event-local 单页公共 history 构造 Plan 055 packet，最多返回两次固定 rewrite，第三次审核
非阻断，typed failure 只回退到唯一一次现行 store commit。committed/attempt replay、取消、并发与 body-free 观测均有聚焦回归，代表性
产品路径启动 Plan 055 正式服务进程并走正式 typed client；本包验收时尚未运行真实模型，后续真实资格由 Plan 068 完成。

独立审查发现的 cycle 隔离、continuation 阶段授权、锁内 bounded history 与 body-redacted trace 终态问题均已修复：无关请求不清理
active cycle，每次阻断反馈轮换 continuation，Team State 专用 history 不携 route/Fact ID，PostToolUse feedback 保留安全终态。

**边界**：只增加 Publication Critic 所需产品能力；不接管 Producer/Root 语义，不新建 Agent 间协议、第二套 Team State、
调度器或自动重写器。实现可以为保持边界干净而重构，不要求堆叠在现有 handler 上。

**交接**：修复与定向门禁已完成，同一独立审查者最终复验结论为 PASS，成果已进入主线；产品链与 Plan 066 模型链均已具备
M3-C1 前置，Plan 068 已复用本服务接缝完成真实模型资格运行。本包不冻结真实 threshold/model identity，不扩张为自动改写器、第二套 Team State/trace
或通用服务监督器。

### C 阶段：本地收敛与最终选择

#### M3-C1：本地部署资格（已完成）

**目标**：在模型链和产品链均完成后，把候选训练模型部署到目标本地环境，关闭格式、量化、资源和服务兼容性问题。

**边界**：只判断候选是否具备本地产品资格，不在本包进行最终模型排名；出现模型或服务问题时回到对应能力修正后重新验收，
不边修部署边改最终横评口径。

**宏观验收**：明确各候选是否具备本地资格，且至少一个候选能稳定处理有界 publication；其延迟、显存和失败率适合
2–8 Agent 场景，格式转换或量化没有造成不可接受的判定漂移，离线 runner 与产品 runtime 判定一致。

**结果**：Plan 068 已完成 120/120 个必要对象（24,385,153,354 bytes）及正式 checkpoint 的本地交接，以原始 safetensors、
CUDA BF16 scorer 和 CPU FP32 reference 接入 Plan 055/057 既有服务接缝。唯一有效正式轮
`plan068-formal-20260824T222852Z-qualification-v3` 给出 base `NOT_QUALIFIED`、C1 `QUALIFIED`、
C2 `NOT_QUALIFIED`、C3 `QUALIFIED`：base 因 projected drift `0.03404159` 与 1 次临时 verdict mismatch 未通过，
C2 因 ranking 与 direction 门未通过；C1/C3 的 runner/service projected parity、verdict parity、15/15 stress 与本地资源门通过。
资格运行未读取 unseen-test，也未转换、量化、继续训练或修改冻结权重。

**交接**：本地副本和身份经独立复验接受后，exact RunPod winner 卷 `hi3iaz8rsr` 已永久删除；当前 RunPod 为 0 Pod、
0 volume，compute/volume 持续费用均为 0，必要本地资产继续保留。Plan 071 随后在不改冻结权重、数据、产品语义或最终
threshold 的前提下，以同一冻结规则重验 exact base、C1、C3；唯一有效正式轮
`plan071-formal-20260825T064600Z-qualification-v5` 给出三者均 `QUALIFIED`，C2 保持 Plan 068 历史
`NOT_QUALIFIED`。最终独立验收接受 `BASE_COMPARABILITY_GO`，`m3_c2_prerequisite_satisfied=true`。

#### M3-C2：联合横评与最终选择

**目标**：对已经通过本地部署资格的基座与训练阶段候选做同口径横评，选定最终模型、判定边界和运行配置。

**边界**：只使用冻结评价口径和已取得资格的候选；异构 Judge 仅作辅助参考，不建立评审委员会，也不把最后 checkpoint
或单一总分默认为赢家。

**宏观验收**：发布质量、False PASS/REWRITE、边界样本、延迟和本地资源开销得到联合比较；最终选择有清晰理由且可由现有
轻量设施复测，未达标则回到对应工作包迭代而非建立模型退役制度。

**当前状态**：Plan 073 已完成并进入主线。正式 validation 在同一冻结协议下比较 exact base、C1、C3，三者均未达到
发布质量底线，终态为 `NO-GO`；没有 selection lock、unseen-test 释放或最终模型/threshold/运行配置。Publication Critic
保持 default-off，M3-D 保持锁定；Plan 075 已完成原因调研与路线决策，详细历史见 `doc/WBS-COMPLETED.md`。

#### Plan 079：Skywork 4B 云端基座质量测评（已完成并通过独立验收）

**结果**：[`Plan 079 ExecPlan`](../../plan/079-multi-publication-critic-skywork-4b-base-quality-execplan.md) 已完成并通过独立验收。exact 4B
正式轮 `plan079-formal-20260825T175912Z-610d880-r1` 从 clean source 与空 namespace 完成 55/55、零 typed failure，并经本地独立
复算得到 `4B_BASE_QUALITY_NO_GO`：无 admissible operating point，False PASS `12/21 = 0.5714`、False REWRITE
`4/34 = 0.1176`、balanced accuracy `0.6555`、ROC AUC `0.6218`、boundary `13/19 = 0.6842`、within-PASS `6/7`。
精炼结果见
[`skywork-reward-v2-qwen3-4b-base-quality-v1.md`](../../eval/results/publication-critic/skywork-reward-v2-qwen3-4b-base-quality-v1.md)。

**正式身份**：任务在 `US-IL-1` 的单张 Secure Cloud RTX 4090 上使用物理不含 unseen-test 的冻结 v8 train+validation bundle、
相同 typed packet/render/16,384 overflow/scalar/pair/指标；commissioning 先形成 `COMMISSIONING_COMPLETE`，随后唯一正式轮绑定 exact
官方两分片 BF16 snapshot、source、bundle/release、runtime receipt 与同一结果相关配置。4B logits 全为强正值并在 sigmoid 后高度饱和，
但 NO-GO 由完整 97 点 operating curve 和冻结门限决定，不是共享 threshold 或基础设施失败。

**边界**：不训练、量化、转换、重跑 1.7B/C1/C2/C3、重问 Judge、修改数据/门限、读取 unseen、启用产品或启动 M3-D。
职责契合时复用 Plan 054/066/073 的输入、bundle、scoring、metrics 与 archive；三候选、单文件或 Judge/selection 语义不契合时可增加
小型 4B base 专用能力，但不复制第二套评价体系。

**资源终态**：任务 Pod `iocp8k8w6zvh4s` 已删除，GPU 持续费用为 0；Plan 079 完成时曾按用户指令保留 20 GB Standard 网络卷
`v1us0nmk0p`，其 task root 当时用量为 8,242,665,809 bytes。用户提供的最新查询显示该卷当前返回 404、已不存在；Plan 082
在创建资源前仍通过既有安全入口复核，不依赖或尝试恢复旧卷。Plan 079 未运行本地重型 Cargo、Docker 或真实本地模型，也未使用
RTX 6000 Ada。

**交接**：Plan 079 没有形成训练、量化、本地部署、产品启用或 M3-D 资格；Plan 075 的 1.7B 路线判断仍只作为历史研究。
后继 Plan 081 已完成；其 PASS 仍不从本 NO-GO 自动取得真实模型、GPU、云端或训练授权。

#### Plan 081：exact 1.7B 非 LoRA 训练路线本地收敛与云端就绪（已完成）

**任务合同**：[`Plan 081 ExecPlan`](../../plan/081-publication-critic-non-lora-local-training-readiness-execplan.md)。

**目标**：保持 exact 1.7B、冻结 pair/input/v8 与 unseen 隔离，禁止 LoRA/QLoRA；在不运行真实模型/GPU/云端的前提下，
以 fixture/fake 打通可从部分参数直接更新起步并按训练动态扩大的连续训练控制、同口径质量观察、checkpoint/恢复、候选保留和结果归档；
选择语义区分 base incumbent、训练序列内部 best、better-than-base candidate 与 no-improvement。

**边界**：职责契合时复用 Plan 060/066 数据、checkpoint/恢复与 Plan 073 指标；旧固定 recipe 扭曲新语义时增加专用薄能力，
不得复制第二套数据/评价/训练平台，不冻结具体层数、LR、batch、更新数或 optimizer。开发期 validation 可驱动观察/选择，
但不进入梯度、不读取 unseen，也不冒充正式 M3-C2 或产品资格。

**当前状态**：最终实现 `87929a50bb031f418ef5e1f55784e1d5b538dd23` 已通过指定审查者主审与三路独立复核，无剩余
P1/P2/P3；Plan 081 fixture/fake 36/36 与 Plan 060/066/073 精选历史回归 9/9 通过。路线、连续训练观察、候选/no-improvement、
checkpoint/恢复/保留与云端 handoff 的本地轻量闭环完整，结论为 `LOCAL_TRAINING_READINESS_PASS`。本结论不包含真实模型、GPU、
云端训练或真实质量候选，也不解锁 M3-D。Plan 082 现已独立立项；这不改写 Plan 081 的历史能力声明。

**交接**：Plan 082 只需完成真实环境 commissioning 和训练参数开发，其云端边界为单张
A40 48GB 首选、L40S 48GB 备选，实际训练活动不超过 12 小时/15 USD，后续资源保留与无 Pod 回传费用分账报告；真实训练的研究成功是形成
同口径优于 exact 1.7B base 的候选，不要求直接达到产品 GO。Plan 079 旧卷不是前置；Plan 082 先执行不付费阶段 A，最终审查者验收
阶段 A 后仍须用户本人明确人工批准才进入付费阶段。

#### Plan 082：exact 1.7B 云端连续训练与候选形成（已完成）

**任务合同**：[`Plan 082 ExecPlan`](../../plan/082-publication-critic-cloud-continuous-training-execplan.md)。

**当前状态**：用户付费批准生效后，Plan 082 已在 US-TX-3 单张 Secure L40S 上完成真实 commissioning、正式 freeze、从 exact base/
空 namespace 开始的四步 score-head 干净正式轮和 step 2 新进程恢复，终态为 `VALID_NO_IMPROVEMENT`。GPU 专项小型证据验收无遗留
需要 GPU/Pod 才能关闭的高/中等级 correctness/functionality finding；唯一 Pod 已释放并确认 0 Pod、持续 compute 费率为 0，任务卷在
Plan 082 完成时为 40GB。`US-TX-3` 不在 provider 当前 S3 API 支持列表，故按用户一次性授权使用一个 Secure RTX 4090 transfer Pod 只读回传；冻结
bootstrap 的 39 对象已在本地完成逐对象 bytes/SHA-256、exact-tree 与权限校验。transfer Pod 随后删除并确认 0 Pod/compute 止费；
最终验收通过。Plan 087 后续将同一卷扩至 57GB 并保留候选；用户本人明确决定继续保留网络卷 `mwemzrn33y`，该卷当前仍未删除，状态为
`FINAL_REVIEW_ACCEPTED / VOLUME_RETAINED_BY_USER_DECISION`。

**目标与边界**：付费阶段在正式创建/启动前同时刷新 A40 48GB 与 L40S 48GB 的库存、价格和网络卷兼容性；使用一张 A40（首选）
或 L40S（备选）及任务网络卷，完成 commissioning、训练参数开发和一轮从 exact base/空 namespace 开始的干净正式轮。累计 GPU 计费
训练活动不超过 12 小时、对应外部费用不超过 15 USD；训练完成后的 GPU 审查等待、无 Pod 回传和删卷等待费用分开持续报告，任务总累计
费用首次达到 10 USD 时非阻断告警。正式 Pod 保留到 GPU 专项审查关闭所有合理可预见的 Pod 依赖后立即释放；无需 GPU 的代码/交接/文档
问题留到最终验收。大型资产不在 GPU 审查期回传，优先在 0 Pod 且不占用共享磁盘和宿主容量的安全窗口通过任务网络卷
S3-compatible API manifest 驱动续传并校验；本轮因 US-TX-3 不受支持，按用户一次性授权使用最小 transfer Pod。网络卷继续保留，
删除须用户本人另行明确人工批准。正式终态为
`TRAINING_IMPROVEMENT_FOUND`、`VALID_NO_IMPROVEMENT`
或诚实的 `INCONCLUSIVE`；前两个都完成研究目标，均不直接授予产品资格或解锁 M3-D。

#### Plan 087：exact 1.7B 云端自适应原参数路线搜索（已完成）

**任务合同**：[`Plan 087 ExecPlan`](../../plan/087-publication-critic-cloud-adaptive-original-parameter-search-execplan.md)。

**结果**：阶段 A 通过审查后，阶段 B 在单张 L40S 上从 exact base 完成 A–O 15 条路线。Route O 的末块内部输入变换/归一化九张量
以一次 full-cohort 原参数更新取得 raw boundary margin `+0.00390625`、projected boundary `+0.00086113`、projected within-PASS
`+0.00013894` 与 ROC AUC `+0.00140056`，关键 operating 指标未退化；精确 checkpoint 已由不同 OS 进程 no-update 恢复。
任务终态为 `PROMISING_CANDIDATE_RETAINED / FINAL_REVIEW_ACCEPTED / ZERO_POD`，保守费用 `$3.009`，低于冻结的
`$8.9852646939` 上限。全部 Pod 已删除并确认 compute `$0/h`；57GB 卷 `mwemzrn33y` 保留，完整 checkpoint/权重仍只在卷上。

**边界与交接**：Route O 是任务合同内的有潜力研究候选，不是效果可靠结论。15 条路线共用同一 validation 自适应选择，且只有一次更新、
没有 clean reproduction；AUC 增量只对应一个跨类 ordering，raw within-PASS 仍轻微回退，strict/threshold 指标不变。后续须另行立项、
重新授权并预先冻结 Route O recipe 后从 exact base 干净复现；Plan 087 剩余预算与外部动作授权不转移，不解锁 M3-C1/M3-C2、unseen、
产品启用或 M3-D。详细跨路线原因见
[`2026-08-26 Publication Critic 模型路线结果与根因分析`](../research/2026-08-26-publication-critic-training-route-outcome-analysis.md)。

#### Plan 090：Route O 干净复现与执行/数值重复确认（已完成）

**任务合同**：[`Plan 090 ExecPlan`](../../plan/090-publication-critic-route-o-clean-reproduction-execplan.md)。

**结果**：保持 exact 1.7B、冻结 v8/pair/input、Route O 九张量与原 BF16 recipe，从 exact base 和独立 namespace 执行
`20260901`、`20260902` 两次 clean BF16。两次均通过预冻结整体 rubric，validation delta 同为 raw Boundary `+0.00390625`、
projected Boundary `+0.00086113`、raw Within-PASS `-0.00334821`、projected Within-PASS `+0.00013894`、ROC AUC
`+0.00140056`，operating/strict 指标不退化；第二候选由不同 OS 进程完成 no-update 恢复。不同 seed 只作元数据，
`seed_sensitive_stability_tested=false`。随后完成真实整模型 FP32 参数训练条件对照，其 raw Boundary `-0.00659415`、projected
Boundary `+0.00620638`，未通过同一 rubric；该单条完整精度路径对照只支持精度敏感性诊断，不自动推翻两次 BF16 clean repeat。

**资源与终态**：正式序列绑定同一 exact US-TX-3 L40S Pod 与既有 57GB `mwemzrn33y`，保守费用 `$0.71`，低于 `$6` 硬上限。
任务 Pod 已停止并删除，live 复核 0 Pod、compute `$0/h`；卷未扩容或删除，只保留恢复合格的第二 BF16 checkpoint。Plan 082/087 roots
保持只读，完整结果摘要见 [`plan090-route-o-confirmation-v1.md`](../../eval/results/publication-critic/plan090-route-o-confirmation-v1.md)。

**当前边界**：终态为 `ROUTE_O_CONFIRMATION_PASS / ZERO_POD / FINAL_REVIEW_ACCEPTED`；只确认同一冻结 validation 上的执行/数值重复性，
不授予随机 seed 稳定、独立 cohort 泛化、unseen、M3-C1/M3-C2、产品启用或 M3-D 资格。Plan 090 预算与外部动作授权已关闭；当前没有
可继承授权。

#### Plan 094：Route O 连续训练与实质增益候选形成（有效负向终态；zero-Pod 收口及最终验收完成）

**任务合同**：[`Plan 094 ExecPlan`](../../plan/094-publication-critic-route-o-continuous-training-execplan.md)。

**目标与边界**：保持 exact 1.7B、冻结 v8 train/validation、pair/input/objective 家族、unseen 物理隔离和 Route O 九张量原参数范围，
复用 Plan 081/082 的连续训练/checkpoint/恢复/保留能力与 Plan 087/090 的 Route O 资产。正式轨迹要求完整 checkpoint 原子落盘和资格化后
才进入测评，并以同轮 exact base、previous/best/latest、train/validation 聚合指标及逐 pair margin 持续判断；候选必须明显越过 Plan 090
已知微弱包络，在 ranking、strict 或 operating 指标上出现有意义变化，且另一 pair family 不明显退化。material rubric、停止和保留规则在
看到正式结果前冻结；训练强度、观察/checkpoint 密度和调度不在 WBS 锁死。

**终态与授权**：实际终态为 `ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT / ZERO_POD / VOLUME_RETAINED / FINAL_REVIEW_ACCEPTED`，完成研究目标。
阶段 B 外部动作授权已随全部任务 Pod释放而关闭，剩余预算不转移；网络卷继续保留。后续训练、扩容/新建/删除云资源、独立 cohort、unseen、
发布或产品动作均须另立任务并重新授权，本任务不授予产品资格或 M3-D 解锁。

#### Plan 095：云端参考 Scorer 后端接入（最终验收通过，已集成本地 main）

**任务合同**：[`Plan 095 ExecPlan`](../../plan/095-publication-critic-cloud-reference-scorer-backend-execplan.md)。

**目标与边界**：复用 Plan 055/057/068 已有 `PublicationScorer → service → typed client → team_publish` 边界，只增加显式选择的云端
scorer backend。云端输出继续是声明 domain 内单个有限标量，由既有 scoring identity/threshold 合同形成 `PASS/REWRITE`；provider
无法验证 tokenizer 或 serving revision 时必须显式标为不可验证，不得伪装成本地 exact identity。产品保持 default-off，未选择 cloud
backend 时没有 secret 读取或网络出口。

**当前实现事实**：唯一的云端选择路径是新增的 `codex-publication-critic-cloud-service` 启动器；不启动它就不读取 secret、不解析
provider endpoint、不产生任何出网请求。云端身份由 `cloud_reference_scoring_identity` / `provider_managed_model_identity` 构造并在
descriptor 校验中强制：声明的 model 名必须等于 provider 实际请求的 model（否则可请求模型 A 而把结果标成模型 B），model revision 恒为
`serving-revision-unverifiable`，tokenizer 恒为 `provider-managed-tokenizer@unverifiable`，input_template 为独立的
`rondo-publication-cloud-template@v1`，scalar_projection 为 `rondo-cloud-json-quality-scalar@v1`，scoring definition 必须带
`rondo-cloud-reference-` 前缀，domain 恒为 `[0,1]`；threshold 是显式非最终的参考 operating point。每次调用的最坏 attempt×timeout 加上
全部递增 backoff（`backoff × (n−1)n/2`）必须装进 service 的 job deadline，因此立即开始执行的调用通常先收敛为 typed backend failure；
service 的 job deadline 始终是外层兜底，排队或外层取消时可以先发生。

**当前状态**：`COMPLETED / FINAL_REVIEW_ACCEPTED / GOAL_COMPLETED / INTEGRATED_LOCAL / NOT_PUSHED`。离线以确定性 loopback provider 通过真实启动器与真实 typed client 覆盖 readiness、
`PASS`/`REWRITE`、malformed 与 out-of-domain、两种模式下的 served-model drift、429 重试与 401 不重试、慢 provider、在途 HTTP 取消
（含丢弃 retry future）、在途请求下的 active shutdown/force-cancel、并发 1/队列 1 的 queue-full、fail-closed 启动，以及非 cloud
backend 零 provider 请求；`codex-publication-critic` 全绿 `57/57`。真实证据以合成 packet 在 DeepSeek chat-completions 上取得：
clean smoke 两个正反 packet 分别得到 `PASS` 与 `REWRITE`，另有 HTTP 400 负向对照证明请求确实到达选定 provider，readiness 不发付费
探针；因 model revision 字面量变更，已用最终代码与最终 descriptor 重跑该轮。首轮 finding 与返修证据见
`agent_log/2026-08-27-071711-plan095-review.md` 与 `agent_log/2026-08-27-075500-plan095-review-remediation.md`。Sol 审查者独立重跑
`codex-publication-critic` `57/57` 与 core 定向 `17/17` 并最终验收通过；用户确认远端 backup ref 是其本人备份并明确授权删除，删除后
095 分支按授权以 merge commit `06cfcfc` 合入本地 main，`origin/main` 尚未推送。复验与集成分别见
`agent_log/2026-08-27-110223-plan095-sol-re-review.md`、`agent_log/2026-08-27-111225-plan095-main-integration.md`。

**授权与边界**：真实 API、可选 Docker/smoke 合计 50 USD 硬上限；按实际可能计费的 provider HTTP request 计数共 11 次，保守计
11 USD。未使用 Docker。任务不做批量测评、最终 threshold、v8/unseen、GPU、真实本地模型或项目数据上传，C: 余量停止线仅在本任务
命令上下文临时为 30GB，不改默认值。该 backend 是 eval/reference-only，不改变产品默认 backend，也不解锁 M3-D。

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

**当前状态**：Plan 094 commissioning 已证明真实 Route O update、checkpoint-first overlay 与 fresh-process 恢复继续。guarded Plan 090
import 因历史 cursor 不兼容按合同拒绝，clean formal 使用预冻结 exact-base fallback；step 1--4 均无 material/strict/operating event，
step 4 形成 `ROUTE_O_VALID_NO_MATERIAL_IMPROVEMENT`。卷上 steps 1/3/4 checkpoint 已深读资格化，小型无权重结果已回传；既有卷只按需
从 57GB 扩到 70GB。预释放审查通过后，唯一 Pod 已精确 stop/delete，并独立确认账户 0 Pod、compute `$0/h`；本地 zero-Pod finalizer
保持同一有效负向终态，并已通过整体最终验收。卷以 `$0.007/h` 继续保留。正式结果不读取 unseen，也不改变产品或 M3-D 边界。

## 串并行与资源关系

- M3-A1、M3-A2 与 M3-B1a 已完成共同前置。Plan 060 / M3-B1b 与已完成的 Plan 064 构成 M3-B1c 的并列资格门；产品链的
  M3-B2a、M3-B2b 均已完成，两链在 M3-C1 前汇合。
- M3-B1b 是独立付费资格门；Plan 060 `TECHNICAL_GO`、Plan 064 `DATA_GO` 与正式训练授权均已成立，Plan 066 已据此完成训练执行、
  资源终态、final-02 receipt 与独立验收；Plan 068 已完成本地交接、资格运行和远端止费，没有追加训练消费。
- M3-B1c 与 M3-B2b 前置、Plan 068 / M3-C1、Plan 071 base 同口径重验及 Plan 073 / M3-C2 均已完成；Plan 073
  终态为 `NO-GO`，没有最终锁定组合，M3-D 保持锁定。
- Plan 079 已通过独立验收，只使用 Publication Critic Python 设施与单张云 GPU 完成，没有占用本地重型资源槽；Pod 已止费，
  完成时保留的网络卷按用户提供的最新查询已返回 404、当前不再作为可用或持续计费资源。
- Plan 081 已在独立 worktree 内完成 Publication Critic Python/训练合同与三期 WBS，不运行 Cargo、Docker、真实模型/GPU或云计算，
  不写/清理共享 Cargo target，也不以 Plan 079 卷为前置。Plan 082 已完成真实正式轮、GPU 专项验收和大型资产交接，训练 Pod 与一次性
  transfer Pod 均已释放并确认 compute 止费；最终验收已通过，用户本人决定继续保留网络卷 `mwemzrn33y`，该卷当前仍未删除。
- Plan 087/090 均已结束并释放全部 Pod，当前不占本地 Cargo build lock、Docker、真实本地模型或云 compute。用户决定保留的
  `mwemzrn33y` 网络卷已由 Plan 094 按需扩到 70GB 并继续计费，未经授权不得删除；Plan 082/087/090 既有根保持只读。
  真实本地模型、Docker 与重型 Cargo 仍按根 `AGENTS.md` 全局串行。
- Plan 095 未使用 GPU、RunPod、真实本地模型、Docker 或既有训练卷，只用付费 API 与本地 Cargo；Cargo 全部从 095 worktree 经正式入口
  复用主物理根 `.codex/cargo-target/rondo-multi`，未在 worktree 另建 target。
- 三期与已经正式收口的方向 1 没有产品依赖。如果未来重新启动方向 1，普通工作仍可并行安排，但共享 API 预算、
  本地 GPU、Docker、构建锁和磁盘时必须显式错峰。
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
- 重型 Cargo、Docker 和真实本地模型继续按项目全局资源门禁串行。Multi 的受支持 Unix 重型入口共享物理仓库根
  `.codex/cargo-target/rondo-multi`；日常 Cargo 使用 `jobs=2`、GNU/Linux LLD 单线程和 2 个机器级 rustc 槽，要求尽量一次跑完的
  完整 workspace 使用受跟踪的 `test-with-codex-v8-conservative`（`jobs=1`、LLD 单线程）。付费 API 服从对应任务的范围、预算和授权，
  在不争用本地重型资源时可以与普通非重型工作并行。
- 不引入合规/取证平台、PKI/签名链、trust score、在线学习路由器、judge 集群、全量 transcript/CoT 广播、
  自由群聊、固定大 swarm 或通用副作用缓存。

## 外部授权与实施边界

- M3-A1 产品合同与 Plan 054 / M3-A2 已完成；M3-B2a 已按 Plan 055 完成实现、独立验收与主线整合；M3-B2b 已按 Plan 057 完成实现、
  审查整改、最终独立验收与主线整合。其余后续工作包启动时仍须按 `plan/plan-example.md` 建立任务合同并取得授权。
- RunPod 创建或计费、模型与数据上传、云端训练、权重下载、真实本地模型加载/推理、Docker 和付费 API 均须在对应任务
  开始前取得明确授权。23 USD 只是 Plan 060/066 已完成训练链的历史连续总账上限；Plan 082 的实际训练活动使用独立的 12 小时/
  15 USD 上限，且该付费授权只有在阶段 A 经最终审查者验收、用户本人再明确人工批准后才生效。训练完成后的强制审查等待、0 Pod
  S3 回传和删卷等待费用另行持续报告；任务总累计费用首次达到 10 USD 时非阻断告警。Plan 082 正式 Pod 只能在 GPU 专项审查确认无需
  再用后释放，任务网络卷删除还须用户本人另行明确人工批准。
- Plan 087/090 外部动作授权均已随各自 `ZERO_POD` 终态关闭，剩余预算不转移。Plan 090 保守费用 `$0.71`，低于 `$6` 硬上限；
  换区/换卡、继续训练、独立 cohort、卷扩容/新建/删除、unseen 或产品动作仍须新的明确任务与授权。
- Plan 094 已形成有效负向研究终态并完成 0 Pod / compute `$0/h` 收口；用户后续允许卷按需扩到 120GB，实际只扩到 70GB并继续保留，
  收口预算另保留至少 6 小时卷费用，整体最终验收已通过。阶段 B 外部动作授权已经关闭；不得沿用本任务重建 Pod、继续训练、新建第二卷、
  删除现有卷、充值、读取 unseen、发布或执行产品动作。
- Plan 095 的一次性真实 API 使用低于 50 USD 上限：按实际可能计费的 provider HTTP request 计数共 11 次（首轮 8 次，返修后以最终代码
  重跑 clean smoke 与负向对照 3 次），金额未知按 1 USD/次保守计为 11 USD。未使用 Docker、GPU、RunPod、真实本地模型、v8/unseen，
  也未上传项目数据。Windows `C:` 停止线只在本任务运行时临时为 30GB，受跟踪默认阈值未改。后续继续用真实 API 做批量测评、
  threshold 标定或产品启用，必须另立任务并重新授权。
- Plan 068、Plan 071 与 Plan 073 的一次性授权已随本地交接、真实推理、资格/联合横评、独立验收和 exact winner 卷删除全部完成，
  不向后续任务延伸。M3-D、新候选或继续训练、云资源、远端上传、真实 API 与产品启用均须另建任务并取得相应授权。
- 训练数据、权重、逐样本输出与私有运行材料留在 `eval-data/` 或仓库外；`training/` 只保存体积合规的轻量合同与数据。
- 正确性测试随产品能力建设；测评只保留能指导模型选择和产品验收的轻量指标，不建设数据资产审计或可信证明平台。
