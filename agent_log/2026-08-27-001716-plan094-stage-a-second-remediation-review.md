# Plan 094 阶段 A 第二轮整改复审

## 结论

`REQUEST_CHANGES`。上一轮关于 5 USD 硬上限的 High 已经闭合；本轮发现 **0 High / 1 Medium**，阶段 A 暂不通过，付费门继续关闭。问题只涉及终止确认时刻的真实性，可以在 Plan 094 守护接缝和对应 fake-clock 测试内窄修，不需要增加通用预算、云编排、审计或可信设施。

复审基于第二轮整改提交 `9d9990cf803c21a4c5d0b0a0507e84c0416318d4`。审查者复跑 Plan 094 focused unittest 为 `17/17` 通过；并行独立复核的 Plan 094、相邻 Plan 090 和 Plan 087 terminal 定向测试合计 `37/37` 通过，`git diff --check` 与变更前 worktree clean 状态通过。没有运行 Cargo、Docker、真实模型、训练或云写。

## 已闭合项

- Pod 的唯一绝对终止点由 provider start 派生，后续 bootstrap/segment 必须消费同一 lifecycle authorization，不能通过新 segment 延长生命周期。
- host-only guard 按 runbook 以 `nohup` + `setsid` 脱离操作会话，复用 Plan 087 exact helper 执行 stop/delete 并要求账户 Pod 列表为 0；守护未成功 armed 时立即同步释放。
- 5 USD 上界已经纳入既有保守任务费用、active lifetime、60 秒 worker kill grace、360 秒 terminal confirmation reserve、closure reserve 和实时余额/聚合费率。
- Plan/WBS、付费门和接手日志准确记录阶段 A 待复审及用户暂停付费；接手日志保持精炼，未复述 Plan。

## Remaining finding

### Medium — `confirmed_at` 早于真实 0 Pod 确认

`training/publication-critic-plan094/runpod-lifecycle-guard.py:56-83` 在调用 terminal helper **之前**取得 `observed`，helper 完成 stop/delete、查询并通过 `_require_zero_pod()` 后仍把这个旧值写入结果的 `confirmed_at`。生产 helper 最长可运行接近 300 秒，因此结果可能把确认时刻提前数分钟；当前 `test_detached_lifecycle_guard_uses_absolute_trigger_and_exact_terminal` 的 fake terminator 瞬时返回，没有覆盖这个时序。使用 fake clock 令 terminator 推进 250 秒可稳定复现：真实时钟到 `00:04:20Z`，结果仍记录 `00:00:10Z`。

实际 stop/delete/0 Pod 校验仍然执行，且生命周期授权已经预留 360 秒，所以这不是资源释放或预算硬上限失效的 High；但终止结果把动作开始时间冒充确认完成时间，属于需要修正的结果正确性问题。

窄修目标：在 `_require_zero_pod()` 成功后重新读取时钟，以真实完成时刻写入 `confirmed_at`，并保证成功确认没有越过已授权的 terminal confirmation deadline；补一个 terminator 会推进 fake clock 的回归即可。Plan 087 receipt 当前以调用前 `captured_at` 作为 billing 查询结束时间，也会漏掉 helper 执行区间；可在 Plan 094 接缝成功后补一次相称的 live/budget capture，或用同样简洁且有证据的办法让最终小型结果覆盖真实确认时刻，不要求改造 Plan 087 历史通用设施。

## 审查决定与边界

- 本轮不再改 Pod deadline、预算算术、训练/评测路线、模型、数据、material rubric、停止或 retention 合同；只整改确认完成时刻及其定向测试/必要小型结果。
- 用户已明确暂停付费。即使后续阶段 A 技术验收通过，也不得由审查者批准进入阶段 B；继续保持 `PAID_GATE_CLOSED / PAID_STAGE_PAUSED_BY_USER`，不得刷新、创建或修改云资源。
- 当前 handoff 的内容和范围可保留，下一次提交只需把审查链/当前状态更新到真实值；所有变更继续只提交现有 Plan 094 worktree，不合并、不推送、不归档或删除工作树。

## 状态

`验收不通过 / 阶段 A 任务目标失败（可整改） / PAID_GATE_CLOSED / PAID_STAGE_PAUSED_BY_USER`。Plan 094 总任务未进入付费执行，也没有形成 material/no-improvement/INCONCLUSIVE 结果。
