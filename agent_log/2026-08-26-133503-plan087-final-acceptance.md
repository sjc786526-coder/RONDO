# Plan 087 最终验收

## 结论

- 审查对象：`worktree-087-publication-critic-adaptive-search@2a8ab98d678e76a8eb1e5dcbded9f4773a778262`
- 验收结论：**通过**。
- 任务目标：**完成**，研究终态保持 `PROMISING_CANDIDATE_RETAINED`。
- correctness/functionality finding：High 0，Medium 0。
- 云端终态沿用已复核证据：0 Pod、持续 compute 费率为 0；既有网络卷 `mwemzrn33y` 保留为 57GB，未删除。

Route O 满足本任务“有潜力研究候选”的启发式终点：同一 validation 上出现非统一 offset 的分布式排序变化，boundary、projected within-PASS 与 ROC AUC 有小幅改善，关键 operating 指标未退化；精确候选 checkpoint 已通过不同 OS 进程的 no-update 恢复。该结论不等于效果已由干净独立复现确认，也不解锁 unseen、M3-C1、M3-C2、产品 GO 或部署。

## 本轮仓库整改复验

用户指定的三项最终收口均已闭合：

1. `scripts/create-runpod-plan079-initial-when-ready.py` 与对应测试已通用化重命名为 `scripts/create-runpod-when-ready.py` 和 `eval/tests/test_runpod_create_when_ready.py`；活跃引用已同步。
2. `training/publication-critic-plan087/runpod-create.py`、对应创建/确认测试、current source bundle member，以及 runbook/ExecPlan 中的 Plan 087 专用创建 receipt 路线已删除。现行流程只用通用脚本抢卡，随后由执行者通过既有 RunPod MCP/CLI 独立核验实际价格、GPU、机房和网络卷挂载；不符或无法确认时立即使用保留的 `runpod-terminal.py` 释放并确认 0 Pod。没有另建专用创建器、receipt 或云端编排体系。
3. 根 `AGENTS.md` 与 `CLAUDE.md` 的工作流程第 7 条逐字一致，固定了通用脚本的窄职责和“先创建、后独立核验、不符立即释放”流程。

历史 `agent_log/` 与已执行的 `6dd27d8` source archive 未被改写；Plan 087 结果文件和两份 WBS 在整改提交中保持不变；terminal 停止/删除能力继续存在并受测试覆盖。

## 验证证据

- 相邻 Plan 081/082/087 与通用创建器聚焦测试：`91 passed, 34 subtests passed`。
- 定向 Ruff：实际整改涉及的通用创建器、创建器测试、Plan 087 terminal 测试与 bundle 通过；5 个改动 Python 文件 format check 通过；5 文件 AST 解析通过。
- 三个 Plan 087 shell 脚本通过 `bash -n`；通用创建器和 terminal 的 `--help` 可用。
- 旧路径、Plan 087 专用创建器及其活跃 receipt 文件名在非历史 tracked 内容中无残留；删除项确实不存在，terminal 仍存在。
- `git diff --check 995adb8..2a8ab98` 通过；整改没有改动 WBS、WBS-COMPLETED 或正式结果摘要；worktree 在复验前保持 clean。
- 独立只读复核结论为 High 0、Medium 0；未访问 live 云状态、未恢复 Pod、未运行 Cargo、Docker、本地真实模型或训练。

## 替用户作出的决定

1. 接受本次仓库整改，并据此正式接受 Plan 087 整体交付；不要求执行者再做仓库修改或重跑训练。
2. Route O 继续按 `PROMISING_CANDIDATE_RETAINED` 记账，因为它达到本任务约定的“研究候选”门槛；同时把“效果是否可靠”保留为未确认事实。15 条路线共用 validation 参与自适应选择，且没有干净独立复现，因此不得把它写成稳定提升或产品候选。
3. 原任务整体验收现已完成，可以由审查者统一更新 WBS/WBS-COMPLETED。后续正式复现只能作为独立工作包，不在 Plan 087 内恢复计费。
4. 因 Route O 尚不是效果可靠的候选，触发用户交给审查者的跨历史路线原因调研；该调研与 WBS 收口由审查者另行完成，不退回执行者。

## 最终状态

`验收通过 / 任务目标完成 / PROMISING_CANDIDATE_RETAINED / ZERO_POD`

验收后，审查者按用户追加要求完成跨历史路线原因研究，并在保留已进入 `main` 的 Plan 086/088 事实前提下统一同步 WBS、
WBS-COMPLETED 与本计划终态。原因报告为
`doc/research/2026-08-26-publication-critic-training-route-outcome-analysis.md`；它确认 Route O 值得独立复现，但尚不是效果可靠候选。
