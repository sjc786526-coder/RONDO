# Plan 043 —— Multi M-4 复验缺口整改

日期：2026-08-17 ｜ 分支：`worktree-043-multi-m4-coordination-closure` ｜ 基线实现：`8f73572` ｜ 复验：`035977c`

对照复验报告核实四条均成立，在 043 工作树窄修。未合并、未推送，不进入 M-5。

## 做了什么

**产品可用性改走 `resume_agent` 恢复能力。** 自动 V2 load 仍用 `probe_v2_restore`（可继续要求 registry）。
分类用 `probe_producer_recoverability`：store+history 能重建即为 `recoverable_unloaded`，registry 缺失不能当成真正不可用。`shutdown_live_agent` 后 NotFound 仍可 resume，不得退休。

**退休最终检查与恢复/删除共用同步 availability gate。** loaded-map insert/remove、store delete、registry release 的 generation bump 与 `team_retire` 的 live epoch 重验持同一把 `std::sync::Mutex`；gate 内不再 await。app-server `thread/delete` 成功后 `notify_thread_store_changed`。

**dump 单条有界、续页只走冻结 cursor、Agent 关系补 ThreadId。** Version 不再内嵌无界 `fact_ids`，改为独立 `VersionFact` 行计入页上限。裸 offset 拒绝。Version/Route/Fact/Visibility/Activity/ChangeLog 在保留 label 的同时写出 `thread_id`。

相对审查建议的取舍：闸门用同步 Mutex 而不是跨 await 的 tokio Mutex（clippy 禁止跨 await 持该锁）；分类与 `ensure_v2` 拆成两条探针，避免把“自动 V2 load 失败”误当成不可 resume。

## 疑难问题

**Interrupted 驱逐后 leftover store 仍可 resume。** 上一轮把“ensure_v2 失败”当成 unavailable。按本轮决策，只要 rollout 还在，就是 recoverable。控制面测试改为：ensure_v2 仍可失败，分类为 `recoverable_unloaded`。

## 验收结果

命令均在 `multidev/` 下经共享构建锁执行。产品套件清 loopback 代理。

| 门禁 | 结果 |
|---|---|
| `just test -p codex-team-state --lib` | 124/124 通过（含 offset 拒绝、VersionFact 分页、重复 label 身份） |
| `just test -p codex-core --lib -- agent::control::availability resume_agent_restores_closed_agent_and_accepts_send_input` | 4/4 通过 |
| `just test -p codex-core --test all -- suite::team_coordination suite::team_world_state suite::team_routing suite::team_evidence` | 17/17 通过 |
| `just fix -p codex-team-state -p codex-core`、`just fmt` | 通过 |

未跑全 workspace、Docker、真实 API、本地模型。未合并、未推送。
