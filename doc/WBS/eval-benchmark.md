# 方向 0：量化测评基准

最后更新：2026-08-21 ｜ 依赖：P0（S1/S2）｜ 当前测评对象：RONDO Local（`mydev/`）｜
设施实现保持产品无关 ｜ Codex 基线：`v0.147.0` ｜ 顶层路线见 `doc/WBS.md`

## 目标

建立可重复、可归档的性能判据，并保证冻结 Codex 与各 RONDO 产品的真实比较满足等条件合同。

- **E-B 真实 API + Terminal-Bench 2.1**：低频验证 RONDO Local 行为改变型优化，是能力与性能结论的最终来源。
- **E-C 设施自测**：保证记录、计分、归因和门禁本身不会说假话。
- **E-A 离线冻结回放**：**已随方向 1 一并挂起**，见下文；日常回归改由测试体系承担。

测评设施本身继续保留和维护，但定位调整为：关键阶段的不退化检查、产品变体对比和最终验收，
不再承担高频回归。设施实现保持**产品无关**，能接收不同二进制与产品 variant；Plan 051 已完成当前方向 0
的 RONDO Local / 同基线冻结 Codex 正式 campaign，RONDO Multi 的主动委派测评仍不属于本方向。

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
| E-B8 公平比较设施 | 完成 | 六项合同已成为 campaign schema v7 的机械约束，并由 Plan 051 v28 正式 campaign 贯通验证。 |
| 首次 v7 正式 canary | **完成** | Plan 051 v28：10/10 共同有效，双方均 5/10，`sigma=0`、`delta=0`，三层判据通过；未运行 validation/holdout。 |
| E-A A1—A7 | **挂起** | 随方向 1 一并挂起，不排期；保留为历史设计，见下文。 |

v22 的 `sigma=0`、`delta=3` 与 `ab_delta_exceeds_aa_sigma` 是对既有冻结输入的机械结果。固定归因报告确认
catalog prompt 相差 161 tokens，同时混有 harness/deadline 和时间分块差异；因此该批次只证明执行、结算、归档和
机械门运行到了终态。报告见 `doc/research/plan020-b7-canary-baseline-failure-attribution.md`。

P2 v2—v22 公共账本已合入当前交付历史：`runs.jsonl` 的 `track=tb` 部分共 244 条唯一 run，其中 v22 为 32 条；
v6—v22 共 11 份聚合 JSON。Plan 051 的 distinct results worktree 另有 v28 的 40 条 `track=tb` 与 1 份
schema v7 aggregate，待后续批准合入后本方向共 284 条。方向 2 的 L3/L4 另有 4 条 `track=shadow`，不属于本方向。
历史标签中的“Plan 015”保留原样，当前权威编号仍为 Plan 020。

## E-B8 公平比较设施（已闭合）

六项合同已实现为 campaign schema **v7** 的机械约束。v1—v6 是冻结历史，slot 顺序、run_id 分配与
assessment 语义一律不变，新规则只在 v7 生效。

1. **catalog 对称**：两侧加载同一份完整 8-model catalog artifact。artifact 身份是它自己的 SHA-256，
   不再绑定任一侧二进制的 source commit；lock 另记上游/RONDO 两个来源的 commit/path/blob ID、
   投影算法与版本、main/Guardian model 与 override 目标 entry。两个来源 blob 不一致时判定无共享工件、直接拒绝。
2. **请求前置硬门**：`rondo_eval.fair_comparison` 投影每个请求中与任务无关的分区
   （tool specs、instructions、输出 schema、采样合同，以及 `input` 中首个 user 之前的 developer/system 前缀 ——
   Responses Lite 的 catalog 派生工具描述就在那里）。**合同必须先由 stub 运行冻结成 preflight receipt**：
   `just eval-b7-preflight-receipts` 驱动两侧冻结二进制走真实 Harbor/Docker 链路，但唯一可达端点是本地 stub，
   零请求零费用；比对通过后写出绑定 campaign_id / lock SHA / task / 两侧 bundle manifest 的 receipt。
   stub 与付费路径共用同一套 RunSpec 与 catalog 投影函数，因此 receipt 冻结的请求不会与被付费的请求分叉。
   付费 worker **启动时一次性校验全部任务的 receipt**，位置在 wire canary 之前，缺失或绑定不符即拒绝整个 campaign；
   运行期代理再以该 receipt 预置期望，因此**第一侧也受检**，不存在"先放行首侧、只拦第二侧"的窗口。
   任一侧不符即在请求体解析后、预算预留与上游转发之前 fail-closed，HTTP 409 直接返回**具体分区**原因码。
   完整请求 digest 各侧分别记录，只作 provenance/drift，不要求轨迹分叉后逐字节相等。
   `just eval-preflight-symmetry` 是纯离线的两份已捕获请求比对入口，不产出 receipt。
3. **执行条件统一**：lock 冻结 harness commit、upstream deadline、task/image digest、provider profile 与
   投影版本。声明值不是自说自话 —— 加载时与 campaign 自身的权威字段（baseline deadline、selected profile 哈希、
   catalog artifact SHA、冻结 canary 的 task/image）逐项等值校验，harness commit 在执行时与实际 checkout 校验，
   任一项漂移给出可归因原因码并拒绝比较。基础轮调度改为**按任务交错**（task-major），
   不再整轮时间分块；某轮最后一题落地即刻做 infra 阈值检查，保留原有的提前停机。
4. **判据分层**：assessment 分别输出 `aa_consistency`、`cross_side`、`directional` 三个子门的状态、原因与指标，
   不再用一个含糊的“性能门”概括。条件加跑进入**最终聚合** —— 触发题每侧的 outcome 是冻结重复的严格多数，
   `delta` 用聚合后的 outcome 计算（同时保留 `base_delta` 供对照）。
   触发条件是**任一方向的跨侧差异**；方向性兜底仍只检测 RONDO 全败/上游全过这一种回退模式。
5. **重复规则预冻结**：lock 必须冻结差异题每侧总观测数与聚合公式，否则拒绝建立 campaign。
   基础 A/B 没有跨侧差异的题保持单次观测；被触发的差异题每侧总观测数为奇数且不少于 3（基础 A/B 算其中
   一次，因此条件加跑为 `n-1` 次），聚合固定为严格多数。样本数与冻结值不符即拒绝，不允许事后删题或改分母。
   唯一的 successor 生成入口 `just eval-b7-next-identity` 只能生成 schema v7，必须传入预先冻结的
   comparison 合同文件与授权 cap；合同不合法时在读写任何文件之前失败，因此无法再生成绕过这些门禁的历史 schema campaign。
   Plan 051 不另跑付费 pilot，直接在正式数据前冻结三次严格多数。首个 v7 从公平合同上 fresh 开始：
   **不继承任何 v1—v22 continuation**（加载时强制为空）且历史 prior 为 0；Plan 051 的 v23 与其 successor
   另由同一任务预算累计，后继不能再次归零。
   run ID 区间按冻结重复数算出的真实 slot 数校验，5/7/9 次重复不会让尾部区间与历史碰撞。
   写 lock 前还会用真实事实核对新 comparison：共享 catalog 必须能从两个记录 commit 复现出声明的 artifact SHA，
   harness commit 必须等于当前 checkout，task/image 与 provider profile 必须等于 campaign 自身字段。
6. **保留机械判据**：`σ` / `delta` / 方向性兜底 / infra 上限按 `doc/WBS.md` §5 执行，
   不使用 pairwise-max `σ` 等事后放宽办法。比较合同不成立时直接 blocked，不计算能力归因。
   该判据**只适用于本设施自身的等条件 A/A、A/B 比较**，Local M3/M4 与 Multi 退化验收都不继承。
7. **产品无关设施、明确 campaign 对象**：`Product`（`rondo-local` / `rondo-multi`）与比较侧 `side`
   正交，v7 lock 显式记录产品身份；`codex` 不是产品取值。设施继续保留不同产品的身份校验能力，但当前首次
   v7 正式 canary 必须锁定 `rondo-local`，不得复用或导入 Multi 主动委派重跑的身份、trace 或结果。

E-B8 当时只闭合设施；Plan 051 随后以全新 IDs 完成了正式 v7 identity 生命周期、真实 API、结算与结果发布。
v23—v27 如实保留为本地设施适配/诊断 identity，v28 是首个有效产品基线；全部 identity 共用同一 400 USD
任务 envelope，未继承或改写 v1—v22。

它是**设施交付物，不是里程碑**：旧 M2 已拆解退役，它不再充当解锁其他方向的总闸门。
Multi 第二期与方向 0 没有产品依赖；两者只因项目排期、API 预算、Docker 和构建资源而串行。
Multi 的主动委派重跑不能充当 v7 pilot，也不能替代 Local 与冻结 Codex 的公平比较。

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

## 首次 v7 正式 canary（Plan 051 已完成）

Plan 051 固定 RONDO Local `54f62e5f7e86a7ab0d4f8d788eafec7176809395` 与 Codex
`v0.147.0@be6e8eac029b183056b7e4402879f15d2c85f61b`，使用同一冻结中转站、双方 Terra main-medium 与
Guardian-low。v28 的十题双侧 stub receipt、wire、按任务交错的两轮 Local A/A 与一轮 Local/Codex A/B、结算、
聚合和发布均完成；未进入 validation、holdout、E-A、本地模型或训练。

正式结果为 10/10 个共同有效任务，Local 的两轮 A/A 与一轮 A/B 均为 5/10，Codex A/B 为 5/10；五道题双方通过，
五道题双方有效失败，`sigma=0`、`base_delta=0`、`delta=0`。由于基础 A/B 没有差异，预冻结条件槽均未激活；
A/A、cross-side 与 directional 三层机械判据均为 `passed`。这只表示冻结十题与当次合同下未观察到差异，不能推广
到完整 Terminal-Bench 2.1 或其他模型/effort。

v23—v26 在零 API 阶段关闭；v27 完成 wire 与首个产品槽后暴露本地 schema v7 发布缺口，可靠结算 `$0.270445`
并由 v28 successor 重新形成正式比较。v28 identity 结算 `$9.142443`，Plan 051 累计 `$9.412888`，全部 400 个
上游 attempt 都有可靠 usage，`actual_usd` 仍为未知；任务 envelope 已关闭，无 active identity 或未结 reservation。
所有有效 pass、reward 0 与任务失败均原样保留，没有按成绩重跑。

后续使用稳定入口创建新 baseline 时仍须另立 identity、重新冻结产品 bundle、comparison、价格与当次预算，并取得
对应真实 API/Docker 授权；本次 400 USD 授权和余额不自动延续。具体历史合同与执行边界见
`plan/051-direction0-schema-v7-first-formal-canary-execplan.md`。

## 硬约束

- 测评默认关闭，对功能路径的性能影响必须可忽略。
- 冻结 Codex 与 RONDO 的条件由设施机械写死和核验，不依赖人工保证。
- 隐藏集信息不得进入日常开发；只保留聚合结果。
- 任何真实 API 跑批须单独授权并给出任务、轮数、模型和预算。
- fake、skip、未运行、无效比较和 infra 不得表述为能力通过。
