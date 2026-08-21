# Plan 049 阶段 A 独立验收

## 结论

- 审查对象：`3b34dae8ab50a72bdb883110830d8bf7c778679f`
- 验收结论：**不通过**。
- 任务目标：**失败**；阶段 A 尚未达到可安全启动真实测评的 `paid-ready` 状态。
- 阶段 B：仍未授权，并因本次 correctness findings 保持 `blocked`。本次审查没有调用真实 API、Docker、Cargo、
  本地模型或外部付费入口。

合同、共同 V2 接线、确定性槽位、Terminal-Bench 外部 verifier、Team Lens 主路径、body-free 产物和多数恢复路径
均已落地，方向正确；但下列问题会在真实阶段 B 中改变停止、重试或报告语义，不能作为非阻断尾项留到付费后处理。

## Correctness findings

### F1（高，阻断）：原则性漂移没有跨进程锁存

`eval/rondo_eval/proactive_eval/formal.py:1206-1217` 在执行前先 claim run；
`eval/rondo_eval/proactive_eval/formal.py:1267-1294` 遇到 `FormalDriftError` 或其他原则性 `FormalError` 时只向本次
调用抛错，没有写入可由下次启动识别的持久停止状态。

下次运行进入 `claimed_run_disposition` 后，零请求 claim 会被 reclaim 并重新执行同一 run；已有请求的 claim 则可能被
归档成 `infra_failed` 并进入下一个 attempt。因此 policy、工具面、产品或身份漂移在进程重启后可能被当作普通恢复，
甚至产生替代样本。这与“身份/公平合同漂移立即停止、不得以 infra 重试换样本”的硬约束冲突。

现有 `test_formal_identity_error_is_a_principled_stop` 只验证首次调用抛错；`Plan049RequestPreflight` 的 `_failed` 也只是
对象内存状态，均没有覆盖 restart/resume。

### F2（高，阻断）：固定请求上限与 budget stop 可以被新 attempt 重试

`eval/rondo_eval/proactive_eval/formal.py:943-952` 将共享预算层明确归为 budget 的
`logical_request_limit_exceeded` 和 `guardian_logical_request_limit_exceeded` 强制转换成 `FormalInfraError`；随后
`eval/rondo_eval/proactive_eval/formal.py:1269-1289` 会把它们当作 infra，最多用五个 paid attempt 重试同一槽位。

另外，`budget_stopped` 虽会结束当前调用，但不属于 `_TERMINAL`；
`eval/rondo_eval/proactive_eval/formal.py:1616-1652` 会在下一次 CLI 启动时把该槽位视为未终止并从下一 attempt 继续。
这会绕过冻结的单 run 请求/费用边界并造成选择性换样本。

最低正确语义是：固定 per-run/request/guardian 边界耗尽不得归类为 infra、不得自动换 attempt；能明确归因于被测 run
自身资源耗尽时可按冻结合同映射为有效 `product_failed`，无法安全归因或全局预算/记账触发时应 fail-closed 为停止状态。
具体内部表示由执行者选择，但 restart 后不得继续该槽位或后续槽位。

### F3（中，阻断）：真实 followup 活动会被静默计为零

Team Lens 将原生 `followup_task` 归一为 interaction kind `assign_agent_task`，见
`eval/rondo_eval/team_lens/reducer.py:80,742-758`；Plan 049 聚合器却在
`eval/rondo_eval/proactive_eval/aggregate.py:228-231` 匹配不存在的 `followup_task` kind。

因此合法 followup 在阶段 B 聚合中始终输出 `followup_count=0`，直接破坏冻结的团队协调指标。应做窄修并增加一个合法
Team View 聚合回归，不需要引入新的观测或文件系统审计。

### F4（中，阻断）：正式账本未在 Docker/密钥之前完成只读校验

`require_safe_formal_prefix` 在 `eval/rondo_eval/proactive_eval/formal.py:703-735` 只抽查 ledger 顶层身份和 run id，
没有复用预算账本的 exact schema、权限、run/request 内部状态和金额一致性校验。带额外字段或畸形内部状态的 ledger
可以通过此前缀检查。

完整账本打开/校验直到 `eval/rondo_eval/proactive_eval/paid.py:217` 才发生，而
`eval/rondo_eval/proactive_eval/paid.py:194-214` 已先取得 Docker 资源门并读取密钥。这违反 unsafe resume prefix 必须在
Docker、密钥和正式状态动作之前拒绝的合同。修复只需复用或抽出既有账本的只读校验，不需要建立第二套账本或审计系统。

### F5（低，随 F3 同批修复）：共同 V2 完整性门禁只覆盖四个工具

当前 V2 共同协作工具面包含 `spawn_agent`、`send_message`、`followup_task`、`wait_agent`、`interrupt_agent`、
`list_agents`，但 loopback、readiness 和 paid preflight 只要求其中四项，遗漏 followup 与 interrupt；loopback 结果还写入
固定要求集合，而不是实际观测集合。当前源码/既有 loopback 没有显示两侧已经发生工具面不一致，因此本项本身不是产品
偏差；但门禁不能证明其声称的完整共同工具面，且遗漏项正好包含 F3 所需指标。应窄补为六项并保存/核对实际观测投影，
允许 RONDO 额外 Team State 工具。

## 正面证据与验证

- 冻结 lock/taskset/policy 的严格字段与摘要、`terra/medium`、并发 4、共同 V2/policy/trace、两侧 frozen task/binary/
  shared catalog 绑定，以及 Codex Team State `null/not_applicable`、RONDO Team State 启用，静态接线成立。
- 旧 Terminal-Bench/M-5 路径通过 opt-in 默认值保持原行为；未发现本次抽 core 引入的直接回归。
- `git diff --check 4c0553e6944d815bfd696183e8d91ed7f24605b7..3b34dae8ab50a72bdb883110830d8bf7c778679f`
  通过。
- `tests.test_proactive_eval`：22 tests，OK（3.173s）。
- `tests.test_terminal_bench tests.test_api_budget_proxy tests.test_multi_m5`：143 tests，OK（45.579s）。
  第一次只清除了大写代理变量，localhost 被残留小写代理转成 502，得到 42 failures / 6 errors；同时清除大小写代理变量并
  显式设置 `NO_PROXY/no_proxy=127.0.0.1,localhost` 后同组全绿，判定为环境污染而非代码失败。
- 未重跑 Docker、Cargo、全 workspace、全量 eval、真实 provider 或付费命令；这些对确认本次 findings 没有必要。

## 代用户作出的决策

1. 不接受当前 `paid-ready`，不启动阶段 B；本报告提交不能作为“独立审查通过”的 commit 使用。
2. 不新开 plan 或工作树。继续在同一 Plan 049、同一 049 分支做上述窄修，保留现有公平合同、任务集、模型、顺序、
   100 USD 上限和 v4 rehearsal/loopback namespace。
3. 原则性漂移必须持久 fail-closed；清除该状态或改变冻结身份需重新审查/授权，不能由普通 resume 自动跨过。
4. 固定 run/request/guardian 资源边界不属于 infra 重试理由；全局预算、余额或不可信记账触发后停止整个 campaign。
5. 修复后只需新增针对上述四类问题的回归，并重跑 Plan 049 的 22 项与共享 runner/预算的 143 项定向门禁；无需为本轮
   验收补 Docker、Cargo、全量测试、复杂审计、签名或可信设施。
6. 现有 ignored rehearsal/loopback 资产不清理；正式 paid namespace 仍不得创建。工作树继续保留，不合并、不推送、
   不关闭，等待修复后的新 final SHA 和再次独立验收。

## 非阻断口径

- 当前 aggregate 的 `duration_ms` 是 Team Lens rollout wall time，不是 Harbor trial 总时长；正式记录保留
  `cost_usd/request_count`，aggregate 尚未复制这两个字段。阶段 B 报告应明确口径；若确需端到端 trial 时长或统一金额列，
  可在不解析正文、不增加重型观测的前提下窄补，不作为本轮额外 blocker。
