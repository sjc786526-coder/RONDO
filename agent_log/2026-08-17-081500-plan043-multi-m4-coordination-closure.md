# Plan 043 —— Multi M-4 协调闭合与可观测性实现

日期：2026-08-17 ｜ 分支：`worktree-043-multi-m4-coordination-closure` ｜ 基线：`main@af1063d`

## 做了什么

Harness 从控制面派生 producer 四类可用性；只有 Root 能在作者被确认真正不可用后，把仍开放的 Version
退休为独立终态；Root 可用有界 dump / 变更日志 / 发布统计解释当前团队状态。

**可用性**只在 `AgentControl` 判定：`get_thread` 成功为 `available`；未加载但 `read_stored_thread`
（含 archived）成功为 `recoverable_unloaded`；store 明确 `ThreadNotFound`，或读到的摘要指向已经不存在的
rollout 文件，为 `unavailable`；manager 丢失或其他读错误为 `unknown`。team-state 只比较这份快照，
不自己猜生命周期。

**退休**是 `Option<RetirementRecord>` 覆盖层，producer 仍是 `open`。只撤销该 Version 的
producer-open 活动理由，不改 root attention、route、其他 Version、Fact refs 或 authored 内容。
陈旧 epoch、可恢复/未知/仍可用、非 Root、已 closed/已退休均拒绝。精确重试返回原结果，不 bump
revision / wake generation / 日志 / 统计。

**可观测性**是 Root-only `team_inspect`：dump 一页硬上限 50，cursor 为 `revision:epoch:offset`；
变更日志按 revision 排序、用 offset 分页，只记真实 canonical commit；统计从当前 Event/Version
重算。dump 对外 ID 用与投影相同的 Display 字符串。`notify_change` 只在真实 mutation 上推进。

协议片段升到 v4。新增 `team_retire` / `team_inspect`。

## 疑难问题

**`CodexErr::ThreadNotFound` 不能当 tuple variant match。** 它是 associated constructor，分类时改用
`err.details()` 的 `CodexErrorDetails::ThreadNotFound`。

**Local store 删除后 `read_thread` 仍可能成功。** 删除会去掉 rollout 文件，SQLite 摘要行还能让
`include_archived: true` 读出一条带过期路径的 `StoredThread`。若把“store 读成功”一律当成可恢复，
产品纵切里真正删掉的 worker 会一直显示 `recoverable_unloaded`。分类改为：摘要指向的 rollout
文件已经不存在，就是 `unavailable`。这没有削弱仍能恢复的路径。

**产品纵切必须走 manager 自己的 store。** 另构一个 `thread_store_from_config(..., None)` 会得到
没有 state_db 的第二份 Local store，删的不是分类器看到的那份。测试改为
`ThreadManager::remove_thread` 卸载、`delete_stored_thread` 删除。

**dump 的 typed ID 不能直接 Serialize。** 派生 serde 会把 `VersionId` 打成内部字段，模型和测试都对不上
投影里的 `ver-…`。dump 条目改为 Display 字符串。

## 验收结果

命令均在 `multidev/` 下经共享构建锁执行；集成测试额外清空代理变量。

| 门禁 | 结果 |
|---|---|
| `just test -p codex-team-state --lib` | 114/114 通过 |
| `just test -p codex-core --test all -- suite::team_coordination` | 1/1 通过 |
| `just test -p codex-core --test all -- suite::team_world_state suite::team_routing suite::team_evidence` | 16/16 通过，无退化 |
| `just test -p codex-core --lib -- agent::control team:: tools::handlers::team_tools context::team_protocol context::world_state::team tools::spec_plan` | 124/124 通过 |
| `just fix -p codex-team-state -p codex-core`、`just fmt`、`just fmt-check` | 通过 |

产品纵切：成员发布开放 Version；卸载后 dump 为 `recoverable_unloaded` 且退休被拒绝；删除 stored
thread 后 dump 为 `unavailable` 且 Root 退休成功；log 记录 `retire` 与 `root_does_not_self_wake`；
stats 计 1 次发布；dump 显示 `retired=true`，投影仍 `root=pending`。

未跑全 workspace、Docker、真实 API、本地模型。未合并、未推送。
