# 方向 0：量化测评基准

最后更新：2026-08-24 ｜ 状态：**设施保留，当前无 active campaign** ｜ 当前默认被测源码：`mydev/` ｜
Codex 基线：`v0.147.0` ｜ 顶层路线见 `doc/WBS.md`

## 当前定位

方向 0 提供轻量、可重复、可归档的性能测评设施，用于关键阶段的不退化检查、产品变体比较和最终验收。
它不替代正确性测试，也不因设施存在而自动触发新测评。

Plan 051 已完成首次 schema v7 正式 canary，并验证稳定创建、运行、恢复、结算、发布与相对基线入口。
完成过程、数字、费用和资源证据统一见 `doc/WBS-COMPLETED.md`；本页不再维护历史 campaign 流水。

当前没有 active identity、可继承预算或默认待跑样本。方向 1 已完成的 Plan 052、056、058、062 事实与指标均已
归入 `doc/WBS-COMPLETED.md`；方向 1 当前正式收口，不安排新的观测或内核/Harness 优化。未来如有新测评需求，
必须按届时目标重新立项、冻结身份并取得真实 API、Docker 与费用授权。

## 现行设施合同

1. **对象身份**：`product` 与比较侧 `side` 正交；新 campaign 显式绑定产品、源码 commit、binary manifest、
   上游基线、任务集、镜像和结果命名空间，历史身份不得复用或回填。
2. **请求对称**：冻结 Codex 与 RONDO 使用同一完整 model catalog；付费前由真实执行路径生成 stub preflight
   receipt，机械核对 task-independent 请求分区。任一侧不对称时在预算预留和上游转发前 fail-closed。
3. **执行对称**：模型、effort、provider profile、deadline、任务与镜像一致，基础轮按任务交错；不能用人工说明
   替代机器绑定。
4. **判据分层**：A/A 观测形成不一致预算 `sigma`；跨侧聚合差异要求 `delta <= sigma`，并另报方向性兜底。
   差异题重复数、聚合公式、共同有效任务下限和 infra 门在运行前冻结；各子门分别报告，合同不成立时不解释产品能力。
5. **预算与恢复**：wire、基础轮、条件重复和 infra attempts 全部计入该任务的独立预算；crash/resume 不重置费用。
   passed/failed 自动关闭预算并退役 active pointer，blocked 只由显式 successor 承接。
6. **结果语义**：有效任务失败、reward 0、infra、skip、未运行与不可测保持原语义；不得按成绩换题、删题、补跑、
   改分母或把缺失计为零。
7. **数据边界**：公共结果保持 body-free；原始请求、响应、trace 和隐藏集留在规定的本地私有命名空间。
8. **适用范围**：`sigma` / `delta` 等公平比较判据只属于本设施自己的等条件 A/A、A/B 比较；方向 1 的单侧
   有界观测复测使用其独立合同，不冒充双侧能力比较。

稳定入口为 `just eval-plan051 initialize|prepare|preflight|run|resume|finalize|compare`。这里的命名是保留的
设施入口，不表示 Plan 051 的历史 identity 或授权仍可使用。新任务必须提供新的 campaign/batch、被测 source
commit 与 manifest、comparison、价格日期及独立 task-budget ID/cap。

## 与其他方向的关系

- 方向 1 已正式收口，当前无 active campaign 或观测工作包；未来如重新启动，新测评不继承旧身份、预算或授权。
- 已永久收口的方向 2 不再消费本方向的新工作包；其历史 shadow 结果保持原身份。
- 方向 3 的专用协作测评不自动并入方向 0；如需复用公共设施，应在方向 3 WBS 中显式定义接口。
- 日常回归由测试体系承担，不借测评设施兜底。

## 新任务授权与验收边界

- 任何真实 API 跑批必须预先冻结任务、轮数、模型和预算并取得授权。
- Docker 与真实本地模型加载/推理按根 `AGENTS.md` 单独授权，并与重型 Cargo 全局串行。
- hidden validation/holdout 不因存在而默认可运行；使用范围必须写入新任务合同。
- 只运行与设施改动或新 campaign 直接相关的必要门禁；没有运行的项目如实记录。
