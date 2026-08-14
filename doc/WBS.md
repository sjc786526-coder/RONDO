# RONDO 长程规划（WBS）

最后更新：2026-08-14

本文件与 `doc/WBS/*.md` 是项目**当前状态与后续规划的唯一来源**。本文件只保留阶段级状态、下一工作包、
跨方向顺序、依赖和授权门；方向内部的任务分解见子 WBS。已完成成果与详细证据见
`doc/WBS-COMPLETED.md`，单次任务合同见 `plan/`，研究与审计只作为形成时点的证据。

## 1. 当前阶段

上游基线冻结为 Codex CLI `v0.147.0`（`rust-v0.147.0`，commit
`be6e8eac029b183056b7e4402879f15d2c85f61b`）；机器事实源为
`mydev/codex-rs/core/upstream-source-baseline.toml`。

项目由两条并列产品线组成：**RONDO Local**（`mydev/`，承载方向 1、2）与
**RONDO Multi**（`multidev/`，产品基线已完成并合入 `main`，承载方向 3）。两者地位相同，结构见 §4。

| 范围 | 当前结论 |
|---|---|
| P0 共享地基 | S1 审批模型覆盖与 S2 `E_final` 证据捕获已完成，开关默认关闭。S1 只覆盖模型与 effort，不覆盖 provider。 |
| 测试基线 | Plan 004 完成对旧 81 项失败的分批整改后，最近一次有记录的 `v0.147.0` RONDO 全 workspace 实际执行 14,092 项：14,060 通过、31 失败、1 超时，Nextest 另列 23 项 ignored；P0 仍以定向验收收口。此后未重跑全 workspace，不能把该历史快照表述为当前全绿或当前失败复现。 |
| P1 / M1 | B1、B2、B3 与 M1 已完成；冻结 Codex 与 RONDO 已在同一 TB 2.1 任务上完成真实端到端并归档。 |
| P2 / 方向 0 | B4—B7 执行设施和 v22 真实执行已完成。E-B8 公平比较设施已闭合（campaign schema v7），已通过 pure/fake/loopback 与无 API synthetic Docker 全 catalog 验收；尚无正式 v7 identity，也未跑新 campaign。E-A（A1—A7）随方向 1 一并挂起，不再作为交付项。 |
| v22 结论 | 机械一致性子门得到 `sigma=0`、`delta=3`，以 `ab_delta_exceeds_aa_sigma` failed；但 A/B 存在 catalog prompt 161-token 非对称、harness/deadline 混杂和非交错执行，因此**不能据此归因 RONDO 与 Codex 的能力或性能差异**。报告分歧已全部关闭。 |
| 结果数据 | P2 v2—v22 公共账本已合入：`eval/results/runs.jsonl` 共 244 条唯一 run，v22 为 32 条；v6—v22 的 11 份聚合 JSON 同步入库。原 results 分支已收口为 `zz-done/0811-p2-b7-results`。 |
| 方向 1 | 教师 harness 研究 T1—T3 已完成，候选及证据见研究报告；**方向整体挂起、不排期**，重启时只针对 RONDO Local。 |
| 方向 2 | L1、L2a、CPU/CUDA model-free runtime 与唯一 GGUF 静态完整性已完成。真实 ignored 配置已迁移到 4k 合同，qualification 设施与 model-backed 证据投影已落地，真实模型已首次成功加载并通过 CUDA/身份/上下文核验。**一条冻结的真实 `E_final` 实测 5,313 input tokens，在 4096 合同下被服务拒绝**，未产生结构化判定，能力保持 `linux_cuda_built_model_unvalidated`；4k 对全部 47 条真实归档的可行性尚未做 exact-token 验证。真实结构化推理、L3/L4 与 Local M3 均未完成，上下文预算需先定案（见 `doc/WBS/local-approval-model.md`）。 |
| 方向 3 | 多智能体可信证据研究已完成。方向改为**独立产品源码 RONDO Multi**，不再是 Local 内的可插拔模式；`multidev/` 产品基线已完成并合入 `main`；首个可交付增量待定（D1，见 §8）。 |

当前不再维护 v6—v22 的逐轮过程、请求数和费用流水；这些历史只保留在
`doc/WBS-COMPLETED.md`、对应 plan、agent log 与冻结结果中。

## 2. 下一工作包与顺序

工作包 1、工作包 2（Plan 022）均已完成。**工作包 3 是当前工作包**，三条线按下述范围并行。

### 工作包 3（当前）：三条线并行

- **3a 测评设施**：按需要继续维护，但不恢复已挂起的 E-A。
- **3b RONDO Local**：已实测的那条真实 `E_final` 为 5,313 input tokens，4k 合同装不下，
  因此下一步先定案本地审批的上下文预算与真实证据的可服务口径（必要时先做 exact-token 普查），
  再以 model-backed + 配置切换收口 Local M3，然后由 L5a 生成冻结教师标签、L3/L4 出未微调 baseline
  与指标口径，之后 L5b/L6，最后 Local M4。
- **3c RONDO Multi**：`multidev/` 产品基线已完成；D1 未定前只有环境就绪工作，没有功能内容。
  付费同题退化验收所需的公平比较设施前置已经具备；实际运行时仍须按 §6 单独冻结范围、轮数与预算并取得
  真实 API 授权，不得用未运行或无效比较表述“未见退化”。
  Multi 尚无冻结 runtime bundle，`eval-data/bin/rondo-multi/` 仍为空；首次真实或 Docker 验收前必须先按
  §4.5 的产品身份冻结一套 Multi bundle。

三条线的代码与文档工作真正并行；重型 Cargo、Docker、真实本地模型加载与付费 API 仍按资源门禁全局串行。

### 关键阶段的真实 API 检查

在关键阶段用小规模、预算固定、尽量交错的真实 API 测评检查“不明显退化”，每次单独申请（§6）。

### 挂起项（不排期）

- **方向 1（harness 性能优化）完全挂起**，排在所有工作之后，本轮不做候选筛选。
- **E-A 轻量离线冻结回放（A1—A7）随方向 1 一并挂起。** 它原本是为低成本反复做性能优化而建；不做优化就不需要它。
  日常回归改由**测试体系**（单测、fake/loopback/replay 测试）保证正确性，不再借测评设施兜底。

## 3. 方向与依赖

| 编号 | 方向 | 产品线 | 状态 | 解锁条件 |
|---|---|---|---|---|
| 0 | 量化测评基准 | 共享 | 公平比较设施已闭合，待新 campaign 授权 | 无外部阻塞；E-A 挂起 |
| 1 | Harness 优化 | Local | **挂起，不排期** | 由用户决定重启；重启时只针对 RONDO Local |
| 2 | 本地审批模型接入与横评 | Local | 真实模型已首次加载；已测那条真实证据超出 4k | 无外部阻塞；上下文预算定案 → model-backed + L7 → Local M3 → L5a → L3/L4 → L5b/L6 → Local M4 |
| 3 | 共享可信证据链的多智能体协作 | Multi | 研究与产品基线完成；首个功能增量待定 | 由 D1 决定首个增量；真实 API/付费测评单独授权 |

- **Local 与 Multi 地位相同**。Local 可能更早收口，只因剩余路径较短（4k model-backed → LoRA → 横评已成链），
  而 Multi 的首个增量还待定（D1），不代表优先级更高。重型任务全局串行是资源约束，不构成战略阻塞。
- 方向 0 与方向 2 共用 P0。方向 3 不再排在方向 1 之后；方向 1 的挂起也不阻塞任何其他方向。
- 方向 2 的真实 `E_final` 必须按稳定语义哈希切成互斥 `seed` / `holdout`，真实证据本身不得进入训练集。

## 4. 仓库与产品线结构

### 4.1 布局

单仓库、单长期 `main`、两套并列源码：

```text
RONDO/
├── mydev/        # RONDO Local（沿用现名，不改名）
├── multidev/     # RONDO Multi（工作包 2 产品基线已完成）
├── eval/         # 两条产品线共享的通用测评设施
├── scripts/      # 共享构建锁与看门狗入口（已由 mydev/scripts/ 迁出，见 §4.4）
├── eval-data/    # 内部按产品分命名空间，不顶层并列
├── test-data/    # 内部按产品分子目录
├── doc/
└── plan/
```

### 4.2 分支与任务隔离

- 不为 Multi 建立需要长期同步的永久产品分支；Local、Multi、公共文档和共享设施统一进入 `main`。
- 目录并列负责产品源码隔离；每个具体开发任务仍使用短期 worktree/任务分支。
- Local 任务只修改 `mydev/` 及必要共享文件；Multi 任务只修改 `multidev/` 及必要共享文件。
- `eval/`、WBS 和其他共享权威文件尽量（不强制）同一时段只由一个任务负责。
- 公共安全修复、provider/API 适配和构建修复按需选择性同步，**不追求两套核心长期提交级一致**。

### 4.3 磁盘预算：显式设计约束

- 项目容量看门狗量的是整个项目根 `du -sx`，阈值 180/195/200 GB；两套 workspace 的 target 自动计入同一预算，
  这是设计意图，门禁不改。
- 实测参考：一次全 workspace 冷构建 + 全量测试的 target 峰值约 126 GB；`eval-data/` 当前约 21 GB。
- 运行规则：**同一时刻只允许一个产品的 target 目录处于热状态**；切换产品线做重型任务前先清理另一侧。
- `.cargo/config.toml` 在仓库根，cargo 逐级向上合并，`multidev/` 自动继承 `jobs=6` 与 rustc-throttle。

### 4.4 共享外围设施

两条产品线不要求共用核心代码，但应尽量共享：构建锁与资源看门狗、Docker 与 Terminal Bench 任务执行、
API 预算与结算、BinaryManifest 与结果归档、本地模型 launcher/doctor/runtime、fake/loopback/replay 无 API 测试，
以及能接收不同二进制与产品 variant 的通用测试与测评入口。

**看门狗**：`with-build-lock.sh` 与 `build-watchdog-lib.sh` 位于仓库根 `scripts/`，逻辑、阈值与退出语义
与迁移前一致，两条产品线共用，**没有 shim 或兼容软链**。现行引用点全部使用根路径；
`eval/locks/*.json`、`agent_log/` 与 `doc/audit-snapshots/` 里的旧路径是冻结 provenance，不改写。

### 4.5 产品身份

- **产品身份与比较侧是正交的两个维度**：`product`（`rondo-local` / `rondo-multi`）说的是哪个 RONDO 产品，
  `side`（`rondo` / `codex`）说的是 RONDO 侧还是冻结上游侧。`codex` 不是产品取值。
- **历史结果只加不改**：既有 244 条 run 中 224 条 `side=rondo` 解释为 RONDO Local，20 条 `side=codex`
  是上游侧、不适用产品身份；一律不改名、不回填。
- Multi 必须显式带 `multi` 字样（`eval-data/bin/rondo-multi/`），产品身份贯通 binary freeze、
  源码/构建路径、manifest 与结果归档，不能只参数化一个 `bin/rondo/` 路径。
  唯一映射是 `eval/rondo_eval/contracts.py` 的 `product_layout()`；任一层缺失或矛盾都 fail-closed。
- **Multi 的产品基线是行为定义的**：`[auto_review]` 的 `model`、`model_provider`、`reasoning_effort`、
  `evidence_dir` 四项默认未配置，eval 也不为 Multi 注入它们，结果工件用版本化 `auto_review_config`
  记录该状态。Local 的既有公平运行合同不变。
- crate 名与二进制名沿用上游（`codex-cli` / `codex`），**不重命名**，保持与 `codex-source-code/` 可直接 diff。
- 数据目录不顶层并列，只在产品特定层级加命名空间；具体规则见 `doc/eval-data-layout.md`。

## 5. 阶段与里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | S1 审批模型显式覆盖、S2 审批证据快照 | 已完成 |
| P1 | B1—B3 最小真实链路；L1/L2 model-free 前置 | 已完成，M1 通过 |
| P2 | 公平比较设施闭合（已完成）；B4—B7；L2a/L7 + 4k model-backed 收口为 Local M3；随后 L5a 教师标签与 L3/L4 未微调 baseline | 进行中 |
| P3 | L5b 合成训练数据、L6 微调，收口为 Local M4 | 未开始 |
| P4 | harness 优化迭代 | **挂起，不排期** |
| P5 | RONDO Multi 产品线 | 产品基线已完成（工作包 2）；功能开发待 D1 |

| 里程碑 | 验收口径 | 性质 | 状态 |
|---|---|---|---|
| M0 | Guardian 模型/effort 显式生效并落盘规范化 `E_final` | 工程验收 | 已完成 |
| M1 | 冻结 Codex 与 RONDO 同一 TB 2.1 任务端到端可归档 | 工程验收 | 已完成 |
| Local M3 | 4k model-backed、结构化输出、真实 `E_final`、fail-closed 与配置切换形成真实本地审批闭环 | 工程验收 | 未完成 |
| Local M4 | 同一批冻结样本上正式比较 Sol / 未微调 Local / 微调后 Local，由人作采用/保留/停止决定 | 人判定 | 未完成 |
| Multi 里程碑 | 由 Multi 自行定义，**不继承 `σ`/`delta` 总闸门** | 待定 | 待 D1 定下首个增量后确定 |

**M2 与 M5 已退役**，历史文档中的这两个名字不再对应当前任何门禁：M2 的“测评设施就绪”部分成为工作包 1
（设施交付物，非里程碑），“方向 1 解锁”部分随方向 1 挂起；M5 同样随方向 1 挂起。
工作包 1 已闭合，Multi 的付费退化验收不再有跨工作包前置，只保留具体运行时的合同冻结与真实 API 授权门。

### 公平比较设施保留的机械判据

公平比较设施在自身范围内保留三个**分别报告**的机械子门，不引入统计显著性框架，也不使用
pairwise-max `σ` 等事后放宽办法：

1. **A/A 行为一致性**：用同一二进制的预冻结重复观测形成不一致预算 `σ`；`σ` 是经验观测，不是统计估计。
2. **A/B 对称比较**：两侧在完全相同的 task-independent 合同下运行，跨侧差异 `delta ≤ σ`；
   `delta` 使用条件加跑聚合后的每题 outcome，不是基础轮的原始差异。
3. **重复与方向性兜底**：对一侧 pass、另一侧 fail 的任务（**两个方向都算**）使用预冻结重复并计入聚合；
   其中若 RONDO 全败而上游全过，则另由方向性子门判为不通过。
4. **infra**：基础设施失败不计能力分，只按同题运行链定点补跑；每轮后最终 infra 超过 2 项即 blocked；
   共同有效集合至少 8 项。
5. **预算**：基础运行、预冻结重复、infra attempts 与 wire canary 全部计入 campaign cap，并单独授权。

这套判据**只适用于该设施自身的等条件 A/A、A/B 比较**。Local M3、Local M4 与 Multi 退化验收都
**不继承** `σ`/`delta`（理由分别见 `doc/WBS/local-approval-model.md` 与
`doc/WBS/multi-agent-trusted-evidence.md`）。

v22 使用“两轮 RONDO A/A + 两侧各一轮 A/B + 条件两侧各加跑两轮”的历史公式；它的机械结果保持不改写，
但不作为新 campaign 的默认重复合同。新 campaign（schema v7）必须在 lock 中预冻结重复数与聚合公式：
每题每侧总观测数为奇数且不少于 3（基础 A/B 轮算其中一次），聚合固定为严格多数。
若 catalog、请求冻结分区、harness、deadline、顺序、重复或聚合规则不对称，设施直接 blocked、不计算能力归因；
若 `σ` 接近任务总数，应回到 B4 重选 canary，而不是放宽判据。

## 6. 授权门

以下动作每次执行前都需单独授权，历史授权不自动延续：

- Docker 拉取、构建或运行。
- 按量付费真实 API 批量测评：须冻结任务范围、轮数、模型和预算上限。
- 真实本地模型加载或推理。
- 任何真实数据外发，包括把本项目自造的合成训练数据上传到云端。
- 云 GPU 训练、上传或下载权重、产生外部费用或状态变更。
- 上游基线升级。

**订阅制入口不计入 API 预算门**：Sol 经开发用 Codex 生成教师标签、Opus 5 经 Claude Code 担任横评裁判，
二者不额外计费，因此不受 API 预算授权门约束，只受订阅速率与配额限制。相应地它们带两条限制：
模型版本不由本项目冻结，必须记录**生成/判定时点的模型标识与日期**；且只用于人在场、发送预写冻结 prompt 的
会话内工作，**不得**作为程序化批量后端接进 `eval/` —— `eval/` 只导入其冻结产物。
也不为这些角色另开按量付费 API 入口。数据外发门与订阅与否无关，仍然适用。

## 7. 测试与测评原则

- 测试验证代码与设施正确性，复用上游 Rust/Nextest 等体系，只补受影响模块的必要回归。
  **E-A 挂起后，日常回归完全由测试体系承担**（单测、fake/loopback/replay），不借测评设施兜底。
- 测评提供性能指标，默认关闭、轻量、自动记录归档；离线、fake、真实 API、真实模型和 Docker 证据严格区分。
- 现有测评设施保留。修复公平性、任务与 prompt 对称性、二进制/结果身份和运行时混杂后，
  主要用于关键阶段不退化检查、产品变体对比和最终验收，不再承担高频回归。
- 冻结 Codex 与 RONDO 的公平横比只使用同口径外部指标；内部探针只用于自身版本间诊断。
- skip、未运行和无效比较不能表述为通过；测评设施合同不满足时不得解释产品能力。
- 结果与数据资产边界遵循 `doc/eval-data-layout.md`。

## 8. 待定决策

- **D1 Multi 首个可交付增量** —— 待细读 `doc/research/multi-agent-trusted-evidence-research.md` 后决定选哪个
  工作流、是否先做证据层地基。**这是当前最大的未定项**：产品基线已完成，且在 D1 定下来之前
  工作包 3c 没有实质内容。
- **D2 Multi 价值命题的最终措辞** —— 现有版本（见 `doc/WBS/multi-agent-trusted-evidence.md`）是初步框架，
  需在读完调研报告后确认或修正，特别是“朴素自然语言基线作对照组”是否采纳为设计约束。

两项都不阻塞 3a/3b；它们只使 3c 暂时停在环境就绪。

## 9. 子规划索引

- `doc/WBS/eval-benchmark.md` —— 方向 0：量化测评基准
- `doc/WBS/local-approval-model.md` —— 方向 2：RONDO Local 本地审批模型接入与横评
- `doc/WBS/teacher-harness-study.md` —— 方向 1：教师研究成果到优化实验（挂起）
- `doc/WBS/multi-agent-trusted-evidence.md` —— 方向 3：RONDO Multi 产品线
