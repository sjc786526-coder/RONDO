# Plan 049 阶段 A 最终验收整改

## 范围与结论

- 独立报告的五项 correctness finding 均经源码与临时状态复现确认，未采纳“尾项”降级处理。
- 在同一 049 合同和共同 eval 层完成窄修；未改变任务集、模型/effort、并发、顺序、100 USD 硬上限、产品语义或
  Team State 语义。
- 整改代码提交 `9e354aa8794c07186ede56689487c17d7a774ea5` 已由全新上下文的独立审查者验收通过；阶段 A 结论恢复为
  `paid-ready`。阶段 B、真实 API、Docker 和费用仍未授权。

## 实质修改

- 正式记录新增非有效 `principled_stopped` campaign barrier；`budget_stopped` 同样成为重启 barrier。run marker 先于
  JSONL append 的崩溃窗口也会在 Docker/密钥前识别，不再把公平漂移或预算停止换成新 attempt。
- 两种 run-local 请求上限仅在无 infra taint、Terminal-Bench 结果与 trace/preflight 完整时归为有效
  `product_failed`；缺失或冲突证据持久停止。pre-commit 审查发现的 `TraceError` 逸出和 settled 检查点写失败路径均已
  补回归并关闭。
- followup 指标改按 Team Lens 归一 kind `assign_agent_task` 统计。
- 从共享预算账本抽出无锁、无创建、无恢复写入的 exact 只读 loader；正式 prefix 在 Docker gate 和密钥访问前复用同一
  schema/权限/内部状态/金额校验。
- common V2 单一来源固定六项协作工具。loopback schema v2 保存实际工具投影，并要求 RONDO 去除精确八项 Team State
  工具后与 Codex 相等；paid preflight 与 readiness 同步执行该合同。

## 验证

- `tests.test_proactive_eval`：30 tests，OK。
- `tests.test_terminal_bench tests.test_api_budget_proxy tests.test_multi_m5`：144 tests，OK（原 143 项加一项纯只读 ledger
  loader 回归）。
- `tests.test_team_lens`：25 tests，OK。
- `just eval-plan049-loopback phase-a-loopback-v5`：exit 0；Codex 实际 14 项工具，RONDO 为同 14 项加八项 Team State；
  summary SHA-256 为 `f1753e710b2683ea001f4cb78c102460be3e6c965f6f5ea65deb20759161e897`。
- `just eval-plan049-ready phase-a-acceptance-v4 phase-a-loopback-v5`：exit 0，26 runs，既有 aggregate SHA-256
  `d27b32576fe268476c7736e067f6534ea62b1a730063f807e274a9b55e0d887c` 保持有效。
- 三个 focused 只读 pre-commit review 分别复核 F1/F2、F3/F5 和 F4；发现的 limit+missing-trace、settled 检查点写失败
  与未归档 stop-marker 窗口已修复，最终结论均为 PASS。
- 最终独立审查者在 clean `9e354aa…` 上复跑 30/144/25 项门禁与 v4 rehearsal + v5 loopback readiness，结果一致，
  未发现 correctness blocker。

未运行 Docker、Cargo、真实 provider/API、本地模型、付费任务、完整数据集或全 workspace；未创建正式 paid
namespace、receipt、账本或 run/result identity。第一次 `just` 因受限环境不能写 `/run/user/1000` 退出 1，获得仅用于
离线 recipe 临时脚本的宿主执行权限后重跑成功；没有 Docker 或外部服务交互。
