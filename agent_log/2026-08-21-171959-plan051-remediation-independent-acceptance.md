# Plan 051 整改独立验收

日期：2026-08-21

结论：**验收不通过；任务目标失败。** 首次 schema v7 正式 v28 结果仍然有效且无需重跑，但“正式启动后自动运行至终态并完成收口”的稳定重跑入口仍有两个窄的功能性阻断，因此 Plan 051 的第二个目标尚未完成。

## 阻断项

1. **P1：`run` / `resume` 到达正式终态后不会闭合任务预算或退役 active pointer。**
   `formal_canary.py:441-450` 直接返回 `baseline_main()` 的终态退出码；预算闭合和 pointer retirement 只存在于随后必须另行调用的 `finalize` 路径（`formal_canary.py:451-497`）。因此一次已经授权的 `run` / `resume` 即使返回 passed/0 或 failed/2，仍会留下 active envelope 和 active pointer，违背稳定入口“一次正式启动持续到终态并安全收口”的合同，也会重新出现此前已经修复过的 active pointer 残留。现有 failed 回归只覆盖显式 `finalize`，没有覆盖 `run` / `resume`。

   建议保持窄修：复用同一个终态收口函数，让 `run` / `resume` 在 `baseline_main()` 返回 0 或 2 时立即核验终态、闭合 envelope、退役 pointer，并保留原退出码；`finalize` 继续作为进程中断后的幂等恢复入口。补 passed/failed 的入口级定向回归即可，可采用等价且证据更充分的实现。

2. **P1：blocked 终态会被相对基线发布器错误地转成异常退出。**
   `_write_aggregate()` 对所有 schema v7 状态无条件调用相对基线写入（`baseline_cli.py:2731-2745`），但 `_formal_baseline_metrics()` 只接受 passed/failed。设施故障进入 blocked 的现有路径会以 `assessment=None` 调用 `_write_aggregate()`（例如 `baseline_cli.py:688-707`），先写 aggregate/public baseline，随后在 comparison 中抛错，导致 worker 返回异常/1，而不是合同定义的 blocked/3，破坏无人值守 successor 收口。

   建议保持窄修：只为 passed/failed 生成相对正式基线，blocked 仍按原合同归档并返回 3；补一条 blocked aggregate 不触发 comparison 的定向回归即可。无需为此增加新的审计或调度设施。

## 已确认正确的部分

- 新 Local commit/manifest、campaign/batch、价格日期和独立 task-budget ID/cap 已成为显式输入；新预算 envelope 按 ID 隔离，已关闭的 Plan 051 envelope 不会被重开或覆盖。
- 显式 `finalize` 对 passed/failed 的 envelope 闭合和 pointer retirement 正确，failed 保留退出码 2。
- v28 lock、公开 baseline 和 raw runs 未被整改改写；新增 comparison 是独立文件且可离线幂等重入。首次 v28 正式结果仍为有效基线，不允许也不需要重跑。
- 默认 `just eval-plan051` 返回 `idle`、`active_lock=null`、`paid_requests_sent=0`，不会意外发起付费请求。
- execution 和 results worktree 在验收开始及定向验证后均保持干净；主分支未合并、未推送、分支未归档。

## 定向验证

- 任务预算、统一入口、新 identity/budget 与相对比较相关的 27 项无 API 单测通过。
- 默认统一入口只读状态检查通过。
- 两个实现阻断均由控制流直接复现确认；当前测试集未覆盖上述 `run`/`resume` 自动收口和 blocked 比较分支。
- 一次较宽的本地测试尝试受宿主代理干扰，3 个 loopback HTTP 用例得到代理 502；去除代理后运行与本次整改直接相关的纯本地子集 27/27 通过。该环境现象不计为产品 finding。
- 未运行 Docker、Cargo、真实 API、全 workspace、CI/PR、validation、holdout、本地模型或训练。

## 代用户作出的决策

- 保留并认可已冻结的主模型 Terra/medium、Guardian Terra/low 合同；执行者说明其会话内存在用户直接修订，且上一轮审查已经代表用户确认该选择，不再改写归因或重跑 v28。
- v28 正式数据、费用、identity、lock、ledger、raw result 和 aggregate 继续只读保留；本轮仅修稳定入口，不创建 successor，也不发送真实 API 请求。
- 两个阻断按上述窄范围修复并补定向回归；不扩建审计、可信、调度或新测评框架。
- 当前不批准合并、推送或分支归档；待下一轮独立验收通过后再由用户决定交付动作。
- 整改日志中把 `53e9b4b3...` 称为“原 aggregate”并不精确，它实际是 tracked public baseline 的哈希；这是非阻断措辞问题，可在下一次窄修时顺手改准。

## 当前状态

- 正确性/功能性验收：**不通过**。
- 整体任务目标：**失败**（v28 正式基线已完成且有效；稳定统一重跑入口未达到自动终态收口要求）。
