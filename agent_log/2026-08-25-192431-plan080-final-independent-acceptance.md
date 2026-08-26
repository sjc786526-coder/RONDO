# Plan 080 / M4-C2 最终独立验收

时间：2026-08-25 19:24 PDT ｜ 候选提交：`6865a649af11f8f93e069f436a8db855dad272cb`

## 结论

**验收通过，任务目标完成，结论为 `M4_C2_CONTROL_PASS`。** 第二轮整改已关闭上次复验报告中的 3 个 Medium 与 1 个 Low；本次限定
正确性、功能性和局部回归复验没有发现新的 High、Medium 或 Low finding。

## 复验结果

- active Archive 与 active/archived Delete 的 query availability 已和 server admission 统一：本 server 有 canonical Root 或完全冷态时
  才可操作，loaded descendant/no Root 明确 unavailable，未知 residency 保持 unknown。owner incarnation 变化统一分类为
  `NotCurrentOwner`。
- formal shutdown 被 Session loop 接受后，completion sender loss、loop-first 与不可回滚 terminal completion 均进入 typed Unknown；仅
  显式 `RetainedError` 保留可回滚、可重试语义。app-server 只用 exact-owner removal 退休旧 mapping，same-ID replacement 不受影响，
  mutation 不自动重放。
- Close 与 active Archive 的 after-preflight Team commit 测试将竞态放在 server proof preflight 之后、M4-S2 最终线性化点之前，确认 stale
  control 被拒绝、获胜 Team commit 与当前 Root owner 保留。doc-hidden in-process hook 默认不安装，不改变生产控制路径。
- client/TUI 继续从同一 query availability 做 preview；unavailable/unknown 不进入确认，terminal Unknown 沿既有 stale→权威 query
  resync 路径收敛。control-only attachment、send-once、response-loss/no-replay 与 delete retry anchor 未被本轮窄修破坏。

## 证据

- 冻结代码正式窄轮 watchdog `20260825-190752-1000-1587834`：JUnit `13/13`、0 failure、0 error、无重跑，SHA-256
  `efe7843fbe6ad611b8a5b12b182d94783b208ad43d8dc9d6f45e357b2ce6e6b6`。覆盖 query residency 2 项、after-preflight
  race 2 项、owner replacement 1 项、accepted handoff 3 项、typed Unknown 1 项、app-server cleanup 3 项及真实 ThreadManager
  exact-owner 原语 1 项。
- scoped fix `20260825-185839-1000-1564505`、clippy `20260825-190308-1000-1575968` 均为 rc 0，三个 watchdog 均
  `stop=none / cleanup=none`。live `git diff --check` 通过，无 `.snap.new`。
- 原 `45/45` 合并树 query×lifecycle、`17/17` 正式控制、`47/47` 邻接回归、fresh Session/store、schema 与 snapshot 证据在原覆盖
  范围继续有效。本轮没有协议或可见 UI 变化，直接因果窄轮已经覆盖整改点，因此决定不重复运行这些重型门禁、schema generator 或
  full workspace。
- 复验前 worktree clean；main 仍为 `0d842e0f568791765eed4eced46674b55ae0106e`，origin/main 仍为
  `305f9049ffabdb8c4a2b6cf4d1df45720eb5b1a1`。未合并、未推送、未读取或修改 079 现场。

## 代用户作出的决定

1. 接受 `6865a64` 为 Plan 080 最终产品候选，并以本报告完成独立验收；无需第三轮整改。
2. 接受“生产 helper + 真实 ThreadManager exact-owner 原语”的轻量组合回归，不为本任务扩建完整 crash E2E 或新的审计设施。
3. M4-Z(core) 因 M4-C2 验收通过而解锁，但仍须另行制定计划和取得授权；本次不提前实施。
4. 保持任务分支本地 clean 提交，不合并、不推送、不关闭或重命名 worktree。

## 最终状态

- 验收：**通过**。
- 任务目标：**完成**。
- 结论：`M4_C2_CONTROL_PASS`。
- 未决 correctness/functionality finding：无。
