# Plan 051 第三轮独立验收

日期：2026-08-21

结论：**验收不通过；任务目标失败。** 第二轮指出的正常 `run`/`resume` 自动收口和 blocked 比较问题已经正确修复，v28 正式基线仍有效且无需重跑；但终态收口仍有一个可稳定复现的崩溃恢复阻断，以及一个可能错误返回成功的退出码校验缺口。因此“稳定统一重跑入口”尚未达到任务要求。

## 阻断项

1. **P1：`finalize` 无法恢复“预算已关闭、active pointer 尚未退役”的合法崩溃窗口。**

   `_close_published_terminal()` 先原子关闭 task-budget envelope，随后才退役 active pointer（`formal_canary.py:440-469`）。若进程恰在两步之间中断，下一次 `finalize` 会先无条件调用 `baseline_main()`（`formal_canary.py:534-542`）；但 baseline worker 在进行任何终态发布恢复之前，强制调用 `verify_active_identity()`（`baseline_cli.py:442-453`）。此时 envelope 已经 closed，worker 返回错误，控制流永远到不了能够复核 closed identity 并退役 pointer 的 helper，形成无法靠稳定入口自愈的 active-pointer 残留。

   现有 `test_finalize_retires_only_a_closed_terminal_identity` 把 `baseline_main` 直接 mock 为 0，因而绕过并掩盖了上述真实门禁。建议保持窄修：`finalize` 先读取 envelope；若当前 identity 已以匹配终态记录在 `closed_identities`，则跳过 runner，直接复核并退役 pointer；只有 envelope 仍以当前 identity active 时才运行发布恢复。补一条“closed envelope + active pointer + runner 不得调用”的入口级回归即可。若执行者有证据充分的等价方案，可以采用更优实现。

2. **P2：passed/failed 与 runner 退出码不匹配时并未真正 fail-closed。**

   `_close_published_terminal()` 在 durable passed/failed 与期望退出码不一致时直接返回原退出码（`formal_canary.py:437-439`）。特别是 durable `failed` + runner rc=0 会向调用方返回成功，同时既不闭合 envelope 也不退役 pointer；这与整改日志声称的“状态/退出码不匹配时 fail-closed”不符。

   建议在正式终态与退出码不匹配时明确抛出 `FormalCanaryError`（或采用同等明确、绝不返回成功的失败语义），并为 passed/2 与 failed/0 补轻量定向回归。无需增加新的审计或恢复设施。

## 已确认正确的部分

- `run` passed/0 与 `resume` failed/2 的正常路径现在会共用 envelope 闭合、closed identity 复核和 pointer retirement，并保留退出码 0/2。
- blocked aggregate 仍正常归档，但不再进入只接受 passed/failed 的 relative-baseline publisher；`run` 对 blocked/3 原样返回并保留 active identity/pointer 给 successor。
- 新 Local、campaign、价格和 task-budget 输入仍保持显式、隔离；Plan 051 已关闭的预算不会被重新打开。
- v28 tracked public baseline 和派生 comparison 的 SHA-256 仍分别为 `53e9b4b3...02a0c8f` 与 `56a0a704...3ef51`；v28 baseline/raw runs 相对既有 results 提交无差异。
- 默认 `just eval-plan051` 仍返回 `idle`、`active_lock=null`、`paid_requests_sent=0`。

## 定向验证

- task budget、formal canary、relative baseline、新 identity/budget 相关无 API 单测 31/31 通过。
- 修改模块 `py_compile`、`git diff --check`、默认零请求状态检查通过。
- 上述 P1 由真实调用顺序和 worker active-envelope 门禁直接确认；现有测试因 mock runner 未覆盖该恢复窗口。P2 由 helper 的直接返回分支确认。
- 未运行 Docker、Cargo、真实 API、全 workspace、CI/PR、validation、holdout、本地模型或训练。

## 代用户作出的决策

- v28 正式基线继续认定有效，不创建 successor、不重跑、不改变费用、identity、lock、ledger、raw result 或比较合同。
- 保留双方主模型 Terra/medium、Guardian Terra/low 的冻结合同与既有用户归因。
- 只修上述恢复窗口与退出码校验，并补对应定向回归；不扩建审计、可信、调度或新测评设施。
- 以现场 Git 为准：execution 实际提交为 `51e160d00a547a3171b5db2bc440a5ea95dca2cb`，执行汇报中的完整 SHA `51e160df...` 不匹配，按非阻断笔误处理。
- 当前不批准合并、推送或分支归档；下一轮轻量验收通过后再由用户决定交付动作。

## 当前状态

- 正确性/功能性验收：**不通过**。
- 整体任务目标：**失败**（v28 正式结果已完成且有效；稳定统一重跑入口仍缺少必要的终态崩溃恢复能力）。
