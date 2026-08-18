# Plan 044 / Multi M-5 付费入口独立验收审查

日期：2026-08-18 ｜ 工作树 `worktree-044-multi-m5-real-workflow-and-nondegradation`
｜ 审查对象：`848a414`（付费入口接线）+ `1c30098`（门 2 `$8` cap 修复）
｜ 本轮无真实 API、无 Docker、无费用

## 结论

**验收通过（经审查者窄修后）。** 两个付费缺口的实现方向、授权门与证据分区都正确；但预算这一层有三处
会在真花钱时才暴露的缺陷，已在本轮就地修好并各钉一条反向回归。M-5 仍**未通过**，真实运行未开始。

## 一、复核确认无误的部分

- **授权门确实前置**。`gate1-paid` / `gate2-real` 都先比对冻结口令再 `load_provider_secret`，
  无口令时退出 78 且不碰 `.env.local`；`just` 两条配方是纯 stub，永不转发口令。
- **密钥不落盘**。捕获代理只见预算代理的 `downstream_api_key`，真实 key 只在预算代理内存里；
  `requests.jsonl` 只有请求正文。
- **`$8`/`$24` `ensure_run` 冲突的修复是对的**。`_register_run` 在 run 已存在且 cap 不同时抛
  `ApiBudgetProxyError`，代理原先用默认 `$24` 覆写编排器登记的 `$8`，第一槽必挂在 Harbor 之前。
  新增的 `run_cap_usd` 参数与两处调用点一致，向后兼容（默认 `None` 保持旧行为）。
- **证据分区没有被绕过**。`run_light_interleaved` 三条互斥断言（只有 TB 执行器能写 `real_api`、
  TB 执行器不能写 fake、脚本执行器不能冒充）成立；`outcomes_by_task` 只吸收
  `counts_as_effective is True` 的行。
- **门 2 没有套 v7 campaign**：`TerminalBenchRequest` 无 campaign id、无 preflight receipt，
  走既有 adapters / `prepare_terminal_bench_run` / Harbor / `parse_single_task_result`。
- **文档没有夸大**。WBS / WBS-COMPLETED / 方向 3 子 WBS 都明确写了"仍锁在授权门后""不是 M-5 通过"。
- 本批次**没有动 `multidev/`**，无 Rust 回归面，因此未跑 Rust 门禁。
- WBS-COMPLETED 里"既有两项 Local 导入失败与本任务无关"属实：
  `test_l6_b10333_pair` / `test_local_m4_holdout_anchor` 都是 `No module named 'eval'`，与 M-5 无关。

## 二、发现的缺陷与修复

三处都出在同一个盲点：**预算代理对耗尽的 run 是"就地回 429"，不是向 Python 调用方抛异常**，
于是被砍断的运行看起来跟"模型自己放弃"一模一样。

### F1（严重）门 1 的可用额度只有 `$8`，正好等于冻结的点估计

`reserve()` 对 main 角色要同时校验自身预留和 Guardian 附加容量，所以一个 run 的可用花费是
`cap - 2 × reservation`，不是 `cap`。原值 `$24 - 2 × $8 = $8`，而运行合同把门 1 建模成
**每次尝试约 `$8`** —— 余量是 1.0 倍，正常跑完一次就会被自己的预算掐断。已用真实账本实测：
`$8` 预留下第 21 个请求触发 `BudgetCapacityExhausted`，累计花费 `$8.19`。

**修复**：`GATE1_REQUEST_RESERVATION_USD` `$8` → `$4`，可用额度回到 `$16`（点估计的 2 倍）；
`$4` 仍覆盖最坏的现实单轮（272k 输入 + 32k 输出 ≈ `$2.32`），不会反过来触发
`usage_cost_exceeded_reservation`。门 2 的 `$8 - 2 × $2 = $4` 相对建模的 `$1.35` 有约 3 倍余量，
维持原值不动。

### F2（严重）预算掐断被记成产品失败

门 1 会落 `agent_failed`（且不重试，因为只对 `infra_failed` 重试）；门 2 更糟 ——
落 `agent_failed` 且 `counts_as_effective=True`，直接喂给退化判据。Multi 单次成本被建模成 Codex 的
3 倍，**恰恰是更容易先撞上单次上限的一侧**，等于给"稳定单向退化"这个结论加了一个系统性偏向。
这违反硬约束 7（基础设施失败不计入有效结果）与 9（诚实记录）。
另外 `_slot_outcome` 里那条 `parsed.outcome is BUDGET_STOPPED` 分支是死代码 ——
`parse_single_task_result` 只会返回 completed / agent_failed / infra_failed / cancelled。

**修复**：新增 `budget.run_stop_reason(ledger, run_id)`，读账本的 `stopped` / `stop_reason`。
门 1 在归档前探测，落 `budget_stopped` + `stop_reason`（`passed=False`，不重试——重试只会多花钱）；
已经拿到完整证据的运行不因收尾时的掐断被抹掉。门 2 在每槽执行后探测，落 `budget_stopped` +
`counts_as_effective=False` 并立即停批，该观察因此进不了退化判据。

### F3（次要）共享账本的 run 槽位没给门 1 留位置

两道门用同一个 `budget-ledger`，`open_phase_b_ledger` 却按 `60 + 12 = 72` 断言槽位数，
没算门 1 的 3 次尝试。最坏合法路径下门 2 会在第 69 槽被
`benchmark run limit is exhausted` 截断。

**修复**：槽位数改为 `60 + 12 + workflow.max_attempts = 75`，`$120` 批次硬上限不变。

## 三、验收

- `tests.test_multi_m5` + `tests.test_multi_m5_exec` + `tests.test_api_budget_proxy`
  + `tests.test_terminal_bench` + `tests.test_terminal_bench_results` + `tests.test_binary_freeze`：
  **237/237**（含冻结二进制彩排）。
- 新增 4 条回归（`MultiM5BudgetStopHonestyTests`），**已逐条确认在修复前失败**：
  门 1 额度实测 `$8.19 < $16`、门 2 掐断记成 `agent_failed`、槽位 `72 != 75`、门 1 掐断记成 `agent_failed`。
- `just eval-lock` 通过。
- 未跑 Rust（本批次未动 `multidev/`）、未跑 Docker、未调真实 API、未产生费用。

## 四、代用户做出的决策

| 项 | 决策 | 理由 |
|---|---|---|
| 三处缺陷是否阻断验收 | **不阻断，但必须先修**；已由审查者就地窄修并补回归 | 都是花钱之后才会暴露的问题，改动面小，留到阶段 B 发现的代价是真金白银 + 一次污染的退化结论 |
| 门 1 单次预留取值 | `$4`（可用额度 `$16` = 点估计 2 倍） | 既给正常运行留 2 倍余量，又高于最坏现实单轮成本，不会触发预留超支停机 |
| 门 2 预留/上限是否跟着改 | **不改**，维持 `$2` / `$8` | 可用 `$4` 对建模的 `$1.35` 已有约 3 倍余量，没必要动 |
| 是否顺手把 `$120` 硬上限或运行合同改掉 | **不改** | 合同已冻结；三处修复都只动实现常量与分类，不碰锁文件 |
| 门 1 掐断后是否重试 | **不重试**，直接落 `budget_stopped` 收尾 | 预算已经不够，重试只会继续花钱，且不会改变结论 |
| 阶段 B 真实付费 / Docker 授权 | **不代批，留给用户** | 属于真实花钱与不可逆外部操作，超出可代决策的范围；授权清单见 ExecPlan §6 |

## 五、边界

未合并 `main`、未推送、未删改 worktree。真实 API、Docker 与付费仍未授权、未执行。
**不得**表述为 M-5 通过、门 1 通过或未见退化。
