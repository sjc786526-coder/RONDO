# Plan 043 / Multi M-4 第五轮审查缺口整改

日期：2026-08-17 ｜ 分支：`worktree-043-multi-m4-coordination-closure` ｜ 基线实现：`def76b6` ｜ 复验：`8a3d7eb`

第四轮复验指出 active counter 与 availability generation 虽在同一 gate 内更新，但 snapshot 无锁读取时仍能插在两次原子写之间，发布新分类与旧 epoch。本轮只修这一处状态版本接缝；未重做 token、退休、dump 或统计设计。

## 实现

- `ThreadManagerState::availability_marker` 短持现有 availability gate，一次取得 generation 与 store-transition active；不跨 `await`。
- producer snapshot 在分类前和返回前都读取 coherent marker。transition active 时仍返回全员 `unknown`；marker 变化则重试。
- 该接缝同时覆盖 begin/end token 边界和 loaded-map mutation + generation bump，旧 cursor 不再能用同 epoch 拼接变化后的 availability。
- midpoint 回归补齐删除前、transition 中、删除完成后的 snapshot class 与 epoch 断言。

## 验证

命令均在 `multidev/` 下执行；Rust 构建与测试经共享构建锁及资源看门狗。

| 门禁 | 结果 |
|---|---|
| `just test -p codex-core --lib agent::control::availability` | 5/5 通过 |
| shutdown 后 explicit resume 单项 | 1/1 通过 |
| `just test -p codex-team-state --lib` | 125/125 通过 |
| `just test -p codex-core --test all -- suite::team_coordination` | 1/1 通过 |
| `just fix -p codex-core`、`just fmt` | 通过 |

首次 `just fmt` 因默认 UV cache 指向只读的项目外目录失败；改用项目内共享 `.uv-cache` 后通过，不涉及代码失败或宿主配置变更。未重跑 M-1—M-3、全 workspace、Docker、真实 API、本地模型或付费资源。

本轮只提交 043 工作树，未合并、未推送，不进入 M-5；等待独立复验。
