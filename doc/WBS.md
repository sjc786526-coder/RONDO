# RONDO 长程规划（WBS）

最后更新：2026-08-13

本文件与 `doc/WBS/*.md` 是项目**当前状态与后续规划的唯一来源**。本文件只保留阶段级状态、下一工作包、
跨方向顺序、依赖和授权门；方向内部的任务分解见子 WBS。已完成成果与详细证据见
`doc/WBS-COMPLETED.md`，单次任务合同见 `plan/`，研究与审计只作为形成时点的证据。

## 1. 当前阶段

上游基线冻结为 Codex CLI `v0.147.0`（`rust-v0.147.0`，commit
`be6e8eac029b183056b7e4402879f15d2c85f61b`）；机器事实源为
`mydev/codex-rs/core/upstream-source-baseline.toml`。

项目由两条并列产品线组成：**RONDO Local**（`mydev/`，已存在，承载方向 1、2）与
**RONDO Multi**（`multidev/`，尚未建立，承载方向 3）。两者地位相同，结构见 §4。

| 范围 | 当前结论 |
|---|---|
| P0 共享地基 | S1 审批模型覆盖与 S2 `E_final` 证据捕获已完成，开关默认关闭。S1 只覆盖模型与 effort，不覆盖 provider。 |
| 测试基线 | Plan 004 完成对旧 81 项失败的分批整改后，最近一次有记录的 `v0.147.0` RONDO 全 workspace 实际执行 14,092 项：14,060 通过、31 失败、1 超时，Nextest 另列 23 项 ignored；P0 仍以定向验收收口。此后未重跑全 workspace，不能把该历史快照表述为当前全绿或当前失败复现。 |
| P1 / M1 | B1、B2、B3 与 M1 已完成；冻结 Codex 与 RONDO 已在同一 TB 2.1 任务上完成真实端到端并归档。 |
| P2 / 方向 0 | B4—B7 执行设施和 v22 真实执行已完成。当前工作包是公平比较设施闭合；E-A（A1—A7）随方向 1 一并挂起，不再作为交付项。 |
| v22 结论 | 机械一致性子门得到 `sigma=0`、`delta=3`，以 `ab_delta_exceeds_aa_sigma` failed；但 A/B 存在 catalog prompt 161-token 非对称、harness/deadline 混杂和非交错执行，因此**不能据此归因 RONDO 与 Codex 的能力或性能差异**。报告分歧已全部关闭。 |
| 结果数据 | P2 v2—v22 公共账本已合入：`eval/results/runs.jsonl` 共 244 条唯一 run，v22 为 32 条；v6—v22 的 11 份聚合 JSON 同步入库。原 results 分支已收口为 `zz-done/0811-p2-b7-results`。 |
| 方向 1 | 教师 harness 研究 T1—T3 已完成，候选及证据见研究报告；**方向整体挂起、不排期**，重启时只针对 RONDO Local。 |
| 方向 2 | L1、L2a、CPU/CUDA model-free runtime 与唯一 GGUF 静态完整性已完成。当前 CUDA 能力为 `linux_cuda_built_model_unvalidated`；真实配置仍是旧合同，4k/8k model-backed、真实结构化推理、L3/L4 与 Local M3 均未完成。 |
| 方向 3 | 多智能体可信证据研究已完成。方向改为**独立产品源码 RONDO Multi**，不再是 Local 内的可插拔模式；`multidev/` 尚未建立，首个可交付增量待定（D1，见 §8）。 |

当前不再维护 v6—v22 的逐轮过程、请求数和费用流水；这些历史只保留在
`doc/WBS-COMPLETED.md`、对应 plan、agent log 与冻结结果中。

## 2. 下一工作包与顺序

推进顺序为 **工作包 1 → 2 → 3**。其中只有一条是**硬依赖**：3c 的付费同题验收不得早于工作包 1 闭合。
其余为建议顺序 —— 工作包 1 与 2 都会改共享 eval 合同，串行是为了避免两套 schema 同期漂移。

### 工作包 1（当前）：公平比较设施闭合（无真实 API）

依据 B7 归因报告已经关闭的证据，本 WBS 冻结以下设施修正合同：

1. 两侧使用同一份完整 8-model catalog bytes，并在工件中绑定 SHA 与来源字段。
2. 上游调用前比较剔除任务内容后的 task-independent tool specs、instructions、schema 等冻结分区；完整请求 digest
   各侧分别记录用于 provenance/drift，不要求轨迹分叉后的动态请求逐字节相等；增加无上游 stub preflight。
3. 固定相同 harness commit、deadline 与运行条件；正式顺序按任务交错，不再按整轮时间分块。
4. assessment 分开输出“方向性结果”和“A/A 行为一致性”；条件加跑进入最终聚合。
5. 重复数在 pilot 后、正式执行前冻结；波动任务使用奇数且不少于 3 次，不事后删样本。必须同时冻结
   多轮结果如何聚合为每题 outcome、`σ` 与 `delta`，在公式未机械化前不得建立新 campaign。
6. 实现保持**产品无关**，不再假设“只有一个 RONDO 产品”；为后续产品身份（`rondo-local` / `rondo-multi`）
   留下明确入口，但本工作包不创建 `multidev/`。

该工作包只修比较设施和离线验收，不产生付费调用。完成后再冻结新的 B7 campaign 合同；不得复用 v22 ID。
它是**设施交付物，不是里程碑**：旧 M2 已按 §5 拆解，公平比较设施不再充当解锁其他方向的总闸门。

### 工作包 2：RONDO Multi 产品基线建立（`multidev/` bootstrap）

范围严格限定为：共享看门狗脚本迁移（§4.4）、从当前 `mydev/` 复制 git 跟踪文件、通过三条行为验收门、
建立贯通 binary freeze / manifest / 归档的独立产品身份、能构建并通过本次变化相关的无 API 验证。
**不夹带任何 Multi 功能开发，也不运行付费 TB。** 任务分解与验收门见
`doc/WBS/multi-agent-trusted-evidence.md`。

这是正式产品基线而非空架子：共享设施适配、独立产品身份、构建与定向基线测试都算在内。
测试范围不重跑全 workspace —— `multidev/` 直接继承 `mydev/` 的源码与已有测试基线，本工作包只验证复制完整性、
路径与构建入口变化、看门狗迁移、Local 审批开关默认关闭以及 eval 产品身份接入；不把继承的历史测试快照表述为
当前全绿，也不把全 workspace 基线自动推迟到首个 Multi 功能阶段，后续是否跑全量由实际重大阶段另行决定。

### 工作包 3：三条线并行

- **3a 测评设施**：按需要继续维护，但不恢复已挂起的 E-A。
- **3b RONDO Local**：推进方向 2 的 4k model-backed 真实本地审批闭环（Local M3），再到 L5/L6 与 Local M4。
- **3c RONDO Multi**：推进方向 3 的功能路线。其**付费同题退化验收**以工作包 1 闭合为硬前置；
  在那之前 Multi 只做离线验证与功能正确性，不跑付费对比，也不得对外表述“未见退化”。

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
| 0 | 量化测评基准 | 共享 | 公平比较设施收口中 | 无外部阻塞；E-A 挂起 |
| 1 | Harness 优化 | Local | **挂起，不排期** | 由用户决定重启；重启时只针对 RONDO Local |
| 2 | 本地审批模型接入与横评 | Local | model-free/静态前置完成 | 无外部阻塞；4k model-backed → L3/L4 → Local M3 |
| 3 | 共享可信证据链的多智能体协作 | Multi | 研究完成，产品基线未建立 | 无外部阻塞；付费同题验收不早于工作包 1 闭合 |

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
├── multidev/     # RONDO Multi（工作包 2 建立）
├── eval/         # 两条产品线共享的通用测评设施
├── scripts/      # 共享构建锁与看门狗入口（由 mydev/scripts/ 迁出，见 §4.4）
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

**看门狗迁移（工作包 2 内必做）**：`with-build-lock.sh` 与 `build-watchdog-lib.sh` 目前在 `mydev/scripts/`，
Multi 一旦构建就形成“Multi 构建依赖 Local 目录里的脚本”这种依赖倒置。两者迁到仓库根 `scripts/`，
逻辑与阈值不动，**直接改所有引用点，不留 shim** —— `eval/` 侧存在 canonical wrapper 身份校验
（硬编码路径全等比较 + `/proc/<pid>/cmdline` 逐字匹配），`exec` 转发会替换进程映像使校验失败，
因此 shim 省不下工作量，且与 fail-closed 资源守卫的完整性方向相反。

迁移必须在**同一个任务内**同步改写 `CLAUDE.md` / `AGENTS.md` 安全边界条款与
`doc/development-environment.md` 中的路径 —— 在脚本真正移动前，这些文档仍按现状写 `mydev/scripts/`，
不得提前改成根路径。`eval/locks/*.json` 中作为冻结 provenance 记录的路径**不得修改**；
历史 `agent_log/` 与 `doc/audit-snapshots/` 同属冻结证据，不改。
顺序要点：先改 `mydev/justfile`，再复制生成 `multidev/`，使其天生带正确路径。

### 4.5 产品身份

- **历史结果只加不改**：`eval-data/bin/rondo/` 与既有 244 条 run 一律解释为 RONDO Local，不改名、不回填。
- Multi 必须显式带 `multi` 字样（`eval-data/bin/rondo-multi/`），产品身份作为独立维度贯通 binary freeze、
  源码/构建路径、manifest 与结果归档，不能只参数化一个 `bin/rondo/` 路径。比较侧的 `rondo` / `codex`
  与产品 variant 是不同概念，不被产品身份覆盖。
- crate 名与二进制名沿用上游（`codex-cli` / `codex`），**不重命名**，保持与 `codex-source-code/` 可直接 diff。
- 数据目录不顶层并列，只在产品特定层级加命名空间；具体规则见 `doc/eval-data-layout.md`。

## 5. 阶段与里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | S1 审批模型显式覆盖、S2 审批证据快照 | 已完成 |
| P1 | B1—B3 最小真实链路；L1/L2 model-free 前置 | 已完成，M1 通过 |
| P2 | 公平比较设施闭合；B4—B7；L2a/L3/L4/L7，收口为 Local M3 | 进行中 |
| P3 | L5 教师标签与合成数据、L6 微调，收口为 Local M4 | 未开始 |
| P4 | harness 优化迭代 | **挂起，不排期** |
| P5 | RONDO Multi 产品线 | 未开始（工作包 2 为其基线） |

| 里程碑 | 验收口径 | 性质 | 状态 |
|---|---|---|---|
| M0 | Guardian 模型/effort 显式生效并落盘规范化 `E_final` | 工程验收 | 已完成 |
| M1 | 冻结 Codex 与 RONDO 同一 TB 2.1 任务端到端可归档 | 工程验收 | 已完成 |
| M2（旧） | 同时承担“测评设施就绪”与“方向 1 解锁” | —— | **已拆解退役**，见下 |
| Local M3 | 4k model-backed、结构化输出、真实 `E_final`、fail-closed 与配置切换形成真实本地审批闭环 | 工程验收 | 未完成 |
| Local M4 | 同一批冻结样本上正式比较 Sol / 未微调 Local / 微调后 Local，由人作采用/保留/停止决定 | 人判定 | 未完成 |
| Multi 里程碑 | 由 Multi 自行定义，**不继承旧 M2 的 `σ`/`delta` 总闸门** | 待定 | 待 D1 定下首个增量后确定 |
| M5（旧） | 首个 harness 优化在 canary 上取得可复现改善 | —— | 随方向 1 挂起 |

### 旧 M2 的拆解

方向 1 与 E-A 都已挂起，旧 M2 失去了原有消费者，因此拆开而不是勉强留着：

| 新单元 | 内容 | 性质 |
|---|---|---|
| 公平比较设施 | catalog 对称、请求冻结分区、harness/deadline 固定、交错执行、重复与聚合规则冻结 | 设施交付，非里程碑 |
| Local M3 | 见上表 | 工程验收 |
| L5/L6 前置 dry-run | 约 5—10 条样本验证教师标签、Local 结构化输出、裁判标准与产物格式；不保存正式分数 | 前置检查，非里程碑 |
| Local M4 | 见上表 | 人判定 |
| Multi 里程碑 | 见上表 | 待定 |

**拆解不得丢失的依赖**：Multi 的付费退化验收仍然依赖公平比较设施闭合（§2 工作包 3c）。它不再叫 M2，
但依赖关系不变。

### 公平比较设施保留的机械判据

公平比较设施在自身范围内保留两个机械子门，不引入统计显著性框架，也不使用 pairwise-max `σ` 等事后放宽办法：

1. **A/A 行为一致性**：用同一二进制的预冻结重复观测形成不一致预算 `σ`；`σ` 是经验观测，不是统计估计。
2. **A/B 对称比较**：两侧在完全相同的 task-independent 合同下运行，跨侧差异 `delta ≤ σ`。
3. **方向性兜底**：对一侧 pass、另一侧 fail 的任务使用预冻结重复；若仍形成稳定单向失败，则判为不通过。
4. **infra**：基础设施失败不计能力分，只按同题运行链定点补跑；每轮后最终 infra 超过 2 项即 blocked；
   共同有效集合至少 8 项。
5. **预算**：基础运行、预冻结重复、infra attempts 与 wire canary 全部计入 campaign cap，并单独授权。

这套判据**只适用于该设施自身的等条件 A/A、A/B 比较**。Local M3、Local M4 与 Multi 退化验收都
**不继承** `σ`/`delta`（理由分别见 `doc/WBS/local-approval-model.md` 与
`doc/WBS/multi-agent-trusted-evidence.md`）。

v22 使用“两轮 RONDO A/A + 两侧各一轮 A/B + 条件两侧各加跑两轮”的历史公式；它的机械结果保持不改写，
但不作为新 campaign 的默认重复合同。若 catalog、请求冻结分区、harness、deadline、顺序、重复或聚合规则不对称，
不得形成能力归因；若 `σ` 接近任务总数，应回到 B4 重选 canary，而不是放宽判据。

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
模型版本不由本项目冻结，必须记录**生成/判定时点的模型标识与日期**；且只用于人在场监督的会话内工作，
**不得**作为程序化批量后端接进 `eval/`。数据外发门与订阅与否无关，仍然适用。

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
  工作流、是否先做证据层地基。**这是当前最大的未定项**：在它定下来之前，工作包 3c 没有实质内容，
  Multi 只能停在环境就绪。
- **D2 Multi 价值命题的最终措辞** —— 现有版本（见 `doc/WBS/multi-agent-trusted-evidence.md`）是初步框架，
  需在读完调研报告后确认或修正，特别是“朴素自然语言基线作对照组”是否采纳为设计约束。

两项都不阻塞工作包 1、工作包 2 与 3a/3b；它们只使 3c 暂时停在环境就绪。

## 9. 子规划索引

- `doc/WBS/eval-benchmark.md` —— 方向 0：量化测评基准
- `doc/WBS/local-approval-model.md` —— 方向 2：RONDO Local 本地审批模型接入与横评
- `doc/WBS/teacher-harness-study.md` —— 方向 1：教师研究成果到优化实验（挂起）
- `doc/WBS/multi-agent-trusted-evidence.md` —— 方向 3：RONDO Multi 产品线
