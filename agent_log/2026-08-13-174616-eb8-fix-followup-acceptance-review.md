# E-B8 修复后二次验收审查（429acfb）

## 结论

**未通过，E-B8 仍为 blocked，不应把 `429acfb` 合并为“设施已闭合”。**

第一轮四项问题中，运行时 receipt 消费接线、successor 只产 v7、运行条件声明等值校验、反方向差异触发重复均已有实质修复；
但沿正式 campaign 入口继续追踪后，发现 3 项 blocker、1 项 high 和 1 项 medium。最直接的问题是正式 TB task ID 无法通过 receipt
自身校验，因此当前没有任何正式任务能生成或消费 preflight receipt。测试全部通过只说明现有 fixture 没有覆盖这些生产形状。

审查范围为 `c970cbb..429acfb` 的修复差异，并回看 `e23d82f..429acfb` 的完整 E-B8 设施路径。未修改实现、WBS 或冻结历史。

## 已确认修复有效的部分

1. `baseline_cli._execute_task_slot()` 已把 receipt 传入 `run_budgeted_terminal_bench()`；`live.py` 对 v7 缺 receipt 拒绝，
   并用 `SymmetryPreflight(require_expectation=True)` 预置合同，首个实际 task 请求不再能自行定义期望。
2. `eval-b7-next-identity` 已强制 `--comparison-contract`，生成 schema v7；缺失/不合法的 comparison 块在 registry 与 lock 写入前失败。
3. lock 加载时已把 deadline、provider profile、catalog SHA、task/image 与 campaign 自身字段等值校验；实际 harness commit 在 task
   执行入口校验；catalog identity 的字段形状比第一版严格。
4. v7 的条件加跑已改为任一方向的 A/B 差异触发，assessment 与执行器一致；方向性兜底仍保持单向，符合当前 WBS。

## 未闭合问题

### BLOCKER 1：正式 task ID 使 receipt 产出与消费必然失败

- `eval/rondo_eval/fair_comparison.py:22` 的 `_TASK_ID` 只允许 `[a-z0-9._-]`，不允许 `/`。
- 正式 canary task ID 是 `terminal-bench/fix-git` 这类带 `/` 的 ID；`baseline_cli.py:1820-1822` 和
  `live.py` 都使用完整 `campaign_task.task_id` 绑定 receipt。
- 新测试 `PreflightReceiptTests` 使用的是不存在于正式 catalog 的 `terminal-bench-fix-git`，因此绕开了生产形状。

纯函数复现：用 `task_id="terminal-bench/fix-git"` 调用 `preflight_receipt_from_stub_run()`，在
`SymmetryPreflight.register()` 直接得到 `FairComparisonError: preflight task id is invalid`。即使人工写 receipt，
`PreflightReceipt.validate()` 与运行时 seed 仍会拒绝同一 ID。

这不是安全上的 fail-open，而是设施不可用：当前无法为任何正式 TB task 形成可消费 receipt。

### BLOCKER 2：仍没有实际双侧 stub 产出链，而且付费 wire canary 先于 receipt 门禁

- `preflight_receipt_from_stub_run()`（`fair_comparison.py:586-634`）只接收调用者提供的两个 request dict 并返回对象；生产代码无调用，
  没有驱动两侧冻结 binary、捕获请求并原子写到 `eval-data/campaigns/<id>/preflight/` 的入口。
- `just eval-preflight-symmetry` 仍只是读取两份任意 JSON 后比较。`preflight_cli.py:83` 只把
  `type(NoUpstreamTransport()).__name__` 写进输出；该 transport 没有安装到任何实际请求链。
  `stub_preflight()` 的注释称返回对象“carries a transport”，实际 `SymmetryPreflight` 没有 transport 字段。
- 正式 worker 在 `baseline_cli.py:471-504` 先进入 Oracle/状态推进，随后在 `:554-561` 调用真实
  `run_model_cli_campaign()` wire canary；receipt 直到具体 task slot 的 `:2337` 才加载。

因此当前一方面无法通过仓库入口生成被声称为“双侧 frozen binary stub 证明”的 receipt，另一方面缺失/错误 receipt 会在 wire canary
已可能产生真实费用后才被发现。这仍不满足“任何真实上游请求可能发出前”的硬门。所需修正是窄的 campaign preflight producer +
启动前全 task receipt 校验，不需要扩大为签名、可信审计或鉴权系统。

### BLOCKER 3：唯一 successor 入口会生成带旧结果的、实际不可执行的 v7 identity

- `baseline_identity.py:225-236` 无条件把 `_successor_continuation(paths, predecessor)` 写入 v7。
  当前 v22 lock 实际包含 25 条 continuation。
- 同一生成器在 `:240-250` 又从 v7 `selected_profile` 删除两个旧 Codex-only catalog 字段。
- 执行期 `_continuation_records()` 在 `baseline_cli.py:2812-2824` 要求 continuation source 的完整
  `selected_profile == identity.selected_profile`，所以 v22 source 与新 v7 必然不等，campaign 会以
  `continued execution contract drifted` blocked。
- 即使把这处等值判断放宽，也不能复用 v1-v22 结果：这些结果没有 v7 的共享 catalog、stub receipt、harness commit 与任务交错条件，
  把它们纳入 v7 聚合会直接破坏公平比较合同。

相邻问题也在同一入口：它仍通过 `required_successor_prior()` 继承 v22 的 `1136.113528 USD` prior，并固定旧 1600 USD cap，
与交接中“新 IDs、独立 cap、单独授权”不一致；且生成前 `_validate_frozen_inputs()` 校验的是 predecessor，不是传入的新 catalog/harness
事实。格式正确但实际不存在的 source commit/catalog identity 可被写成 active lock，直到执行（且可能在 wire canary 后）才失败。

v7 应从公平合同上 fresh 开始：不得继承 v1-v22 continuation；新授权 cap/prior 应与历史 campaign 分离；新 comparison 的真实
catalog/harness 条件应在写 lock/激活前用现有纯校验原语核对。

### HIGH：重复数可变后，run-ID 碰撞校验仍固定为 321 slots

`RepeatContract` 支持 3/5/7/9 次，但 `validate_successor_run_range()`（`baseline_identity.py:577-593`）始终只检查
`range(CAMPAIGN_MAX_RUNS)`，即 321 个 ID；生成器稍后才按重复数把 `max_run_slots` 扩到真实值。

纯函数复现中，5 次重复得到 481 slots；候选 base `500000001` 与从 `500000400` 开始的历史区间在尾部重叠，当前 validator
仍返回成功（`validator_admitted_overlap True`）。这会让合法 v7 lock 的后 160 个 run ID 与历史冲突。

校验函数应接收本次由冻结 repeat contract 计算出的精确 slot 数，并在写 lock 前检查完整区间。

### MEDIUM：代理实际返回的不是分区级原因码

`SymmetryPreflight.register()` 对 tool/instructions/schema 漂移产生
`("frozen_contract_asymmetry", "task_independent_<partition>_differs")`，但
`api_budget_proxy._preflight_reason()`（`:149-157`）取第一个合法字符串，所以 HTTP 409 只返回
`frozen_contract_asymmetry`。纯函数复现输出正是该值，而不是 `task_independent_tool_specs_differs`。

这保持 fail-closed，但不满足 WBS/验收所写的分区级、可归因失败原因。应优先返回具体 partition reason（scope 可另保留在内部元数据），
无需新增审计体系。

## 验证结果

- `just eval-lock`：通过。
- `just eval-test`：通过，`Ran 552 tests in 68.661s`，`OK`。
- `git diff --check`：通过（写本日志前后均检查）。
- 相对 `e23d82f`，`eval/locks/`、`eval/results/`、`mydev/`、`codex-source-code/`、`eval/uv.lock` 无差异；
  `multidev/` 不存在。
- 纯复现：正式 task ID receipt 被拒；v22 continuation 为 25 条且含两个旧 catalog profile 字段；5-repeat 的 481-slot
  区间碰撞被错误放行；代理只发通用 preflight 原因。
- 未运行 Docker、真实 API、真实模型、`eval-b7-baseline` 或 `eval-b2-no-api`；未创建/激活/消费 campaign、ledger 或 run ID；
  未读取 `.env.local` 或 holdout 正文/solution/verifier/单题日志与结果。

## 验收判定与最小后续

`429acfb` 不能作为 E-B8 闭环验收。下一轮只需围绕上述生产路径补窄修复与入口级回归：

1. 使用正式带 `/` 的 task ID 覆盖 receipt 产出、加载、seed 和代理首请求。
2. 提供真正驱动双侧 frozen binary 的无上游 stub receipt 产出入口，并在任何 wire/API 前一次性验证全 task receipts。
3. v7 successor 清空历史 continuation，按新授权冻结独立预算，并在激活前验证新 comparison 的实际事实。
4. run-ID 区间使用动态 slot 总数；HTTP 409 返回具体分区原因。

不需要引入签名、角色鉴权、可信审计平台或统计显著性框架，也不应提前接入 Multi 产品线。
