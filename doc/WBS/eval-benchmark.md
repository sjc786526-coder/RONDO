# 方向 0：量化测评基准

最后更新：2026-08-13 ｜ 依赖：P0（S1/S2）｜ 服务对象：RONDO Local 与 RONDO Multi ｜ Codex 基线：`v0.147.0` ｜ 顶层路线见 `doc/WBS.md`

## 目标

建立可重复、可归档的性能判据，并保证冻结 Codex 与各 RONDO 产品的真实比较满足等条件合同。

- **E-B 真实 API + Terminal-Bench 2.1**：低频验证行为改变型优化，是能力与性能结论的最终来源。
- **E-C 设施自测**：保证记录、计分、归因和门禁本身不会说假话。
- **E-A 离线冻结回放**：**已随方向 1 一并挂起**，见下文；日常回归改由测试体系承担。

测评设施本身继续保留和维护，但定位调整为：关键阶段的不退化检查、产品变体对比和最终验收，
不再承担高频回归。设施实现保持**产品无关**，能接收不同二进制与产品 variant。

## 当前状态

| 工作项 | 状态 | 当前边界 |
|---|---|---|
| B1 环境与接口 | 完成 | Harbor `0.20.0`、TB 2.1 commit、task/image、双侧 bundle 已冻结。 |
| B2 双侧 no-API | 完成 | 同进程 RONDO→Codex 串行、Docker/watchdog、tool round-trip 与清理证据通过。 |
| B3 / M1 | 完成 | v19 双侧真实 `fix-git` completed/reward 1，M1 passed；历史 identity 不可复用。 |
| B4 分层 | 完成 | 10 canary / 61 validation / 18 holdout 已按 task ID 哈希冻结。 |
| B5 计分归因 | 完成首版 | agent、Guardian 与 infra 可分离；后续 assessment 需再拆方向性与行为一致性。 |
| B6 预算 | 完成首版 | v1—v22 只读，active paid identity 已关闭。 |
| B7 首次执行 | 执行完成、结论不可归因 | v22 机械一致性子门 failed，但比较条件不对称，不能解释为 RONDO/Codex 能力或性能差异。 |
| E-A A1—A7 | **挂起** | 随方向 1 一并挂起，不排期；保留为历史设计，见下文。 |

v22 的 `sigma=0`、`delta=3` 与 `ab_delta_exceeds_aa_sigma` 是对既有冻结输入的机械结果。固定归因报告确认
catalog prompt 相差 161 tokens，同时混有 harness/deadline 和时间分块差异；因此该批次只证明执行、结算、归档和
机械门运行到了终态。报告见 `doc/research/plan020-b7-canary-baseline-failure-attribution.md`。

P2 v2—v22 公共账本已合入当前交付历史：`runs.jsonl` 共 244 条唯一 run，其中 v22 为 32 条；v6—v22
共 11 份聚合 JSON。历史标签中的“Plan 015”保留原样，当前权威编号仍为 Plan 020。

## 当前工作包

### E-B8 公平比较设施闭合（无真实 API）—— 对应 `doc/WBS.md` 工作包 1

1. **catalog 对称**：两侧使用同一份完整 8-model catalog bytes；lock 记录最终 artifact SHA，上游/RONDO 两个
   来源各自的 commit/path/blob ID，投影算法/schema，main/Guardian model 与 override 目标 entry。
2. **请求前置硬门**：规范化并比较剔除任务内容后的 task-independent tool specs、instructions、输出 schema 等
   冻结分区；完整请求 digest 各侧分别记录用于 provenance/drift，不要求轨迹分叉后的动态请求逐字节相等。
   先用禁止上游调用的 stub preflight 证明冻结分区不对称会 fail-closed。
3. **执行条件统一**：冻结同一 harness commit、timeout/deadline、task/image 与 provider profile；按任务交错 A/A、A/B，
   不按整轮时间块串行。
4. **判据分层**：assessment 分别报告方向性分数、跨侧差异与 A/A 行为一致性，不再用“性能门”概括全部结论；
   条件加跑必须进入聚合。
5. **重复规则预冻结**：pilot 后、正式执行前冻结次数；波动任务使用奇数且至少 3 次；不得看结果后删样本或改轮数。
6. **保留机械判据**：`σ` / `delta` / 方向性兜底 / infra 上限按 `doc/WBS.md` §5「公平比较设施保留的机械判据」执行，
   不使用 pairwise-max `σ` 等事后放宽办法。比较合同不成立时直接 blocked，不计算能力归因。
   该判据**只适用于本设施自身的等条件 A/A、A/B 比较**，Local M3/M4 与 Multi 退化验收都不继承。
7. **产品无关**：实现不再假设“只有一个 RONDO 产品”，为产品身份（`rondo-local` / `rondo-multi`）留下明确入口；
   本工作包不创建 `multidev/`，产品身份的实际接入在 Multi 基线任务中完成。

验收只运行 pure/fake/loopback/stub 定向门禁，不调用真实 API。完成后才可制定新的 B7 campaign；新 campaign
必须使用新 IDs、独立 cap 和单独授权。

本工作包是**设施交付物，不是里程碑**：旧 M2 已拆解退役，它不再充当解锁其他方向的总闸门。
但有一条依赖不变 —— RONDO Multi 的付费同题退化验收不得早于本工作包闭合
（见 `doc/WBS/multi-agent-trusted-evidence.md`）。

## E-A 轻量离线冻结回放（已挂起）

> **状态：随方向 1 一并挂起，不排期。** E-A 当初是为低成本反复做性能优化而建；方向 1 挂起后它失去了主要消费者。
> 日常回归改由**测试体系**（单测、fake/loopback/replay 测试）保证正确性，而不是借测评设施兜底。
> 以下 A1—A7 保留为历史设计，不是待办工作包；将来重启方向 1 时需重新评估是否恢复，以及是否仍按此拆分。

### A1 录制器（规模 M）

- 在 HTTP 层录制完整请求/SSE，复用现有 proxy/dumper；authorization 等敏感字段脱敏。
- 同时记录 Standard/Responses Lite 形态、baseline/source commit、有效 policy hash 与请求规范化版本。
- 录制只作素材，不作为性能基线；低频运行，不进入严格耗时测评热路径。

### A2 回放服务器（规模 M）

- 按轮次返回冻结 SSE，计算实际请求与录制请求的结构化 drift。
- drift 为零才可用于行为保持型判据；非零必须显式标记为不适用，不用人工解释成通过。
- 同一录制包连续两次回放，输出、归档和外部指标应在冻结阈值内稳定。

### A3 冻结用例集（规模 S）

- 从已交付的真实运行中选取长轨迹、多工具、审批、compact 与失败恢复样本。
- 体积受控；隐藏分区内容和单任务结果不得进入仓库或日常开发循环。

### A4 探针与指标（规模 M）

- 外部指标：wall time、CPU time、peak memory、exit status，由同一 runner/supervisor 采集，用于公平横比。
- 内部指标：轮次、工具耗时、序列化、审批往返，只用于 RONDO 自身诊断。
- 探针默认关闭；开启时内存累积、轮末统一输出，不常驻写盘。

### A5 故障注入（规模 S）

确定性覆盖请求超时、SSE 断流、工具失败、沙箱拒绝与审批超时；验证恢复与归因，不做压力测试。

### A6 结果归档与曲线（规模 S）

统一写入 `eval/results/runs.jsonl` 与 `eval/results/baselines/`，schema、Git 交付和私有重资产边界遵循
`doc/eval-data-layout.md`。绘图按需运行，不常驻服务。

### A7 一键入口（规模 S）

提供一个 `just` 入口完成回放、判据、归档并输出与上一基线的对比；失败时保留可恢复证据并返回非零。

## E-C 测评设施自测

- 单测覆盖规范化器、计分器、归因分类器、结果 schema 与 active identity 门禁；回放服务器相关项随 E-A 挂起。
- 注入已知延迟、额外轮次和请求不对称，证明报告能检出且 fail-closed。
- 测试并入已有体系，不另起框架；只运行与本次改动相关的必要门禁。

## 再次执行 B7 的前置与验收

新的真实 canary 只有在以下条件同时满足后才能申请授权：

- E-B8 无上游 preflight 通过。**不再要求 E-A 完成**：E-A 已挂起，不作为前置条件。
- 新 identity 不复用任何 v1—v22 ID。
- 任务、轮数、交错顺序、重复规则、模型、价格快照、预算 cap 和停止条件全部预冻结。
- 按 `doc/WBS.md` §5 的机械判据执行，比较合同任一项漂移都先 blocked。

通过只表示在冻结样本与该合同下的等条件比较成立；不自动推广到全量 TB 2.1，也不自动解锁未获授权的下一轮费用，
更不构成任何方向的解锁闸门。

## 硬约束

- 测评默认关闭，对功能路径的性能影响必须可忽略。
- 冻结 Codex 与 RONDO 的条件由设施机械写死和核验，不依赖人工保证。
- 隐藏集信息不得进入日常开发；只保留聚合结果。
- 任何真实 API 跑批须单独授权并给出任务、轮数、模型和预算。
- fake、skip、未运行、无效比较和 infra 不得表述为能力通过。
