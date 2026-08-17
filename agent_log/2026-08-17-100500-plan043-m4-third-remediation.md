# Plan 043 —— Multi M-4 第三轮审查缺口整改

日期：2026-08-17 ｜ 分支：`worktree-043-multi-m4-coordination-closure` ｜ 基线实现：`c203e34` ｜ 复验：`31ecafc`

对照第二轮整改后复验核实三条均成立，在 043 工作树窄修。未合并、未推送，不进入 M-5。

## 做了什么

**store delete 改为两阶段 epoch。** `begin_thread_store_transition` / `finish_thread_store_transition` 各在同步 gate 内 bump 一次，await 的实际删除夹在中间。`delete_stored_thread` 与 app-server `thread/delete` 走同一对接口；删除可见之前旧 epoch 已失效。去掉只在删除后无锁 bump 的 `notify_thread_store_changed`。

**当前可用必须 loaded 且 `is_running()`。** 提交通道已关但仍留在 map 的 runtime 不再报 `available`；按 stored resume material 分成 recoverable / unavailable / unknown。探测时丢掉死驻留并 bump generation，使该变化进入 availability version。

**DumpCursor 绑定 TeamInstanceId。** 编码为 `instance:revision:epoch:observe_generation:offset`。跨实例续页返回既有 `InstanceReset`；旧四段 cursor 视为畸形拒绝。

相对审查建议：不跨 await 持锁，也不加 pending 事务旗标；两阶段 bump 已让退休看不到“store 已变、epoch 未变”的窗口。死驻留若尚无 rollout，分类为 `unavailable` 而不是强行 `recoverable_unloaded`，与 resume-material 探针一致。

## 疑难问题

关通道后若从未 flush rollout，store/history 读不到，分类是 `unavailable`。测试先落盘再关通道，覆盖“runtime 已死但同树仍可 resume”的反例。

## 验收结果

命令均在 `multidev/codex-rs` 下经共享构建锁执行。产品套件清 loopback 代理。

| 门禁 | 结果 |
|---|---|
| `codex-team-state --lib` | 125/125 通过（含跨实例 cursor 拒绝） |
| availability + `resume_agent_restores_closed_agent_and_accepts_send_input` | 6/6 通过 |
| `codex-core --test all` M-1—M-4 产品纵切 | 17/17 通过 |
| clippy `-D warnings`（team-state / core / app-server）、`just fmt` | 通过 |

未跑全 workspace、Docker、真实 API、本地模型。未合并、未推送。
