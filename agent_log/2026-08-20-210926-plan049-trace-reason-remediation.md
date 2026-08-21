# Plan 049 missing-trace 原因码整改

## 修改与依据

- 独立审查 finding 已复现：四种已解析非 infra 结果虽正确持久停止，但 JSONL 与 `run.json` 均误写
  `identity_or_fairness_drift`。
- executor 改抛专用 `FormalTerminalTraceError`；campaign 仍复用原有 principled-stop publication 分支，只按异常类型选择
  固定 code `non_infra_terminal_missing_trace`。不从异常正文派生 reason，也不改变 drift、request-limit 或 infra 路径。
- 该实现比复制一份专用 publication catch 更小：run.json→JSONL 顺序、append 恢复与 body-free 校验继续只有一条实现，
  同时专用类型避免给通用 `FormalError` 增加任意 reason 接口。

## 验证

- 修复前新增断言在 `COMPLETED` reward 0/1、`AGENT_FAILED`、`CANCELLED` 四个子用例均稳定失败，实际值为
  `identity_or_fairness_drift`。
- 新增分类与反向 infra 两项：2 tests，OK；JSONL 和 `run.json` reason 均精确匹配固定 code。
- `tests.test_proactive_eval`：32 tests，OK。

本轮未改共享 runner/M-5、Team Lens 或 readiness，按独立审查范围未重复运行 144/25/ready。未运行真实 API、Docker、
Cargo、付费操作、完整数据集或全 workspace；未创建正式 paid namespace、receipt、账本或 run/result identity。阶段 B
仍未授权。
