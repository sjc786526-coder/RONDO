# Plan 090 阶段 A 整改复审

## 结论

`REQUEST_CHANGES`。首轮 `1 High / 3 Medium` 的四项指定整改均已闭合，但终态状态机仍有 **0 High / 1 Medium**，因此暂不批准进入付费阶段，付费门继续关闭。

本轮核对 `a2f8aa1`、`02cdae5`、整改 diff、freeze/runtime/result、no-update diagnostic、task-root、terminal、runbook 与 ignored bundle。复跑 Plan 090 聚焦测试为 `16 passed`；source archive `22bbfd70…` 绑定 `a2f8aa1` 并通过 exact-tree，data archive `6d98c163…` 复验 train `128/58`、validation `55/26`、unseen `0`；AST、freeze exact JSON、三个 shell `bash -n`、diff check 通过。审查输入时主工作区和 worktree tracked 状态 clean。未访问 live 服务，未运行真实模型、Cargo 或 Docker。

## Finding

### Medium — 两次 BF16 已通过并恢复，但已授权 FP32 因基础设施无法开始时没有合法终态

两次 BF16 clean run 均通过、第二条已 fresh-process recovery，且刷新预算仍授权完整 FP32 分支时，`next_action` 正确要求继续运行 FP32。若此时 exact Pod 丢失或持续不可用，PASS 会因正式分支尚未完成而被拒绝；当前 `INCONCLUSIVE_INFRASTRUCTURE` 又只放行第二 BF16 **尚未恢复**的 closure gap（`plan090_finalize.py:403-417`），因此同样被拒绝。

使用现有 fixture 只读复现：`[bf16 primary pass, bf16 secondary pass+recovered]`、正向 FP32 budget 和 `INCONCLUSIVE_INFRASTRUCTURE` 返回 `plan090_infrastructure_cannot_override_model_result`。这与 ExecPlan 已冻结的“有效正式结果后 exact Pod 丢失、无法在预算内从干净边界完成剩余序列时诚实收口为基础设施不完备”不闭合。

窄修要求：在现有 recovery-closure gap 之外，仅当两个 BF16 都通过、第二 BF16 已恢复、无有效负面结果、给定的 FP32 budget 经现有 validator 验证且 `next_action` 仍明确返回 `run / fp32-seed-20260901`，但该剩余分支因基础设施无法完成时，允许 `INCONCLUSIVE_INFRASTRUCTURE`。如果 FP32 预算不足，既有 PASS 分支保持不变；任何负面 BF16 仍不得被 infrastructure 覆盖。补一个对应聚焦测试即可，不增加故障证明、云编排或审计体系。

## 已确认闭合与决定

- 接受 seed 语义降格：不引入随机性，第二条只作为不同 seed 元数据下的独立 clean repeat，`seed_sensitive_stability_tested=false`。
- base/旧 Route O 的 train/validation objective、receipt/identity，Plan 090 task-root 专属门，以及“两条/三条全正向但恢复未完成”的 INCONCLUSIVE 已闭合。
- FP32 仍是诊断性分支，不新增自动 veto；WBS 继续不改。
- 只在现有 Plan 090 worktree 窄修、跑 Plan 090 聚焦测试和必要 diff/static 门后提交；不需要重建数据 archive。因为 Python 正式源码变化，整改通过前须重建并复验绑定新 commit 的 source archive；不合并、不推送。

## 状态

`验收不通过 / 阶段 A 任务目标失败（可整改） / PAID_GATE_CLOSED`。Plan 090 整体研究目标尚未执行。
