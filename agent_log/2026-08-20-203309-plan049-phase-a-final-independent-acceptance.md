# Plan 049 阶段 A 最终独立验收

日期：2026-08-20
受审提交：`a30715de75240a9d61f0e8702e942ca7b90fc53e`
结论：**验收不通过；阶段 A 仍为 `blocked`，未达到 `paid-ready`。**

## 范围与正面证据

- 只读复核 `9e354aa…a30715d` 的正式执行、恢复、公平性和聚合路径；未运行真实 API、Docker、Cargo、全 workspace、CI 或 PR。
- 先前五项 finding 的整改成立：原则性/预算停止持久化、request/guardian 上限分类、followup 归一统计、Docker/密钥前 exact ledger 校验、六项共同 V2 与八项 Team State 差值门禁均已实现。
- `phase-a-loopback-v5` 实际投影为 Codex 14 项工具，RONDO 为同 14 项加冻结的 8 项 Team State；readiness 在 v4 rehearsal + v5 loopback 上返回 `offline-evidence-ready` 和 26 runs。
- 本次独立轻量回归：`tests.test_proactive_eval tests.test_team_lens` 55/55，`tests.test_terminal_bench tests.test_api_budget_proxy tests.test_multi_m5` 144/144；子审查的 8 项恢复/预算定向测试与 2 项 followup/readiness 定向测试均通过。

## 阻断 finding

**高：已明确的产品失败在 trace 缺失时被误归为 infra，并购买替代 attempt。**

`Plan049TerminalBenchExecutor.execute` 已从 Harbor 解析到 `AGENT_FAILED`/`CANCELLED` 后，后续 `find_trace_bundle`
抛出的 `TraceError` 仍被统一转成 `FormalInfraError`；campaign 遂将该 attempt 记为无效
`infra_failed` 并进入下一 attempt。最小 fake/mock 复现在首槽得到：

```text
core_calls=7
[(1, "infra_failed", false), (2, "product_failed", true)]
```

即六个固定 pilot run 之外，对同一首槽又购买了替代样本。这违反 Plan §3.3/§3.5 对“产品崩溃/
协议失败不得伪装为 infra”、“完全缺 trace 须先判因”和“不得选择性重跑”的公平合同。
现有新测试只覆盖“request-limit + missing trace”，未覆盖普通产品终态后 trace 缺失。

## 代用户作出的决策

1. **不接受 `paid-ready` 结论。** 该缺口可直接改变阶段 B 的有效样本，属于 correctness 与公平性边界，不是可留待运行时观察的低风险项。
2. **只要求窄修，不建新设施。** 已解析为产品失败后又缺 trace/归因不完整时，必须持久 fail-closed 并禁止 attempt 2；只有独立证据确认为 collector/infra 故障时才可 infra retry。补一条 executor + campaign 跨重启定向回归即可。具体代码路线由执行者自主选择。
3. **阶段 B 继续未授权。** 不允许创建 paid receipt/ledger/run identity，不允许真实 API、Docker 或付费连通试探；`100 USD` 上限和余额确认仍是未来单独授权门。
4. **不扩大验证。** 此轮结论不需要 Docker、全数据集或全 workspace 来加固；修复后重跑新增回归、Plan 049 定向组和受影响的共享路径即可重新验收。
5. **保留 049 工作树。** 本次只提交本地 049 分支；不合并、不推送、不关闭或重命名工作树/分支。

## 最终状态

- 验收：**不通过**。
- 任务目标：**失败**（阶段 A 尚未实现可安全进入付费 pilot 的 `paid-ready` 预期）。
- 当前分类：`blocked`。
- 正式 paid namespace：不存在。
