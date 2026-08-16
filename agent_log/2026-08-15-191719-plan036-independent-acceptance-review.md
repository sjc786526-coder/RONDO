# Plan 036 独立验收审查

日期：2026-08-15 ｜ 审查对象：`worktree-036-local-m4-offline-harness@b7d4a627`

## 结论

- **验收通过，任务目标完成。** 130 条冻结 validation 被完整、无重、无漏地分成 65 / 65 两批；26 个 source
  group 与 26 个 split group 均不跨批，tracked cohort 的 SHA-256 为
  `9dd901fff3df072ed65ff3962d1e4524255a5a42a3f810903d191457cb494b95`。
- 三方导入、L6 成对工件约束、匿名位置平衡、裁判结果导入、私有解盲、synthetic / holdout 分区聚合等任务目标
  均有实际实现与正负测试覆盖。真实状态诚实保持为 `waiting_for_l6_outputs`，没有伪造 Local 输出或启动正式 M4。
- 未发现影响功能正确性、任务边界或当前结论的 blocker；无需为本次验收新增审计设施、数据治理或重构任务。

## 独立复核

1. 从 `main@230f7a6` 到审查提交的 15 个文件差异与 Plan 036 范围一致；未修改 L5b 数据正文、Plan 032/033
   产物、历史结果、产品代码、模型配置或权重。
2. cohort manifest 可由当前 tracked validation 和合同重新构造；逐条 sample、payload、target、source group、
   split group、batch 与模板哈希均被绑定，manifest 本身不含 input、target、rationale、seed 或 mapping 正文。
3. 三方导入要求每个样本恰有 `sol-static`、`local-static`、`local-ft-static`。Sol 侧必须等于冻结 validation
   target；两个 Local 侧必须与同一 canonical L6 pair receipt 逐字段一致，且未微调/微调工件身份不同。
   Plan 033 的部署 baseline 不能通过该合同冒充 L6 成对未微调工件。
4. 裁判包只携带共享 approval input 与匿名 candidate decision；私有 seed 派生的稳定排列在每批分别满足
   side × position 计数差不超过 1。已知 side、模型/工件身份和明确模型路径会在打包或结果导入时被拒绝。
5. 正式导入会先验证全部裁判批次，再生成任何解盲文件；mapping、package、request、prompt、judge model、日期、
   batch、sample 与哈希漂移均会阻断。聚合不产生质量阈值或采用结论，并拒绝 synthetic / holdout 混算。
6. holdout 当前只交付独立私有输入合同和批次级公共投影合同，没有读取真实正文或物化 anchor；正式执行目录也
   尚未创建。这两点符合本任务 no-model 准备边界，不构成缺失实现或验收阻断。

## 独立验证

- `PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=eval python3 -B -m unittest -v eval.tests.test_local_m4_cross_eval`：
  **27/27 通过，0 skip**。
- 额外以 JSON Schema 对 L6 pair receipt、三方 side output、judge result 和 holdout summary 的完整合成 round-trip
  做交叉校验：通过。
- 独立解析 cohort：130 个唯一 sample、130 个唯一 payload；两批 65 / 65；26 个 source group 与 26 个 split
  group 全部只属于一个 batch。
- `git diff --check 230f7a6..b7d4a627`：通过；申报 cohort SHA-256 与文件实算一致。
- 审查期间未运行模型、训练、网络、Cargo、Docker、正式 M4、Opus 裁判、真实 holdout 或全量测试。

## 非阻断判断

- 核心模块与测试规模大于原先预期的中等任务，但现有复杂度对应了完整三方导入、盲化和解盲闭环；未发现因此
  产生的功能错误。本轮不要求为缩短代码而重构，也不另立整理任务。
- `judge-request-<batch>.json` 是未来人在场裁判时与 prompt、judge package 一起使用的身份清单；当前数据布局已
  记录其职责。无需在本任务增加会话自动化或程序化 Opus 后端。

## 代用户作出的决策

1. **接受全部 130 条 validation 与 65 / 65 group-safe 两批作为首版 M4 synthetic 主体。** 不回开抽样或重新分批。
2. **接受 validation 中冻结的 point-in-time Sol target 作为 `sol-static`。** 不为本任务重新调用 Sol。
3. **接受轻量 canonical L6 pair receipt 作为未来成对归因入口。** 不扩建签名、可信制品库或生产级模型审计系统；
   真正的工件与训练事实由 L6 产生并在当时验证。
4. **接受 holdout 与正式执行目录继续保持待物化。** 不为完成准备任务读取真实 holdout、生成 fake Local 输出或提前
   启动 M4。
5. 当前没有执行者遗留的额外策略问题需要用户确认；项目当前路线和授权门继续只以 WBS 为准。

## 项目状态

- 验收状态：**通过**。
- 任务目标：**完成**。
- Plan 036 交付状态：实现提交已存在，当前仍未合并、未推送；正式 L6 和 Local M4 均未开始。
