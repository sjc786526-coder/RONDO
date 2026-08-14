# E-B8 公平比较设施独立验收（提交 `e55a4ac`）

## 审查结论

**不通过，结论为 blocked。**

本提交完成了若干正确的底层原语，但 E-B8 尚未形成可用于下一次正式 campaign 的闭环。主要问题不是需要扩大鉴权、
可信或审计体系，而是新合同没有接入现有正式执行入口：当前 `eval-b7-next-identity` 仍会生成 schema v6，实际付费 runner
也没有启用请求对称 preflight。即使绕过生成器手工制作 v7 lock，运行条件与 catalog identity 的部分字段仍只是可解析的
声明，没有与真实执行事实完成机械绑定。因此不能接受 WBS 中“工作包 1 已完成”以及后续付费比较已解锁的表述。

审查仅新增本日志；未修改实现、测试、WBS、冻结历史或产品代码。

## 阻塞问题

### 1. [BLOCKER] 正式 paid runner 没有接入请求对称 preflight，且现有 registry 会先放行第一侧

证据：

- `eval/rondo_eval/terminal_bench/live.py:145-166` 构造正式 `LoopbackResponsesProxy` 时，没有传入
  `symmetry_preflight`、`preflight_side` 或 `preflight_task_id`。全仓检索这些关键字，生产代码只有代理自身的参数定义；
  实际传参只出现在 `eval/tests/test_fair_comparison.py:318-320`。
- `SymmetryPreflight.register()` 在某个 `(task_id, role)` 首次出现时只保存摘要并正常返回
  （`fair_comparison.py:284-310`）；`allow_upstream=False` 只被保存和读取，没有参与任何转发判定。
- 代理测试先在内存中人工注册 RONDO 请求，再只测试 Codex 代理。其“对称”用例明确断言 transport 被打开一次
  （`test_fair_comparison.py:365-370`）。这证明该门只能在第二侧到达时发现跨侧差异，不能阻止第一侧先出站。
- `preflight_cli.py` 只是读取调用者提供的两个 JSON 文件并比较。它没有驱动冻结的两个二进制向 stub endpoint 发请求，
  也没有把 `NoUpstreamTransport` 安装到任何实际请求链；输出中的 transport 名称只是新建对象后取类名。
- 冻结归因报告已经明确指出这种设计不成立：若等第二侧到达再比较，第一侧已经可能产生费用；要求是两侧二进制先在
  本地 stub 上零成本生成请求，再允许任何真实上游发送
  （`doc/research/plan020-b7-canary-baseline-failure-attribution.md:275-292`）。

影响：

- 不对称请求仍可由第一侧发送并计费；第二侧最多只能事后阻断。
- 正式 campaign 完全不传 preflight 时，两侧都会照常发送，schema v7 lock 中的
  `task_independent_request_preflight=required_before_upstream` 只是声明。
- 当前离线 CLI 比较任意外部文件，不能证明文件确实来自冻结二进制、同一 task、同一 campaign 条件。

最小修正方向：复用现有 stub/no-upstream 运行能力，在 paid slot 之前由两侧真实 adapter/binary 生成并冻结同题稳定分区，
两侧均通过后才开放 paid runner；正式 runner 还应核验该预检结果与 task/side/role/campaign identity 的绑定。无需新增大型
审计系统。

### 2. [BLOCKER] 唯一公开的 successor identity 入口仍硬编码生成 schema v6

证据：

- `eval/rondo_eval/terminal_bench/baseline_identity.py:200-217` 把新 lock 的 `schema_version` 写死为 `6`，并调用
  `campaign_baseline_contract(6)`；该生成路径不会写 `comparison` 块，也不会冻结重复合同、运行条件、共享 catalog identity
  或产品身份。
- 根 `justfile` 的 `eval-b7-next-identity` 仍直接调用这个生成器。
- 新增测试只用 `dataclasses.replace()` 在内存中伪造 v7 identity；没有覆盖真正的 identity 生成/注册入口。

影响：用户按仓库提供的正式命令创建下一 campaign 时，会得到一个合法可加载且可激活的历史 schema v6 campaign，绕过
E-B8 的全部新门禁。它直接违反“重复数和聚合公式未冻结前拒绝建立正式 campaign”以及“新 campaign 必须使用 schema v7”。

最小修正方向：让 successor 生成器只生成完整合法的 v7，要求调用方显式提供 pilot 后冻结的重复合同及其余 comparison
事实；在任何写 lock、注册或激活之前完成纯校验。补入口级回归，证明无法再生成或激活 v6 successor。

### 3. [HIGH] `ComparisonConditions` 和部分 catalog identity 没有绑定到正式执行事实

证据：

- `ComparisonConditions.require_match()` 的全仓调用只存在于测试；正式加载、调度和执行代码从未调用。
- `load_campaign_identity_path()` 对 v7 只触发各 accessor 的解析
  （`baseline.py:1457-1465`），未把 `comparison_conditions` 与 lock/运行时已有的权威事实互相核对：
  `validate_eval_harness_checkout()` 得到的当前 eval harness commit、`baseline.upstream_timeout_seconds`、
  `selected_profile.provider_profile_sha256`、canary task/image mapping。
- `ComparisonConditions.validate()` 不检查 image digest 的格式；`_parse_comparison_block()` 对 catalog identity 也只检查
  key 集合、两个 side 名称与 artifact SHA 的形状，没有在 lock 建立/加载阶段检查 projection algorithm/version、model、
  override entry、source commit/path/blob ID 格式及两侧 blob 一致性（`baseline.py:1494-1538`）。
- 纯函数复现把 harness commit 改为另一合法 commit、task/image 改为 `unrelated-task: not-a-digest`，同时把 catalog
  projection algorithm/version 和一个 source commit 改成非法值，`_parse_comparison_block(..., schema_version=7)` 仍返回
  成功（本次复现输出：`malformed_lock_block_accepted: true`）。

补充判断：现有 runner 的其他旧字段确实会分别检查 provider、task、timeout 和 harness，这避免了一部分运行时漂移；问题在于
新 `comparison` 块可以与这些真实事实互相矛盾，且 `require_match()` 所宣称的可归因拒绝从不发生。结果会携带一份看似冻结、
实际未生效的比较合同。

最小修正方向：在 v7 identity 建立/加载且任何外部动作之前，从现有权威字段构造唯一的实际 conditions，并与
`comparison_conditions` 做一次等值校验；catalog identity 同样复用 `load_shared_model_catalog().identity()` 的严格校验。
不需要另建可信或审计层。

### 4. [HIGH] 条件重复只覆盖 `RONDO fail / Codex pass`，与当前 WBS 的双向差异合同不一致

证据：

- `baseline.py:1948-1953` 和 `baseline_cli.py:2069-2074` 都只把 RONDO fail、Codex pass 设为 trigger。
- 当前权威 WBS 写的是“对一侧 pass、另一侧 fail 的任务使用预冻结重复”
  （`doc/WBS.md:183-186`），并未把另一方向排除；E-B8 合同也要求双方同题使用相同的预冻结重复合同。
- 纯函数复现中，同一 task 的 `ab-rondo-1=pass`、`ab-codex-1=fail`，再令 A/A 的 `sigma=1`，最终得到
  `status=passed`、`delta=1`、`conditional_tasks=[]`、三个 layer 全部 passed。也就是说正式差异被 `sigma` 吸收时，
  该 task 完全绕过声明为 3 次的重复合同。

影响：`repeats_per_task` 名称和 WBS 表述暗示所有被比较的差异题都进入冻结多数聚合，实际却只有历史“方向性回退”一类进入；
cross-side `delta` 因而混合了部分任务的三次多数结果和部分任务的单次结果。

最小修正方向：若当前策略确实只想复核 RONDO 回退，应在 lock 中明确冻结 detection target，并让 WBS/字段命名与聚合公式
精确表达这一点；若维持当前 WBS 的双向差异合同，则两种 pass/fail 分叉都应按同一重复规则进入最终聚合。两者择一，不需要
引入统计显著性框架。

## 已确认正确或基本正确的部分

- `load_shared_model_catalog()` 从上游/RONDO 指定 commit 读取固定路径与 blob，要求两个 blob ID 和 bytes 同时相等，
  保留完整 catalog 并只给 main entry 写审批 override；adapter/runner 能向两侧交付同一 artifact。相关单测通过。
- v7 的基础 slot 顺序确实按 task-major 交错；v1-v6 仍走 round-major 分支，未发现冻结 lock/result 被修改。
- `RepeatContract` 对奇数、至少 3、严格多数和精确样本数的纯函数校验有效；layered assessment 的输出结构与
  条件结果参与 `effective_delta` 的已触发路径有效。
- `Product` 与 `Side` 已做窄分离，未创建 `multidev/`，没有夹带工作包 2 产品实现。
- 提交没有修改 `mydev/`、`codex-source-code/`、`eval/locks/`、`eval/results/` 或依赖锁。

这些局部成果可以保留，但不足以支持“E-B8 已闭合”的整体结论。

## 验证记录

- `just eval-lock`：通过，`Resolved 85 packages`。
- `just eval-test`：通过，`Ran 532 tests in 68.334s`，`OK`。
- `git diff --check e23d82f..e55a4ac`：通过。
- 静态接线检查：正式 `run_budgeted_terminal_bench()` 未传 preflight；`ComparisonConditions.require_match()` 无生产调用；
  successor generator 固定 schema v6。
- 两个纯 Python、`-B`、不落盘复现：
  1. 非法/矛盾的 v7 comparison/catalog 声明仍被 `_parse_comparison_block()` 接受；
  2. `RONDO pass / Codex fail` 在 `sigma=1` 时不触发重复且 assessment 整体 passed。
- 未运行：任何真实 API/provider、Docker、真实本地模型、`eval-b7-baseline`、`eval-b2-no-api`、
  `eval-b3-oracle-no-api`；未读取 `.env.local`，未查看 holdout 内容，未创建 campaign/ledger/run ID。

## 交付建议

在上述 1-3 三项阻塞问题修复并补入口级离线回归之前，不应合并本提交，也不应把 WBS 推进到工作包 2；第 4 项需先按现行
WBS 或明确的新策略统一语义。修正仍可保持为现有模块内的窄接线和合同校验，不需要扩大成鉴权、可信审计或统计平台。
