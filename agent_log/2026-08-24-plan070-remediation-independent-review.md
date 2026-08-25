# Plan 070 / M4-C0 修复轮独立验收审查

审查目标：`fe31e3f752a505af075f71359d0d40e6d7bf7f22`

前次审查：`agent_log/2026-08-24-plan070-independent-acceptance-review.md`

结论：**验收不通过；任务目标尚未完成。** 前次 7 项 finding 均已按范围闭合，response-lost、Root-only cold
prototype routing、DB error、child-page scanning、默认关闭、per-attempt certainty、ChildOnly 与 v2 wire 修复方向正确；但本轮在执行者点名的
bounded discovery cursor 复核中确认 1 项新的高优先级 correctness finding。修复前不能给出 `M4_C0_PROTOTYPE_PASS`，也不应合并或推送。

## Finding

### P1：相同 `created_at_ms` 的记录跨页时会被 cursor 跳过，却仍报告 discovery complete

C0 list 在 `app-server/src/request_processors/experimental_session_control.rs:89-103` 使用全局 State DB list 和
`SortKey::CreatedAt`。该非 relation 查询只按 `created_at_ms` 排序，不启用 thread-id tie-breaker：

- `state/src/runtime/threads.rs:1172-1176` 仅为 relation、`RecencyAt` 或 `SectionPosition` 启用 tie-breaker；
- `state/src/model/thread_metadata.rs:595-610` 因而为 CreatedAt page 生成 `id=None` 的 anchor；
- `state/src/runtime/threads.rs:1379-1408,1422-1453` 的下一页条件和排序均只有 timestamp。

因此，只要分页边界两侧存在相同毫秒时间戳，overflow row 就会被跳过。一个直接场景是 26 条 active Root 均有非空 preview 且
`created_at_ms` 相同，`limit=25`：底层先取 26 条、pop 一条作为 overflow，第一页返回 25 条与 cursor；第二页使用
`created_at_ms < anchor_ts`，永久排除第 26 条，并返回空页、`next_cursor=None`、`complete=true`。若第一页恰为 child、被跳过的是较旧
Root，同样会把实际非空 Session 集合投影为空且完整。

这不是要求正式 durable query 或额外审计设施，而是当前 C0 自己生成的 cursor 与所选排序键不构成稳定 keyset。建议在 070-owned
server seam 选择已有的稳定双键排序（例如当前 State DB 已为 `RecencyAt` 携带 thread-id anchor），或采用其他等强窄修；不要为此修改
`state/`、`thread-store/`、`rollout/` 或引入新分页平台。补一条同毫秒跨页回归，证明所有 Root 可经 cursor 枚举且最终 complete 诚实。

## 已确认闭合的前次 finding

- 真实 WebSocket 故障注入先让 server 完成 `thread/unarchive`，再丢弃 response；C0 专用 deadline 有界进入 stale/Unknown，wire mutation
  只有一次，显式 read 恢复 Fresh，迟到旧 request-id response 不覆盖新投影。
- track/unarchive 使用 typed per-attempt outcome；preflight 是 NotSubmitted，不再把历史 Unknown 错归给新操作。
- state DB 不存在或 query error 均返回 unavailable/incomplete，不再伪报完整空集合。
- Root filtering 会在 400-row/16-page 有界范围内继续读 source；耗尽预算会 `complete=false` 并保留 cursor。除上述同 timestamp keyset
  缺口外，扫描预算和 complete 语义成立。
- archived child 不再暴露 cold unarchive availability；真实 ChildOnly 按 Root/child id 查询结果一致，online mutation fail closed；
  `prototype_facts` 已遵循 v2 optional/nullable wire 规则。
- 默认关闭的 feature 不再贡献 startup tooltip，原型仍保持独立 product gate；未发现 TUI→core/store 旁路或 069/S1/S2 写集越界。

## 替用户作出的决策与复验边界

- **接受 C0 的 Root-only cold 边界位于 prototype projection + AppServerSession fresh preflight。** 该路径只在 stored metadata 证明
  canonical Root 时提交同一 id；不要求本任务改变稳定的通用 `thread/unarchive`。日志和交接只能声称“C0 TUI prototype routing
  fail closed”，不能声称公共 app-server mutation point 已获得正式 Root authority。
- **接受 response timeout 后旧 transport correlation entry 留到迟到 response 或断线再清理。** request id 单调且 exact-id 分发，旧
  oneshot receiver 已释放；它不会污染新 read、让 controller 继续 Pending 或触发 replay。无需建设通用 request cancellation/reconnect 平台。
- 前次完整门禁的 16 项范围外失败继续不阻断 070，也不要求修复；本轮不重跑 14k workspace 门禁。上述 pagination 修复后只需相应
  app-server public JSON-RPC 回归、必要 schema check、受影响 crate fix/format；若实现未改变协议或其他 crate，不扩大验证。
- 本轮只读检查当前修复 diff、调用链、测试和底层 keyset 实现，未重复运行 Cargo 重型测试、Docker、真实 API/模型、测评、CI/PR 或
  远端操作。worktree 审查开始时 clean，`git diff 1bfdaa0..fe31e3f --check` 通过。

## 修复后复验重点

1. 同 `created_at_ms` 的 Root/child 横跨 source page 时，cursor 不漏记录、不重复，最终空页/complete 只在 source 真正耗尽时出现。
2. 修复保持 server-owned、只读、有界，不改 State DB/ThreadStore/rollout，不扩展为通用 query 平台。
3. 前次 7 项修复与默认关闭行为保持不回归。
