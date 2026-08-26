# Plan 089 / M4-W1 最终生命周期整改复验

## 结论

- 复验对象：`985018be0457d9d599a228c86188fbedfaf86140`，上一轮审查提交 `a396b3e`。
- 结论：`REVIEW_NOT_ACCEPTED / TASK_TARGET_NOT_YET_COMPLETE / PENDING_FAILURE_ROLLBACK_FIX`。
- 上一轮唯一的成功关闭竞态已经关闭：task-admission permit 从 idle reservation 保持到 task install；bound durable close
  持有同一 fence 到 runtime teardown；shutdown 专用 abort 不再自动接纳 pending work，普通 Interrupted 行为未改变。
- 但本轮发现一个中等级失败回滚缺口。除此之外，没有新的高/中等级 finding。

审查者没有运行 Cargo。独立证据复核确认聚焦 shutdown 回归为 `1/1`，最终 fresh app-server OS + unique offline Critic 正式链为
`1/1`，run id 为 `0041026b-2574-4c36-9bdc-6813fc5219a6`，JUnit SHA-256 实测为
`7ff58d6e6971654c1e6ad374698bfbd4534c364cee95f377596e90e00b8fdcef`；这些证据支持成功关闭路径，但没有覆盖下面的失败回滚。

## 唯一剩余阻断

### R4-F1 — Medium：no-restart quiescence 失败回滚不会重新唤醒 pending work

`core/src/session/handlers.rs:596-624` 在 bound durable close 中取得 task-admission fence，执行第一次 confirmed process revoke，随后以
no-restart 模式 abort active task，再执行第二次 confirmed revoke。这个顺序正确地阻止了成功关闭时 pending trigger-turn 或
durable-sleep work 越过 quiescence。

问题出现在 close 尚未越过不可逆 persistence 边界而失败时：

- 第二次 confirmed revoke 失败会从 `quiesce_bound_writer_before_durable_persistence` 返回错误；fence 随之释放，close permits 和
  shutdown marker 被回滚，但此前 no-restart abort 已经有意跳过 pending-work wakeup。
- quiescence 成功、随后 `live_thread.shutdown()` 返回错误时，错误分支同样回滚 close permits 和 marker；`RuntimeShutdownMode` 中的
  fence 最终会释放，但仍没有重新触发 pending work。

`finish_failed_experimental_session_control_shutdown` 只递减 shutdown-in-progress 计数，不负责调度。结果是 Root authority 和
persistence 虽按失败语义保留，close 前已排队的 trigger-turn/durable-sleep work 却会无限沉睡，直至另一个偶然外部事件再次触发
`maybe_start_turn_for_pending_work`。这不是越权或数据损坏，但违反“失败后保留可用 Root/runtime”的生命周期合同，故定为 Medium。

最窄修复边界：在这些已经执行 no-restart abort、但尚未越过不可逆 persistence 边界的失败回滚路径中，确保先释放 task-admission
fence、再清除 shutdown marker，随后调用既有 `maybe_start_turn_for_pending_work`。该调用仍会经过现有 idle admission、binding
revision、permission/trust 和 shutdown marker 检查；无需新增 scheduler、持久状态或第二套生命周期权威。第一次 revoke 尚未 abort
时失败也可统一经过同一安全唤醒入口，active-turn admission 会自然拒绝，不需要复杂分支。

建议至少增加一个 fault-injection 聚焦回归：active task + pending trigger-turn（或 durable sleep），让 no-restart abort 之后的第二次
revoke 或 persistence shutdown 确定失败，断言 close 诚实失败、Root/persistence/authority 保留且 pending work 在 marker/fence 回滚后
重新被接纳。成功 close 不接纳 pending work 的现有回归必须继续通过。

## 审查者替用户作出的决定

- 本问题只允许窄修既有失败回滚，不要求重构 shutdown、增加审计设施或扩建调度体系。
- 修复后只需运行新失败回滚回归、现有成功关闭回归，以及相称的 core fmt/clippy/diff 门禁；不要求重跑 full workspace、宽邻接或
  历史矩阵。
- 若修改严格局限于不可逆 persistence 边界前的失败回滚，并由上述聚焦测试证明，当前成功路径的 frozen fresh 正式链证据可以继续
  接受，不要求再次运行重型正式全链。若修复触碰成功路径、persistence 成功边界或 task admission 主流程，则仍需重新跑一次正式链。
- 当前不更新 WBS、不整合、不推送，也不宣告 `M4_W1_PASS / PHASE_4_COMPLETE`。完成该唯一 finding、提交并保持 worktree clean 后，
  通过既定 Codex queue 再请求终验。
