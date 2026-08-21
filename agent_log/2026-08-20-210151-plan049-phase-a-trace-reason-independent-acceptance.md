# Plan 049 阶段 A trace 原因码独立验收

日期：2026-08-20
受审提交：`9837a2c2cf74e7ee0b4fec531c03826a83df1634`
结论：**验收不通过；阶段 A 回拨为 `blocked`。**

## 审查范围与成立的修复

- 只读复核 `4cb15cc…9837a2c` 的 executor、campaign 恢复、新增回归和当前文档；未运行真实 API、Docker、Cargo、付费、全 workspace、CI 或 PR。
- 主要安全语义已修正：`COMPLETED` reward 0/1、`AGENT_FAILED`、`CANCELLED` 在 trace 缺失时会持久 `principled_stopped`，跨 ledger reopen 不再执行 a02。
- `INFRA_FAILED` 仍精确走 `FormalInfraError` 的有界重试，且不进入 trace 查找；未发现对真实 infra 语义的回归。
- 本次独立运行新增两条分类回归 2/2，并运行 `tests.test_proactive_eval` 32/32，全部通过。共享 runner/M-5 与 Team Lens 本次无代码变更，未重复运行已报告的 144/25 项测试。

## 阻断 finding

**中：新路径虽然正确停止，但持久归档会记录错误的原因。**

executor 在已解析非 infra 结果且 trace 缺失时抛出的准确原因是
`non-infra task result lacks complete trace evidence`。但 `run_formal_campaign` 的通用 `except FormalError`
把所有此类停止的 body-free `reason_code` 固定写成 `identity_or_fairness_drift`。因此初次抛错后，
`run.json`/JSONL 与后续 resume 只会声称“身份/公平漂移”，丢失实际的 trace/归因不完整分类。
新增回归只断言 outcome 与 attempt，未断言 `reason_code`。

这不会再购买替代样本，但会让阶段 B 的持久证据和恢复诊断误报停止原因，不符合 Plan §3.5
要求的原始分类保留与独立报告。这是当前窄修路径的直接正确性遗漏，不是额外审计设施需求。

## 代用户作出的决策

1. **暂不接受 `paid-ready`。** fail-closed 已经安全，但正式结果不能把 trace 缺失错报为身份/公平漂移。
2. **仅要求一个原因码窄修。** 让该原则性异常持久一个稳定、body-free 且准确的 reason（例如 `non_infra_terminal_missing_trace`），并在现有矩阵测试增加 reason 断言。具体异常类型/传递方式由执行者自主选择，无需新设施。
3. **验证保持轻量。** 修复后重跑新增分类矩阵与 `tests.test_proactive_eval` 即可；若共享文件未改，不要重跑 144/25、Docker 或全 workspace。
4. **阶段 B 仍未授权。** 不允许创建正式 paid 状态，不允许真实 API、Docker 或付费连通试探；100 USD 上限和余额确认仍待未来单独授权。
5. **保留 049 工作树。** 本次只提交本地 049 分支，不合并、不推送、不关闭或重命名。

## 最终状态

- 验收：**不通过**。
- 任务目标：**失败**（阶段 A 尚未实现可准确持久停止分类的 `paid-ready` 预期）。
- 当前分类：`blocked`。
- 正式 paid namespace：不存在。
