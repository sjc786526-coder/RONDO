# Plan 070 / M4-C0 最终独立验收

审查目标：`bb60a04938b2f55c5ceede4fd5820f1e7637b30f`

前次修复轮审查：`agent_log/2026-08-24-plan070-remediation-independent-review.md`

结论：**验收通过；任务目标完成。** 同毫秒 discovery cursor finding 已以范围内的窄修闭合，前次 7 项修复未回归；当前实现、测试、
文档和证据足以支持 `M4_C0_PROTOTYPE_PASS`。未发现剩余 C0 correctness finding。

## 最终 finding 复验

- C0 discovery 已在 `app-server/src/request_processors/experimental_session_control.rs:89-105` 从 timestamp-only `CreatedAt` 切换为
  `RecencyAt`。State DB 现有实现会为该 sort key 同时使用 recency timestamp 与 thread id：
  `state/src/runtime/threads.rs:1172-1176,1379-1408,1422-1453` 的过滤和排序均带相同 tie-breaker，
  `state/src/model/thread_metadata.rs:595-610` 也把 id 写入下一页 anchor。
- C0 既有 cursor codec 已支持 `timestamp|threadId`，本轮没有改变 protocol 或 schema。server 生成与解析的是 State DB 同一
  `Anchor`，第二页不会再把等时间戳 overflow row 排除。
- 新公共 JSON-RPC 回归创建 26 个同毫秒 Root，以 limit 25 读取两页；除分别断言 25/1 条和 cursor 最终耗尽外，还比较全部
  session id 的集合，能够同时发现遗漏和重复。
- retained JUnit `03d16a7a-9b6a-487b-8810-2a96cb18c083` 证明旧代码首跑和自动重试均稳定得到第二页 0 条；
  `23ab43b6-5423-41ba-8f44-83af3378b91f` 证明修复后该回归 1/1 通过；
  `85e47146-0249-4c7f-a35b-e634691ab5bd` 证明 app-server `experimental_session` 全集 13/13 通过，覆盖 DB unavailable/error、
  child-page scan、archived child、ChildOnly、owner operation 和 cold lifecycle。

## 最终整体判断

- v2 experimental protocol 与独立默认关闭 product gate 保持分离；关闭态无 Session startup tooltip、后台查询或 TUI 可见原型变化。
- list/read 仍只使用只读来源，不 repair、不加载 Session、不启动 Agent/model/API；S1 缺失事实仍标为 prototype、unknown 或
  unavailable。
- online mutation 仍只路由到 current/running canonical Root owner；non-owner、ChildOnly 和 owner unavailable fail closed。
- C0 cold unarchive 仍只在 prototype projection 证明 stored canonical Root 且 AppServerSession 持有同 attachment 的 fresh view 时
  提交既有权威 `thread/unarchive`。该结论只适用于 C0 TUI prototype routing，不宣称稳定公共 mutation point 已获得正式 Root authority。
- lag、disconnect、EOF 与真实 response loss 的 stale/Unknown、不重放、权威 reread和迟到 request-id 隔离保持成立；per-attempt
  outcome 不再混用历史 certainty。
- 本轮精确 diff 只涉及 app-server 排序键、公共 JSON-RPC 回归、API README、任务 Plan 状态和执行日志；未触碰 state、
  thread-store、rollout、Team durability、069 或正式控制面，也未引入通用分页/重连/审计设施。

## 替用户作出的决策与验证边界

- **接受 `RecencyAt + thread-id` 作为 C0 原型 discovery 排序。** 它复用现有稳定 keyset 且不冻结正式 durable Session query 的排序
  合同；正式 query 仍等待 S1 后单独设计。
- **接受本轮不重跑 schema generator、protocol/client/TUI 与 14k workspace 门禁。** 本轮无 wire、client 或 TUI 代码变化；新增
  app-server 回归和 13 项聚焦全集足以覆盖直接因果面。前次 16 项范围外完整门禁失败继续如实保留，但不阻断 070。
- **维持前次边界决策。** 不扩改稳定 `thread/unarchive`，不建设通用 transport cancellation/reconnect，不修改 state/
  thread-store/rollout，也不吸收 069 内容。
- 本轮审查读取精确 diff、底层 keyset/cursor 调用链、回归源码和 retained JUnit；未重复运行重型 Cargo、Docker、真实 API/模型、
  测评、CI/PR 或远端操作。`git diff 2e8d027..bb60a04 --check` 通过，审查开始时实现工作树 clean。

## 交付状态

- 结论：`M4_C0_PROTOTYPE_PASS`。
- 分支仅含本地 070 实现、整改与审查提交；未合并、未推送。
- 后续只需按用户批准进入主线整合；后整合者应吸收届时最新 main 并运行受影响的相称门禁，不在 C0 内继续扩展正式 query/control。
