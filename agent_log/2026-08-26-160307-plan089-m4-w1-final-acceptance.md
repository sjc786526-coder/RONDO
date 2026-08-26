# Plan 089 / M4-W1 最终独立验收

## 结论

- 最终实现对象：`eb4a3bb8530f25632affe7d0bae2f2fec3f6323a`。
- 技术验收结论：`ACCEPTED / TASK_TARGET_COMPLETE / READY_FOR_INTEGRATION`。
- W1 产品合同、M4-S2/S/C 兼容、fresh 正式组合链和四轮独立审查整改均已闭合；没有未关闭的高/中等级
  correctness 或 security finding，也没有必须转移给 M4-W2、兼容补丁包或无编号收口任务的缺口。

最终 `M4_W1_PASS / PHASE_4_COMPLETE` 仍以本报告之后同一审查流程成功完成最新 `main` 整合与 `origin/main` 推送为生效边界。

## 最终复验

- R4-F1 已关闭：bound durable close 在 no-restart quiescence 后、不可逆 persistence 成功边界前失败时，late revoke 分支会先随
  `Err` 释放 admission fence，persistence failure 分支会显式释放 fence；两者随后撤销 shutdown marker，再通过既有
  pending-work 入口恢复调度。首次 revoke 失败仍发生在 abort 前，成功关闭继续把 fence 保持到 runtime teardown，普通
  Interrupted 与 task-admission 主流程未改变。
- 两条生命周期回归都使用临时 linked-worktree metadata、managed workspace-write authority 和 production binding revalidation，
  并通过真实 `spawn_task` 断言 active task 已安装。late revoke fault 精确越过 pre-abort revoke 与 abort cleanup 后命中第三次
  confirmed revoke；断言 `RetainedError`、persistence 可写、Root close 可重试、marker/fence 回滚和 pending trigger 重新接纳。
  成功回归继续断言 terminal close 后 pending work 不重启、persistence 确实关闭且 admission 拒绝。
- 聚焦 Nextest `42450a18-8595-49d1-aa6e-9be035a82069` 为 `2/2`，watchdog
  `20260826-155459-1000-454690` 为 `final_rc=0 / stop=none / cleanup=none`，JUnit SHA-256 实算为
  `7ff1f84b38f41a440ee482b58061ffe4f53ff423184b2a9d28f9c4ecc2e70c9a`。core scoped clippy watchdog
  `20260826-155649-1000-459061` 也为 `final_rc=0 / stop=none / cleanup=none`；fmt-check 与 diff-check 通过。
- 上一轮已直接核验并接受的 frozen fresh app-server OS process replacement + unique offline Critic 正式链继续有效：它从 fresh
  repository、两个 linked worktree、Session/store 开始，覆盖隔离写、scoped 外写、cold resume、重验、失效/replacement、继续
  Team mutation、Query/Control 和 lifecycle，并断言 Critic 恰好一次实际调用。最终窄修仅触及 persistence 成功边界前的失败回滚，
  未改变该成功路径，故未重复运行重型正式链。

## 审查者替用户作出的决定

- 接受 canonical full workspace `just test` 已按要求尝试一次、但在测试前被 rusty-v8 v150.4.0 prebuilt archive HTTP 404 阻断的
  归因；该轮不计通过。宽邻接剩余的规划基线 cwd/空 rollout/Realtime 问题也不冒充通过，不构成 W1 新回归。
- 接受为关闭正式 finding 而发生的两次精确 `069 target/debug/incremental/` 清理；两次均记录前后体积且未扩大到 deps、其它 cache、
  训练或来源不明资产。最后一轮未删除文件。
- 接受最终失败回滚聚焦门禁在默认 Windows 50GB preflight 停止后，按用户原始指令仅以命令级 35GB 临时门继续；实测余量约
  49.97GB，未快速趋近 35GB，未改变长期配置。
- 接受正式链仅移除宿主代理变量以直连 `127.*` 本地 fake 的离线处理；未修改生产配置、未访问真实 API/模型或外部网络。
- 不要求追加 full workspace、宽邻接、完整 clippy 或再次运行正式链；现有聚焦证据与成功链足以支持最终验收。
- binding 状态/失效展示和 replacement TUI 可作为未来未排期增强；生产 binding、scoped authorization、replacement、恢复与完整
  lifecycle 入口均已完成，不能把任何核心缺口伪装成该可选项。

## 整合边界

审查者已获用户明确授权在最终验收通过后更新 `doc/WBS.md`、`doc/WBS/durable-team-runtime.md`、
`doc/WBS-COMPLETED.md`，提交并整合最新 clean `main`，推送 `origin/main`，随后把完成分支归档为 `zz-done/...` 并保留 worktree。
不得读取、合并或依赖尚未进入主线的 Plan 087 成果；若远端或本地 `main` 在整合前变化，必须加法式保留其权威状态。
