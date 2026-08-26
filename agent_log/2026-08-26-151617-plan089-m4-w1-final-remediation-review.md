# Plan 089 / M4-W1 第二轮整改终验

## 结论

- 终验对象：`c6d5c71cb3452a1ed8e98b72865297663ad1cda1`，上一轮审查提交 `60e973b`。
- 结论：`REVIEW_NOT_ACCEPTED / TASK_TARGET_NOT_YET_COMPLETE / PENDING_FINAL_LIFECYCLE_FIX`。
- 上一轮四项 finding 的目标语义均已关闭，六条聚焦回归和最终 fresh 正式链证据可信；但 durable close 的新 quiescence 接线存在
  一个可直接触发的高等级 task-admission 竞态。除此之外，本轮未发现新的高/中等级问题。

审查者未运行 Cargo。直接核验 `20260826-150914-1000-383202` 为 `final_rc=0 / stop=none / cleanup=none / 1 passed`，
JUnit SHA-256 确为 `38afc34651ff961cedd1d27c917b1668ad2c107fd3820682fd65f4dc58b5497a`；六个聚焦 watchdog 也均为
`final_rc=0 / stop=none`。

## 唯一剩余阻断

### R3-F1 — High：durable close quiescence 会自动重启 pending turn

`core/src/session/handlers.rs:594-614` 的 pre-persistence quiescence 先 confirmed terminate processes，再调用
`abort_all_tasks(TurnAbortReason::Interrupted)`，最后第二次 terminate late process。问题是普通 interrupted abort 在成功清除 active turn 后，
`core/src/tasks/mod.rs:498-532` 会调用 `maybe_start_turn_for_pending_work`；若存在 trigger-turn mailbox 或 durable-sleep pending work，
`:475-495` 会立即 reserve 并启动新的 `RegularTask`。

第二次 process terminate 只能清理该时点已经创建的进程，不会终止这个新 task。随后
`RuntimeShutdownMode::BoundWriterAlreadyQuiesced` 使 `core/src/session/handlers.rs:617-639` 跳过再次 abort，而 durable close 在
`:743-748` 关闭 canonical persistence 并继续成功收口。新 task 因而可能在 persistence shutdown 后继续运行，甚至再次 spawn process。
这违反 terminal lifecycle 不遗留可继续 mutation 的 binding/task，也会让成功关闭结论不诚实。

最窄修复边界：durable shutdown quiescence 应使用“中断 active task、但禁止 pending-work 自动重启”的现有/专用 abort 模式，并把 task
admission fence 保持到 runtime teardown 完成。无需新增 scheduler 或生命周期体系。建议新增一个 bound durable Root 场景：active turn +
trigger-turn mailbox（或 durable sleep pending work）进入 close，断言 pending turn 未启动、persistence 关闭前无 active task/process、close
结果诚实。可再加一个普通非 shutdown interrupted 行为仍自动续跑的断言，避免改变 W-off/既有 mailbox 语义。

## 已接受的最终整改

- local PTY confirmed terminate 已传播 kill 错误；失败时保留 killer、helper tasks 与 manager handle，成功后才移除。
- Forked current settings 使用 strict append/persist/flush；最新 `binding=None` 同时 tombstone core binding 和 app-server authority roots。
- bound active turn 拒绝 authority-relevant 更新；idle 更新推进 runtime revision，旧 TurnContext 在 admission/tool execution 前失效。
- process revoke 失败会在 canonical persistence shutdown 前返回并 abort close permits，保留 Root authority 与可写 persistence。
- F1–F7 其余整改、Critic 恰好一次调用、正式链离线代理处理、第二轮未清理文件及当前资源记录均接受。

## 审查者替用户作出的决定

- 不要求重跑 full workspace、完整 clippy 或历史矩阵。修复后只需新增 shutdown+pending-work 聚焦回归、必要 core fmt/clippy/diff，随后从
  冻结代码再跑一次唯一 fresh app-server OS + offline Critic 正式链。
- 当前 Windows C: 仍仅略高于 50GB。若 monitored Cargo 实际触发 50GB 门，继续沿用上一轮已记录的用户原始 35GB 临时例外：先停止
  触发命令，确认余量高于 35GB 且未快速下降后才继续必要门禁；达到或快速逼近 35GB 立即停止。不得扩大清理范围；本轮不预授权任何
  新的删除目标。

完成该唯一窄修并提交后，按既定 Codex queue 再请求终验。修复前不更新 WBS、不整合、不推送，不宣告
`M4_W1_PASS / PHASE_4_COMPLETE`。
