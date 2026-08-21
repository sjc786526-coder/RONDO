# Plan 049 非 infra 终态缺失 trace 分类整改

## 结论与修改

- 独立审查 finding 已复现：Harbor 已给出非 infra 结果后，`find_trace_bundle` 的 `TraceError` 仍被包装为
  `FormalInfraError`，campaign 会购买替代 attempt。
- 修复保持在 Plan 049 executor：`INFRA_FAILED` 继续走有界 infra retry；其余已解析结果缺 trace 且没有独立 infra
  证据时持久 `principled_stopped`，禁止 a02。
- 回归矩阵主动覆盖 `COMPLETED` 成功、`COMPLETED` 有效任务失败、`AGENT_FAILED` 与 `CANCELLED`。这是对报告建议的
  必要补全：missing trace 本身不是 collector 故障证据，不能只修两个失败枚举后让已知成功或有效失败仍被替换。
- 另有反向回归精确证明 `INFRA_FAILED` 仍抛 `FormalInfraError`，且不会进入 trace 查找。

## 验证

- 新增两项定向回归：2 tests，OK。
- `tests.test_proactive_eval`：32 tests，OK。
- `tests.test_terminal_bench tests.test_api_budget_proxy tests.test_multi_m5`：144 tests，OK。
- `tests.test_team_lens`：25 tests，OK。
- v4 rehearsal + v5 loopback readiness：exit 0，`offline-evidence-ready`，26 runs。

未运行真实 API、Docker、Cargo、付费操作、完整数据集或全 workspace；未创建正式 paid namespace、receipt、账本或
run/result identity。当前等待 clean commit 上的最终独立复验，阶段 B 仍未授权。
