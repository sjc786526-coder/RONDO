# Plan 043 —— Multi M-4 第四轮审查缺口整改

日期：2026-08-17 ｜ 分支：`worktree-043-multi-m4-coordination-closure` ｜ 基线实现：`59b0f33` ｜ 复验：`c3e9563`

对照第三轮整改后复验核实中间 epoch 双义成立，在 043 工作树窄修。未合并、未推送，不进入 M-5。

## 做了什么

**store transition 增加 active token。** `begin_thread_store_transition` 返回可跨 await 持有的 `StoreTransitionGuard`：计数器加一并 bump epoch。`finish` 与 `Drop` 都能减一并再 bump。`delete_stored_thread` 与 app-server `thread/delete` 持有该 token。

**transition 期间可用性 fail-closed。** snapshot/classify 在 active 时一律 `unknown`；`team_retire` 持闸门时若仍 active 则 `AvailabilityConflict`。同一中间 epoch 不再既能表示 recoverable 又能表示 unavailable。

相对审查建议：采用 token 而不是只加裸计数器，避免取消/错误路径漏 finish。不在 snapshot 里忙等重试，直接 unknown，避免把 dump 绑在删除 I/O 上。

## 验收结果

命令均在 `multidev/codex-rs` 下经共享构建锁执行。产品套件清 loopback 代理。

| 门禁 | 结果 |
|---|---|
| `codex-team-state --lib` | 125/125 通过 |
| availability + resume 精确测试 | 6/6 通过（含 midpoint barrier） |
| `codex-core --test all` M-1—M-4 产品纵切 | 17/17 通过 |
| clippy `-D warnings`（core / app-server）、`just fmt` | 通过 |

未跑全 workspace、Docker、真实 API、本地模型。未合并、未推送。
