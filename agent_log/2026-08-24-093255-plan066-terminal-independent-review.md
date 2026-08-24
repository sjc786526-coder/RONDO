# Plan 066 终态独立验收

## 结论

- **本轮终态验收不通过，存在 1 个阻断项：provider billing 尚未结算稳定。** 训练主体、候选、恢复、代码修复和资源终态均正确；阻断仅影响
  `provider_bill_settled=true`、最终费用与 final receipt 的终态真实性，不是训练路线失败。
- 当前 `plan066-final-receipt.json`（SHA-256 `6d90468b...6def`）记录余额 `$11.9072265969`、连续费用 `$11.6881377997`。独立只读查询于
  2026-08-24T16:30Z 后得到余额 `$11.8393653830`，对应连续 balance delta 已为 `$11.7559990136`，比 receipt 多 `$0.0678612139`；该变化远高于
  唯一卷约 `$0.006/h` 在数分钟内的线性费用。
- 已删除 Pod 的小时账单目前只有 14:00、15:00 两个 bucket，合计 `$3.0658493785`，仍缺训练/Pod 持续至约 16:24Z 所对应的 16:00 bucket。
  因而现有 provider facts 的 `provider_bill_settled=true` 已被实时事实推翻，`GO_RECOMMENDED` 只能保留为技术建议，不能作为最终已结算 receipt 验收。

## 已通过部分

- commit `4249e6b` 对 resume validator 的窄修复正确：复用完整 process identity 合同，要求 start/resume PID 与 instance ID 均不同，并覆盖同 PID、
  同 instance ID 和 bool PID 负例；实际 final-01 pending receipt 通过新合同。
- final receipt 对 start/pending/provider facts 的 SHA-256、identity、coverage、checkpoint、三个候选、资源和预算字段绑定一致；若 provider facts 本身
  结算稳定，该 finalizer 链成立。
- 独立复跑 Plan 066 focused 11/11 通过；三个 launcher `bash -n`、实际 bundle/start/pending/provider validator、final receipt 交叉绑定与
  `git diff --check` 通过。未运行训练、完整模型、Docker、Cargo 或无关全仓测试。
- RunPod 实时只读控制面确认 Pod 数为 0；唯一网络卷为 Standard 60GB `hi3iaz8rsr`。计算持续费已归零，当前持续费率约 `$0.006/h`，资源终态正确。
- 三个候选与正式 checkpoint 仍在 winner 卷，候选真实加载验证按既定边界留到 M3-C1 或删除唯一卷副本前；这不是 Plan 066 当前阻断项。

## 代用户作出的决定

1. **保持 0 Pod，绝不重启或新建 Pod。** 当前 finding 只需只读等待账单追记，不需要任何 GPU、训练、模型或代码重跑。
2. **继续保留 winner 卷。** 不删除 `hi3iaz8rsr`、候选或 checkpoint；约 `$0.006/h` 的卷费纳入更新后的连续总账。
3. **现有 terminal receipt 降为 superseded。** 不把 `6d90468b...6def` 写成最终已验收 receipt，也不必破坏性覆盖；结算稳定后生成新的
   `provider-terminal-facts-final-02.json` 与 `plan066-final-receipt-final-02.json`（或等强新身份），更新 tracked 执行日志、Plan/WBS 当前状态。
4. **简单稳定门即可。** 等待已删除 Pod 的 16:00 billing bucket 出现；之后至少两次、间隔不少于 5 分钟只读采样，Pod billing 总额不再变化，且余额变化
   只符合唯一卷费的线性增量（允许约 `$0.005` 采样容差），再设置 `provider_bill_settled=true` 并运行 finalizer。
5. **后续复验保持窄。** 只核对新 provider facts、费用算术、新 receipt hash/绑定、0 Pod/唯一卷和文档状态；不重审训练主体，不追加审计设施。

## 当前状态

- 验收：`FAIL / TERMINAL BILLING NOT SETTLED`
- 训练主体目标：`COMPLETE / PASS`
- Plan 066 整体任务：`INCOMPLETE, NOT FAILED`
- 训练路线建议：`GO_RECOMMENDED PENDING VALID TERMINAL RECEIPT`
- RunPod：`0 PODS / COMPUTE COST ZERO`
- winner 卷：`RETAINED`
- M3-C1：仍锁定，等待更新后的终态 receipt 与最终独立验收
