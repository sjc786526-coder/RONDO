# Plan 074 外部验收审查

## 审查对象与结论

- 审查提交：`bf8b7da6a7a4bc1db962c1f5a4b97dc55267673c`。
- 审查范围：Plan 074 合同、7 文件实际 diff、ThreadStore cwd/lineage/permission 合并路径、app-server read/list/resume 消费链、已有
  watchdog/JUnit 与未通过项。
- 结论：**不通过，需一项中等级 correctness 修复**。未发现高等级问题；除下述 finding 外，persisted read/list 与显式 live
  cwd/workspace roots 的责任分离、canonical rollout mismatch 拒绝和 permission 最终 cwd 重算均符合任务方向。

## Finding

### M-1：有效 persisted cwd 无法救济同 lineage rollout 中的无效 cwd

`read_thread_by_rollout_path()` 在读取 matching SQLite metadata 之前，先调用
`read_thread_from_rollout_path()`（`multidev/codex-rs/thread-store/src/local/read_thread.rs:127`）。后者在只读 SessionMeta 路径和正常
rollout item 路径分别于 `:297`、`:328` 立即拒绝空或相对 cwd。于是当现场为：

1. 请求的是 canonical rollout；
2. rollout/SessionMeta 的旧 cwd 为空或相对路径；
3. 同 Thread ID、同 resolved rollout 的 SQLite metadata 已持久化可信绝对 cwd；

读取会在 `:133-168` 的 lineage 匹配和 persisted cwd overlay 之前失败，可信 persisted cwd 永远没有机会成为最终 projection。
`read_thread()` 的 `include_history=true` 路径也受影响，因为 `sqlite_rollout_path_can_load_history_for_thread()` 复用了这个提前校验；app-server
legacy resume 随后会在按 rollout path 重新加载 history 时走同一失败路径。

这与 Plan 074 的核心结果“matching persisted cwd 覆盖同一 rollout 的旧 cwd，read projection 与 legacy resume 可继续使用”冲突。
现有回归只覆盖了相反组合——SQLite cwd 空/相对而 rollout cwd 有效——因此没有暴露该问题。

## 修复与复验边界

- 将 cwd 有效性判断延后到 matching lineage metadata 合并完成之后，或采用等强结构：先安全取得 Thread ID/rollout lineage，只有 exact
  canonical path 匹配才允许 overlay persisted cwd，最后统一验证最终 cwd并据此重算 legacy permission。
- matching metadata 不存在、不可解析或指向另一 rollout 时，仍不得用它救济当前 rollout；最终 cwd 无效时继续 fail-closed。
- 增加一个最小回归，覆盖“rollout cwd 空或相对 + matching persisted absolute cwd”的 read-by-path/history 路径；应同时断言最终 cwd 与
  legacy permission。若现有 fixture 容易复用，可再把该组合穿过一次 cold legacy resume；不要求另建测试平台。
- 只需重跑新回归、直接相邻 ThreadStore/app-server 切片、相称 lint/format/diff 检查；不要求全 workspace、Docker、真实模型或 Plan 069
  阶段 E。

## 已复核证据与非阻断项

- ThreadStore 190/190、最终聚焦 3/3、resume 单跑 1/1 及 finding 修复 1/1 的 JUnit/summary 均与执行摘要相符；本次审查未重复运行 Cargo。
- 069 相邻 cold-resume 的失败证据确实停在未修改 mock `/v1/responses` 的 502/超时链，没有 cwd/ThreadStore 断言失败。联合 app-server
  clippy 的既有 core lint 阻断也已如实记录；二者不要求在 074 中扩大修复。
- state-only list 对无法独立证明的空/相对 cwd 整体 fail-closed，是本任务允许的诚实错误语义。本轮决定保留该策略，不要求为可用性另建
  repair、隔离或审计设施。

## 代用户决策

- 无需用户追加选择。M-1 属于既定 Plan 074 目标内的窄正确性修复，执行者可自主采用最契合当前代码的等强实现并复验。
- 保持当前授权边界：不处理 069 的 mock 失败或既有 core clippy，不运行重型扩大门禁，不更新 WBS，不合并或推送。

## 当前状态

- 验收：`NOT_ACCEPTED / REMEDIATION_REQUIRED`。
- 任务目标：尚未完成；M-1 关闭并复验后再进行外部验收。
