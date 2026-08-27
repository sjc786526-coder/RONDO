# Plan 094 阶段 A 首轮审查整改

## 结论与修改

- 复核 `agent_log/2026-08-26-231728-plan094-stage-a-review.md` 的 1 High / 3 Medium，四项均存在。
- 增加 Plan 094 专用 paid-segment 薄门：bootstrap 和后续 launcher 都消费五分钟内的 task-owned budget snapshot、实际核验的 compute/storage
  费率与有限 timeout；按保守既有费用、完整 segment 上界和 closure reserve 同时约束 5 USD 与实时余额，不改根抢卡脚本职责。
- Plan 090 `source_external` observation 只保留 continuation previous/reassessment 语义，不再进入 Plan 094 latest、material、best、training-best
  或 turning 角色；首个自有 checkpoint 后这些角色才建立。
- `real_training_run` 只认 Plan 094 自有完整 checkpoint/overlay，历史 update 导入本身不再产生本任务训练 claim。
- bootstrap 在 existing/download snapshot 分支之前无条件清除三个不需要的 Hub token 变量，并把 Hub cache/telemetry 固定在任务 root。

## 验证与边界

- Plan 094 focused unittest：16/16 通过；新增覆盖 fresh/rate/timeout 预算拒绝、历史-only 与首个自有 checkpoint 角色/claim、existing-model
  token 清除顺序。相邻 Plan 090 training/delivery 16/16、compileall、freeze/segment CLI、三份 shell `bash -n` 与 `git diff --check` 通过。
- 未改变模型、数据、Route O、material rubric、停止或最多六点保留合同；未运行 Cargo、Docker、真实模型或外部写，付费门保持关闭。
