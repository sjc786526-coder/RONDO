# Plan 074 外部复验

## 审查对象与结论

- 审查提交：`8c60ad4ae411d6f314c0432dc6531e8bab8d5fb8`，基于原实现 `bf8b7da6a7a4bc1db962c1f5a4b97dc55267673c`。
- 结论：**ACCEPT**。上一轮 M-1 已正确关闭，未发现剩余高/中等级 correctness finding。
- Plan 074 的本地实现、聚焦验证与外部验收目标已经完成；仍未合入或推送 `main`，也未执行 Plan 069 阶段 E。

## M-1 关闭证据

- rollout 读取已拆分为 lineage/content 提取与最终 cwd projection 校验。read-by-path 不再在 SQLite overlay 前拒绝空/相对 rollout cwd。
- persisted metadata 只有在其 rollout path 可解析且与请求 canonical path 完全相同时才参与合并；有效 persisted absolute cwd 可成为最终
  projection，并用最终 cwd 重算 legacy permission。
- matching metadata 不存在、不可解析或指向另一 rollout 时不会救济当前 rollout；最终 cwd 无效仍在公共出口 fail-closed。
- read-by-ID 的 history lineage 探测也使用无提前 cwd 裁决的读取，随后仍由 SQLite projection 的最终校验保证输出合法；legacy resume
  按 rollout path、`include_history=true` 消费的正是已修路径。
- 新回归覆盖 rollout cwd 为空和相对两种场景，验证 matching persisted cwd 下 ID/path history、cwd 和 permission 一致；随后把 metadata
  指向另一 rollout，验证 mismatch 明确失败。

## 复核的验证证据

- 新回归 1/1：watchdog `20260825-023249-1000-2035054`，JUnit SHA
  `7c3d0478a5ecda2e4de0acae7d8870bfd6b0ae6c8b765660c3e6d6b9e31693d4`。
- `codex-thread-store` 191/191：`20260825-023312-1000-2036697`，JUnit SHA
  `63cf8ff2515910313661dfccf6bf936d72241450c6bfcec838cdb74becf9a138`。
- app-server read/list/resume 2/2：`20260825-023330-1000-2039385`，JUnit SHA
  `5c6fa5b3c8a5db950db0d8da1f1fc2743e770ea4ba26d935a425c08fc2872616`。
- ThreadStore clippy：`20260825-023438-1000-2049137`，退出码 0；执行者记录的 `just fmt` 与 `git diff --check` 通过，当前提交 diff check
  复核通过。
- 本轮代码审查与现有精确 JUnit 已足够闭合 finding，未重复启动 Cargo 或扩大测试范围。

## 代用户决策与非阻断项

- 保留 state-only list 对无法证明 cwd 的 fail-closed 语义，不增加 repair、隔离、registry 或审计设施。
- 069 mock `/responses` 502 与既有 core clippy 阻断继续视为已披露的非 074 问题；不要求本任务修复或重跑全 workspace。
- 无需用户追加技术决策。后续只剩获批后把 074 独立整合进 `main`，再由 Plan 069 按自身合同执行阶段 E；本结论不等于
  `M4-S1 PASS`。

## 当前状态

- 验收：`ACCEPTED`。
- 任务目标：`COMPLETE`。
- 项目阶段：`PLAN_074_COMPLETE / MAIN_INTEGRATION_PENDING / M4_S1_STAGE_E_PENDING`。
