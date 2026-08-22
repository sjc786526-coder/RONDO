# Plan 051 最终独立验收

日期：2026-08-21

结论：**验收通过；任务目标完成。** 未发现剩余 correctness/functionality 阻断。首次 schema v7 正式 v28 基线有效，稳定统一重跑入口已具备新 Local/独立预算初始化、无 API 预检、连续运行、正常与 blocked 终态处理、崩溃恢复、结算归档及相对基线发布能力。

## 验收结论

- `run` passed/0 与 `resume` failed/2 会在返回前关闭 exact task-budget envelope、复核 closed identity 并退役 active pointer；退出码保持 0/2。
- `finalize` 能正确恢复 envelope 已关闭、pointer 尚未退役的中间崩溃窗口：它在进入 runner 前识别匹配的 closed record，跳过要求 active envelope 的 runner，直接完成 pointer retirement。测试明确断言该路径不得调用 runner。
- durable passed/failed 与 runner 退出码不匹配时明确抛出错误，不关闭预算、不退役 pointer，也不会把 failed 终态误报为成功。
- blocked aggregate 正常归档但不生成 relative formal baseline；入口保留 active identity/pointer 并返回 3，供 successor 按原预算链继续恢复。
- 新 Local commit/manifest、campaign/batch、价格日期和独立 task-budget ID/cap 均为显式输入；Plan 051 已关闭的 400 USD envelope 不会被后续任务重开或复用。
- v28 正式结果没有因整改被重跑或改写。tracked public baseline 与派生 comparison SHA-256 分别保持 `53e9b4b3...02a0c8f`、`56a0a704...3ef51`，baseline/raw runs 相对既有 results 提交无差异。

## 定向验证

- formal canary、task budget、relative baseline、新 identity/budget 相关无 API 单测 32/32 通过；其中 formal entry 13/13 覆盖正常、blocked、closed-envelope 恢复及双向退出码错配。
- 修改模块 `py_compile`、`git diff --check` 通过。
- 默认 `just eval-plan051` 返回 `idle`、`active_lock=null`、`paid_requests_sent=0`。
- execution、results 与 main 在写入本报告前均干净；results 仍为 `696ea651f036734359036141d04180edeb621dbc`，main 仍为 `9bd38fc342e9d3d087a162432fbb90469b1018d1`。
- 未运行 Docker、Cargo、真实 API、全 workspace、CI/PR、validation、holdout、本地模型或训练；这些均不是本轮窄修所需。

## 代用户作出的决策

- 接受 implementation commit `d1b91ebb3afbdc5ebbc79b8b37ba786ac38c3bdb` 的功能性实现，Plan 051 按已完成处理。
- v28 继续作为首次正式 schema v7 基线，不创建 successor、不重跑，不改变既有费用、identity、lock、ledger、raw result 或比较合同。
- 保留双方主模型 Terra/medium、Guardian Terra/low 及既有用户直接修订归因。
- 不追加重型测试、审计、可信、调度或新测评设施；当前证据已足以完成本任务验收。
- 本次授权边界仍是不合并、不推送、不归档。execution/results 分支和工作树保持待交付状态，后续合并、推送与归档须由用户批准。
- 按用户约定，验收通过后不再向执行者跨会话队列发送整改消息。

## 当前状态

- 正确性/功能性验收：**通过**。
- 整体任务目标：**完成**。
- Git 交付：实现和结果均已在各自专用工作树提交；尚未合并、推送或归档。
