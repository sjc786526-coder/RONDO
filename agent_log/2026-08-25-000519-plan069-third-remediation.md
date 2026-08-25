# Plan 069 第三轮 correctness 修复

第三轮独立复验提出的两项中等级 finding 均确认存在，并在 Plan 069 原边界内关闭：

- canonical Root write permit 现可在唯一 writer authority 内读取并验证 `SessionMeta`。已激活 Session 的 committed read、close 和
  mutation 持续复核 marker；CAS 在替换 snapshot 前后均验证，marker 丢失、损坏或读取不可用不会返回 durable success。
- projection 与 wait 不再把 activation、reconcile 或 snapshot 的持续不可用降级为无 Team/正常等待；仅 feature-off 和合法非 participant
  保持原有空结果语义。
- rollout 增加与异步读取语义一致的 blocking `SessionMeta` head reader，并覆盖 plain/compressed 文件在无效 UTF-8 tail 前停止的行为。

验证：

- `just fmt`、`git diff --check`：通过。
- core marker-loss、projection、wait 聚焦回归：3/3 通过；watchdog
  `.codex/build-watchdog/20260824-235943-1000-1500748`，`complete`、退出码 0、`stop_reason=none`。
- rollout/thread-store/team-state 聚焦回归：26/26 通过；watchdog
  `.codex/build-watchdog/20260825-000119-1000-1510814`，`complete`、退出码 0、`stop_reason=none`。
- 调试中有限次数故障注入会在启动阶段耗尽，已改为可复位的持续故障 fixture；本机代理曾使 loopback wiremock 返回 502，最终轮仅为
  runner 设置 loopback `NO_PROXY`，未削弱产品逻辑或断言。为 071 资源交接主动中止的一次 wrapper 不计入通过证据。
- 按独立复验决定，本修复轮未重跑完整 workspace 或 clippy；既有历史证据不改算为本轮结果。

状态：`IMPLEMENTATION_COMPLETE / PREACCEPTANCE_REVIEW_PENDING / FINAL_PASS_BLOCKED_BY_#37198`。未进入阶段 E，未处理 `#37198`，未合并、
推送或使用 Docker/真实模型；069 重型 Cargo 资源和相关进程已全部释放。
