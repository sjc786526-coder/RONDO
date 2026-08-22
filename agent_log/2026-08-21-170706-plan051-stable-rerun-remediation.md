# Plan 051 稳定重跑入口整改

- 外部独立验收确认 v28 首次正式结果、费用和资源链有效，但发现两个真实阻断：v7 loader/identity/task budget 把
  `54f62e5...` 与唯一 Plan 051 400 USD envelope 固定死；合法 `failed` 聚合返回 2 时会跳过 envelope 关闭和 active
  pointer 退役。两项均以现场代码复现，没有重跑 v28 或任何真实请求。
- `just eval-plan051` 现以同一入口承载 `initialize|prepare|preflight|run|resume|finalize|compare`。初始化显式绑定
  campaign/batch、Local commit/manifest、价格日期与独立 task-budget ID/cap；后续授权使用按 ID 隔离的新 envelope，
  旧 Plan 051 文件名、v23—v28 identity 与累计 `$9.412888` 全部只读保留。新任务 paid action 同样绑定 budget ID；
  stub preflight 由入口经共享构建锁/看门狗启动。
- v7 稳定合同仍固定冻结 Codex、Terra main-medium/Guardian-low、题集和判据，但不再固定 Local commit 或任务预算。
  `passed`/`failed` 只有在发布返回码分别为 0/2 且预算闭合事实匹配后才退役 pointer；其他返回码不伪装终态。
- 相对基线采用自动选择 results worktree 中最新兼容正式 schema v7 前驱的轻量方案，避免人工填错前驱；单独写入
  `eval/results/baseline-comparisons/`，不改历史 aggregate。离线发布 v28 的 `first_formal_baseline` 后，其原 aggregate
  SHA-256 仍为 `53e9b4b3ee74cefd7215c8f2b6bfcdbe6da46c9f3c31a88089adcc9bd02a0c8f`。
- 相关 9 模块无 API 回归 357/357 通过；默认入口为 `idle` / 0 requests，relative compare 重入成功。未运行 Docker、
  Cargo、真实 API、全 workspace、CI/PR、validation、holdout、本地模型或训练。
- 验收报告建议仅在没有执行者会话直接用户消息时，把 Guardian-low 的来源改成“独立验收采纳”。本会话中用户已明确
  指示“审批模型使用的思考程度都使用 low，修改合同”，因此保留 Plan 的“用户在执行中明确修订”归因；没有把审查者
  的条件性假设改写成虚假的历史。
