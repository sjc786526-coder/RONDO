# RONDO 长程规划（WBS）

最后更新：2026-08-13

本文件与 `doc/WBS/*.md` 是项目**当前状态与后续规划的唯一来源**。本文件只保留阶段级状态、下一工作包、
跨方向顺序、依赖和授权门；方向内部的任务分解见子 WBS。已完成成果与详细证据见
`doc/WBS-COMPLETED.md`，单次任务合同见 `plan/`，研究与审计只作为形成时点的证据。

## 1. 当前阶段

上游基线冻结为 Codex CLI `v0.147.0`（`rust-v0.147.0`，commit
`be6e8eac029b183056b7e4402879f15d2c85f61b`）；机器事实源为
`mydev/codex-rs/core/upstream-source-baseline.toml`。

| 范围 | 当前结论 |
|---|---|
| P0 共享地基 | S1 审批模型覆盖与 S2 `E_final` 证据捕获已完成，开关默认关闭。S1 只覆盖模型与 effort，不覆盖 provider。 |
| 测试基线 | Plan 004 完成对旧 81 项失败的分批整改后，最近一次有记录的 `v0.147.0` RONDO 全 workspace 实际执行 14,092 项：14,060 通过、31 失败、1 超时，Nextest 另列 23 项 ignored；P0 仍以定向验收收口。此后未重跑全 workspace，不能把该历史快照表述为当前全绿或当前失败复现。 |
| P1 / M1 | B1、B2、B3 与 M1 已完成；冻结 Codex 与 RONDO 已在同一 TB 2.1 任务上完成真实端到端并归档。 |
| P2 / 方向 0 | B4—B7 执行设施和 v22 真实执行已完成；E-A A1—A7 未实现，M2 未达成。 |
| v22 结论 | 机械一致性子门得到 `sigma=0`、`delta=3`，以 `ab_delta_exceeds_aa_sigma` failed；但 A/B 存在 catalog prompt 161-token 非对称、harness/deadline 混杂和非交错执行，因此**不能据此归因 RONDO 与 Codex 的能力或性能差异**。报告分歧已全部关闭。 |
| 结果数据 | P2 v2—v22 公共账本已合入：`eval/results/runs.jsonl` 共 244 条唯一 run，v22 为 32 条；v6—v22 的 11 份聚合 JSON 同步入库。原 results 分支已收口为 `zz-done/0811-p2-b7-results`。 |
| 方向 2 | L1、L2a、CPU/CUDA model-free runtime 与唯一 GGUF 静态完整性已完成。当前 CUDA 能力为 `linux_cuda_built_model_unvalidated`；真实配置仍是旧合同，4k/8k model-backed、真实结构化推理、L3/L4/M3 均未完成。 |
| 方向 1 | 教师 harness 研究 T1—T3 已完成，候选及证据见研究报告；正式优化仍由 M2 阻塞。 |
| 方向 3 | 多智能体可信证据研究已完成，产品实现未开始，仍排在方向 1 之后。 |

当前不再维护 v6—v22 的逐轮过程、请求数和费用流水；这些历史只保留在
`doc/WBS-COMPLETED.md`、对应 plan、agent log 与冻结结果中。

## 2. 下一工作包与顺序

### 当前主工作包：公平比较合同闭合（无真实 API）

依据 B7 归因报告已经关闭的证据，本 WBS 冻结以下设施修正合同：

1. 两侧使用同一份完整 8-model catalog bytes，并在工件中绑定 SHA 与来源字段。
2. 上游调用前比较剔除任务内容后的 task-independent tool specs、instructions、schema 等冻结分区；完整请求 digest
   各侧分别记录用于 provenance/drift，不要求轨迹分叉后的动态请求逐字节相等；增加无上游 stub preflight。
3. 固定相同 harness commit、deadline 与运行条件；正式顺序按任务交错，不再按整轮时间分块。
4. assessment 分开输出“方向性结果”和“A/A 行为一致性”；条件加跑进入最终聚合。
5. 重复数在 pilot 后、正式执行前冻结；波动任务使用奇数且不少于 3 次，不事后删样本。P2-2 必须同时冻结
   多轮结果如何聚合为每题 outcome、`σ` 与 `delta`，在公式未机械化前不得建立新 campaign。

该工作包只修比较设施和离线验收，不产生付费调用。完成后再冻结新的 B7 campaign 合同；不得复用 v22 ID。

### 后续串行：E-A 轻量离线冻结回放

按 `doc/WBS/eval-benchmark.md` 的 A1—A7 完成录制、回放、冻结用例、探针、故障注入、归档曲线和一键入口。
公平比较合同与 E-A 可在设计上并行，但都修改共享 eval 合同，实际合并与验收应串行，避免两套 schema 漂移。

### M2 重新验收

- 先用无上游 preflight 和离线设施证明请求对称、归档与判据输出正确。
- 只有公平比较合同与 E-A 均闭合后，才制定新的 canary 实验并单独申请任务数、轮数、模型与预算授权。
- 新执行必须产生可归因的等条件证据；未满足比较合同即 blocked，不进入能力结论。

### 并行次线：方向 2 model-backed 验收

方向 2 可以与 P2 的无 API 工作交错推进，但真实模型加载/推理必须与重型 Cargo、Docker 互斥：先迁移真实本地配置，
再做 exact GGUF 4k smoke，之后才评估 8k baseline、L3/L4 与 M3。4k 未通过时不得称本地审批服务就绪。

## 3. 方向与依赖

| 编号 | 方向 | 状态 | 解锁条件 |
|---|---|---|---|
| 0 | 量化测评基准 | P2 进行中 | 公平比较合同、E-A 与新的等条件 B7 共同闭合 M2 |
| 1 | Harness 优化 | 研究完成，实施未开始 | M2 通过后按候选队列逐项实验 |
| 2 | 本地审批模型接入与横评 | model-free/静态前置完成 | 4k/8k model-backed、L3/L4 后形成 M3 |
| 3 | 共享可信证据链的多智能体协作 | 研究完成，实施未开始 | 方向 1 形成稳定优化循环后启动 |

方向 0 与方向 2 共用 P0；方向 1 的正式实现依赖 M2；方向 3 排在方向 1 之后。方向 1、方向 3 的研究成果不等于
实施已解锁。方向 2 的真实 `E_final` 必须按稳定语义哈希切成互斥 `seed` / `holdout`，真实证据本身不得进入训练集。

## 4. 阶段与里程碑

| 阶段 | 内容 | 状态 |
|---|---|---|
| P0 | S1 审批模型显式覆盖、S2 审批证据快照 | 已完成 |
| P1 | B1—B3 最小真实链路；L1/L2 model-free 前置 | 已完成，M1 通过 |
| P2 | E-A；B4—B7；L2a/L3/L4 | 进行中，M2/M3 未通过 |
| P3 | L5 合成数据、L6 微调、L7 一键切换 | 未开始 |
| P4 | 基于 M2 的 harness 优化迭代 | 未开始 |
| P5 | 可信证据型多智能体内核 | 未开始 |

| 里程碑 | 验收口径 | 状态 |
|---|---|---|
| M0 | Guardian 模型/effort 显式生效并落盘规范化 `E_final` | 已完成 |
| M1 | 冻结 Codex 与 RONDO 同一 TB 2.1 任务端到端可归档 | 已完成 |
| M2 | E-A 一键回放出曲线；等条件 canary 通过下述机械判据 | 未完成 |
| M3 | Luna-static / Sol-static / Local-static 同证据横评首版 | 未完成 |
| M4 | 微调后横评与审批模型一键切换 | 未完成 |
| M5 | 首个 harness 优化在 canary 上取得可复现改善 | 未完成 |

### M2 的判据与待冻结执行合同

M2 保留两个机械子门，不引入统计显著性框架：

1. **A/A 行为一致性**：用同一 RONDO 二进制的预冻结重复观测形成不一致预算 `σ`；`σ` 是经验观测，不是统计估计。
2. **A/B 对称比较**：冻结 Codex 与 RONDO 在完全相同的 task-independent 合同下运行，跨侧差异 `delta ≤ σ`。
3. **方向性兜底**：对 Codex-pass / RONDO-fail 的任务使用预冻结重复；若仍形成稳定单向失败，则不通过。
4. **infra**：基础设施失败不计能力分，只按同题运行链定点补跑；每轮后最终 infra 超过 2 项即 blocked；共同有效集合至少 8 项。
5. **预算**：基础运行、预冻结重复、infra attempts 与 wire canary 全部计入 campaign cap，并单独授权。

v22 使用“两轮 RONDO A/A + 两侧各一轮 A/B + 条件两侧各加跑两轮”的历史公式；它的机械结果保持不改写，
但不作为新 campaign 的默认重复合同。P2-2 必须在 pilot 后、真实执行前机械冻结奇数重复如何聚合为每题 outcome、
`σ`、`delta` 与方向性终态。若 catalog、请求冻结分区、harness、deadline、顺序、重复或聚合规则不对称，
不得形成能力归因；若 `σ` 接近任务总数，应回到 B4 重选 canary，而不是放宽判据。

## 5. 授权门

以下动作每次执行前都需单独授权，历史授权不自动延续：

- Docker 拉取、构建或运行。
- 真实 API 批量测评：须冻结任务范围、轮数、模型和预算上限。
- 真实本地模型加载或推理。
- GPT 批量合成数据、任何真实数据外发。
- 云 GPU 训练、上传或下载权重、产生外部费用或状态变更。
- 上游基线升级。

## 6. 测试与测评原则

- 测试验证代码与设施正确性，复用上游 Rust/Nextest 等体系，只补受影响模块的必要回归。
- 测评提供性能指标，默认关闭、轻量、自动记录归档；离线、fake、真实 API、真实模型和 Docker 证据严格区分。
- 冻结 Codex 与 RONDO 的公平横比只使用同口径外部指标；RONDO 内部探针只用于自身版本间诊断。
- skip、未运行和无效比较不能表述为通过；测评设施合同不满足时不得解释产品能力。
- 结果与数据资产边界遵循 `doc/eval-data-layout.md`。

## 7. 子规划索引

- `doc/WBS/eval-benchmark.md` —— 方向 0：量化测评基准
- `doc/WBS/local-approval-model.md` —— 方向 2：本地审批模型接入与横评
- `doc/WBS/teacher-harness-study.md` —— 方向 1：教师研究成果到优化实验
- `doc/WBS/multi-agent-trusted-evidence.md` —— 方向 3：可信证据型多智能体内核
