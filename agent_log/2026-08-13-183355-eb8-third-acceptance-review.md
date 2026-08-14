# E-B8 修复后三次验收审查（`d34d4d7`）

## 结论

**未通过，E-B8 仍为 blocked。**

`d34d4d7` 对上一轮五项问题的定点修复均已实质落地，但把“生成 v7 identity → 产出 stub receipt → 启动正式 worker”
串成真实生命周期后，仍发现 2 项 blocker；另有 1 项不影响 fail-closed、但会使 receipt 批次无法重试的 medium 问题。
这些都属于现有入口的实践正确性，不需要新增签名、可信审计、鉴权体系或统计框架。

审查覆盖 `1f288b3..d34d4d7`，并回看 E-B8 的 identity、producer、paid proxy、worker、重复与聚合生产路径。
除本日志外未修改 E-B8 实现、测试、WBS、plan 或冻结历史。

## 已确认有效的修复

1. 正式 `terminal-bench/<task>` ID 已贯通 receipt 产出、加载与 seed；路径使用完整 task ID 摘要，不再只取 leaf。
2. `just eval-b7-preflight-receipts` 与 `preflight_producer.py` 已形成真实入口；stub 与付费路径复用
   `campaign_terminal_bench_request()` 和 `project_shared_model_catalog()`；worker 在 wire canary 前一次性加载全部 receipt。
3. successor 只生成 schema v7，continuation 恒为空、prior 为 0、cap 显式传入；catalog、task/image 与 provider profile
   在写 lock 前核对；5/7/9 次重复的 run-ID 区间按真实 slot 总数校验。
4. proxy 409 已优先返回具体分区原因；双向差异触发重复、三层 assessment 与最终多数聚合未发现回退。
5. `eval/locks/`、`eval/results/`、`mydev/`、`codex-source-code/`、`eval/uv.lock` 相对 `e23d82f` 无改动，
   `multidev/` 不存在。

## 未闭合问题

### BLOCKER 1：successor 的 harness commit 形成不可满足的自引用生命周期

`generate_successor_lock()` 先要求工作树干净，并要求 comparison 中的 `eval_harness_commit` 等于当前 `HEAD`；随后它在同一
工作树新增 tracked campaign lock，并改写 tracked active pointer。由此产生两种都不可执行的状态：

- 不提交 identity：工作树已脏，`preflight_producer.main()` 和正式 worker 的 `validate_eval_harness_checkout()` 立即拒绝。
- 提交 identity：`HEAD` 从冻结的 `H` 变为 `H2`，但 lock 内仍是 `H`。producer 只检查“当前 checkout 干净”而没有把返回的
  `H2` 与 identity 比较；正式 worker 也直到 `_execute_task_slot()` 才调用
  `identity.require_declared_conditions(eval_harness_commit=H2)`。这发生在 oracle 与 wire canary 之后，因此可能先产生 wire
  费用，再以 harness drift blocked。

当前没有一种正常 Git 状态能同时满足“active v7 lock 已存在、工作树干净、HEAD 等于该 lock 生成前冻结的 HEAD”。
这使唯一 successor 入口产出的 campaign 无法进入正式 task 执行。现有回归只分别测试生成时比较和 task-slot 漂移拒绝，
没有覆盖生成后的完整生命周期。

最小修正应消除 commit 自引用，例如把 harness 身份定义为排除 campaign lock/pointer 的已提交代码投影，并在 worker 启动、
wire canary 之前核对；不应靠隐藏脏文件或手工伪造 commit 绕过。

### BLOCKER 2：stub producer 只冻结 `main`，合法 Guardian 请求必被付费门禁拒绝

`preflight_producer._terminal_sse()` 第一次响应就返回普通 assistant message，不产生 tool call；因此真实二进制的 stub 轨迹只会
发出首个 main 请求。`_requests_by_role()` 也只要求存在 `main`，`PreflightReceipt.validate()` 接受任意非空角色子集。

但正式 adapter 明确启用 `approvals_reviewer="auto_review"`，campaign profile 允许 Guardian 请求；付费 proxy 对每个实际请求都
使用 `SymmetryPreflight(require_expectation=True)`。所以只含 main 的 receipt 一旦遇到正常 Guardian review，会在预留与出站前
以 `preflight_expectation_missing` 拒绝。结果是配置中合法、且比较本来要保留的审批轨迹被设施机械截断。

现有测试恰好把缺口的两半分别固化了：

- `PreflightProducerTests.test_it_writes_one_bound_receipt_per_task` 用注入 capture 生成仅含 `main` 的成功 receipt；
- `PreflightReceiptTests.test_an_uncovered_request_is_refused_under_require_expectation` 证明未冻结的 `guardian` 必然被拒。

producer 应通过真实、受控的 stub 轨迹冻结所有付费路径允许出现的角色合同（当前为 main 与 Guardian），并让 receipt 对所需角色
集合 fail-closed；不能用人工构造 Guardian JSON 代替冻结二进制的实际请求。

### MEDIUM：多任务 receipt 产出失败后留下不可重试的半批次

`produce_preflight_receipts()` 每完成一题就立即发布最终 receipt。若后续任务不对称或执行失败，前面文件保留；再次执行从第一题
开始，`_atomic_receipt()` 又以 `preflight receipt already exists` 拒绝。单题测试只证明“当前题不对称时不写”，没有覆盖批次中途失败。

离线注入复现：两题中第二题不对称后，第一题的 `fix-git-fe7a9b10fec7.json` 已存在；把两题都改为对称后重试，立即得到
`PreflightProductionError: preflight receipt already exists`。这不造成 fail-open，但一次昂贵的双侧 Docker 预跑无法通过正式入口恢复。
采用批次成功后再发布，或对已存在且绑定/内容完全一致的 receipt 做幂等续跑即可；无需引入事务或审计平台。

## 验证记录

- focused：`tests.test_fair_comparison` 77 项通过（按仓库要求清除 ambient proxy，仅使用 127.0.0.1 loopback）。
- `just eval-lock`：通过，`Resolved 85 packages`。
- `just eval-test`：通过，`Ran 565 tests in 69.557s`，`OK`。
- `git diff --check 1f288b3..d34d4d7`：通过；受保护目录核对如上。
- 纯复现：main-only receipt 对 Guardian 得到 `preflight_expectation_missing`；两题批次第二题失败后留下一份 receipt，重试因
  `already exists` 失败；当前 clean checkout 的 harness 校验返回 `d34d4d75031727947b29a47855b3a3b55a6ee5a7`。
- 未运行 Docker、真实 API/provider、真实模型、`eval-b7-baseline`、`eval-b2-no-api` 或 oracle；未创建/激活/消费 campaign、
  ledger 或 run ID；未读取 `.env.local`，未查看 holdout 正文、solution、verifier、日志或单题结果。

审查末尾 `eval/rondo_eval/runtime_bridge.py` 出现并行未提交修改；用户确认这是另一个 Claude 在获授权运行 Docker 后形成的修复。
它不属于 `d34d4d7` 或本审查，已原样保护并排除在本日志提交之外。因此当前 worktree 在提交本日志后仍可能因该并行工作显示
dirty，不能把它误报为本次审查改动或擅自清理。

## 验收判定与最小后续

`d34d4d7` 不能作为 E-B8 闭环验收，也不应据此启动新的真实 campaign。下一轮只需窄修：

1. 解除 identity 文件与 harness commit 的自引用，并把实际 harness 条件校验前移到 wire canary 之前。
2. 让真实 stub producer 覆盖付费路径允许的 main/Guardian 角色合同，并补组合回归。
3. 让 receipt 批次可全量失败不落最终文件，或可安全幂等续跑。

不需要扩大鉴权、可信审计、数据资产证明、统计显著性或 Multi 产品设施。
