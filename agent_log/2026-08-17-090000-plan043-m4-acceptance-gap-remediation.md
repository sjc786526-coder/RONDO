# Plan 043 —— Multi M-4 独立验收缺口整改

日期：2026-08-17 ｜ 分支：`worktree-043-multi-m4-coordination-closure` ｜ 基线实现：`e03eef1` ｜ 审查：`e2105aa`

对照审查报告核实四条均成立，在 043 工作树窄修。未合并、未推送，不进入 M-5。

## 做了什么

**可用性复用真实恢复门禁，epoch 改单调 generation。** 从 `ensure_v2_agent_loaded` 抽出
`probe_v2_restore`：Loaded / Restorable / Unrecoverable / Failed。分类与恢复共用。epoch 不再是
内容哈希（`unavailable → available → unavailable` 会撞回同一 hash）；ThreadManager 在 insert/remove、
delete、residency 驱逐、restore commit 时 bump 单调 generation。快照用 seqlock；退休在 store 锁内
比较 live generation，不一致则 `AvailabilityConflict`。删掉 `rollout_path.exists()` 特判。

**dump 只补必要元数据，cursor 四段。** Version 带 `retire_reason` / `retired_availability` /
`retired_availability_epoch` / `fact_ids`；Fact 带 `call_id`；Participant/Publication 带 `thread_id`。
cursor 为 `revision:epoch:observe_generation:offset`。`confirm_observation` 与新建 participant 递增
`observe_generation`，旧 cursor 拒绝。dump/log/stats 在 store 锁内读 wake generation。

**同状态 lifecycle 是 no-op。** `pending→pending` / `tracking→tracking` 成功但不推进 revision、
changelog 或 wake generation。

**统计按 thread_id 聚合并分页。** 重复 label 不再错计；limit/offset 生效。

相对审查建议的取舍：epoch 用单调 generation 而不是内容哈希（审查允许“单调版本或等强原子重验”；
哈希无法挡住 ABA）。产品纵切仍覆盖 unload→recoverable 拒绝→delete→unavailable 退休；恢复门禁对照
和陈旧 epoch 分别落在控制面 Interrupted 驱逐测试与领域 live_epoch/ABA 测试，不把 crate-private
`ensure_v2` 抬到集成测试。

## 疑难问题

**Interrupted 驱逐后 store 摘要仍在。** 旧分类器看 `read_stored_thread` 会报 `recoverable_unloaded`，
但 `ensure_v2` 返回 `ThreadNotFound`，orphan 无法退休。分类必须走同一探针。

**M-1—M-3 与 M-4 并行时会踩 loopback 代理。** `team_coordination` 会清代理；M-1 套件不会。并行跑出现
502 / `expected 1 request, got 0`。清代理后单独重跑 16/16 通过，不是实现回归。

## 验收结果

命令均在 `multidev/` 下经共享构建锁执行。

| 门禁 | 结果 |
|---|---|
| `just test -p codex-team-state --lib` | 121/121 通过（含审查反例） |
| `just test -p codex-core --lib -- agent::control::availability` 及受影响 control/team tool 子集 | 通过；Interrupted 驱逐分类与恢复门禁一致 |
| `just test -p codex-core --test all -- suite::team_coordination` | 1/1 通过 |
| `just test -p codex-core --test all -- suite::team_world_state suite::team_routing suite::team_evidence` | 清代理后 16/16 通过 |
| `just fix -p codex-team-state -p codex-core`、`just fmt`、`just fmt-check` | 通过 |

未跑全 workspace、Docker、真实 API、本地模型。未合并、未推送。
