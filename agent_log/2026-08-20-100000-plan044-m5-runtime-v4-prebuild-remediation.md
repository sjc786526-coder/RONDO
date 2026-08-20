# Plan 044 / M-5 runtime-v4 正式门前收口

日期：2026-08-20 ｜ 分支：`worktree-044-multi-m5-real-workflow-and-nondegradation`

## 产品与判据修复

- 否决 runtime-v3 的假绿路径：required `team_inspect` 失败、残余 continuation、错 cursor/offset、
  continuation 总数变化与页集未覆盖 `total_entries` 均 fail-closed；fresh page set 可更新总数，optional
  `stats` 失败不污染只要求 dump/log 的合同。
- 彩排固定 dump/log `limit=3`，初始页与续页保持一致；两类都必须至少两页并走到 null，页数进入结果与归档。
- code-mode outer Fact 只允许同 cell 已完成受支持的非 canonical team-state nested tool，且 outer response 为
  terminal 的全 `InputText` 结果。绑定键改为唯一 `output_item_id`；Yielded、team-state/evidence-read-only、
  Missing/Unavailable、混合媒体、加密、空输出与取消结果均不铸证。recorder 覆盖 wait gap、seal 边界、
  call-id 复用、并发 abort、terminal/Missing/error/cancel 清理。
- `team_inspect` 响应报告实际有效页长；省略 limit 时为 20，不再误报硬上限 50。

产品修复提交：`0eee6dc5ee69f0eca9e1db350148c423a2b2bf67`。

## 构建、冻结与离线验收

- 共享 build-lock 定向 Rust：146/146 通过；metrics：
  `eval-data/build-metrics/plan044-runtime-v4-source-tests-20260819c/20260819-205140-1000-85962`；
  wrapper/final `status=0 stop=none cleanup=none`。
- measurement worktree `.claude/worktrees/044-m5-multi-bundle-measurement-v4` detached clean 于 `0eee6dc`。
  legacy musl 构建 metrics：
  `eval-data/build-metrics/rondo-multi-musl-0eee6dc5ee69f0eca9e1db350148c423a2b2bf67/20260819-205528-1000-93581`；
  CLI+host 构建 metrics：
  `eval-data/build-metrics/rondo-multi-musl-v8-0eee6dc5ee69f0eca9e1db350148c423a2b2bf67/20260819-213738-1000-63972`；
  两者均 `status=0 stop=none cleanup=none`，`verify-companion` / `verify-runtime` 通过。
- `multi-m5-runtime-v4` 实物：CLI `c64ff001fe7bec20c84a6bbea84f077ffffdcddc8b796b2f663513d5d7a6c631`；
  host `dc7a00d7ba249773a88bca0fa0c124cc03eb3d089814978ddd863ad6c1758d0f`；bwrap
  `77360cb751ccedc5971391444ac86a8a33c15b04d6b4a6fe45f5d25496e62c4c`；manifest
  `5fa958e058b9bbe9ddc1a834d0db137789689afa54201d7b780dfd80b3ac5f31`。
- 合同提交 `b078e285494fe49b796230fe2fa2668e6f150977`：loader 固定
  workflow-v5→runtime-v4→nondegradation-v5；clean-smoke-v5 为独立 1 run / `$23.10` 身份。
- `just eval-lock`、M-5 Python 定向 136/136、ready=true、loopback 通过。rehearsal：20/20 dispatch
  都是 code cell、0 Direct、全部 completed；dump 7 页/log 2 页，均 `limit=3` 到 null；明文 9、加密/未知 0，
  七谓词全真。成员 exec Fact 被成员首个 Version 引用，`team_evidence` 读回明文 observation。
- 独立子智能体逐字节核 bundle、锁关系、Rust 持久结果、ledger 隔离与原始 rehearsal trace 后给出付费前 GO。

## 唯一一次真实 clean smoke

运行：`m5-g1-smoke-finalv5`，独立 batch/lock/archive 均为 `multi-m5-clean-smoke-v5`；未运行 provider probe、
Docker、正式 Gate 1/2，也未创建 `$120` 正式账本。

- ledger 只有 1 个 run、20 个 request；全部 `attempt_count=1`、`usage_valid=true`、`status=settled`、
  `settlement_kind=usage_priced`。逐项计价和 run spend 均为 `$0.273138`，无 held reservation，
  `stopped=false`、`stop_reason=null`，低于 `$23.10` 硬上限。
- archive 只有 1 行：`evidence_kind=real_api`、`smoke_test=true`、`contract_attempt=false`、
  `counts_as_effective=false`、`outcome=completed`、`passed=true`；`infra_taint` / `trace_error` / stop reason 均为空，
  `conservative_exposure_usd=0`；明文 16、加密 0、未知 0，七谓词全真。
- 原始 trace：17 cells / 18 nested dispatch，18/18 requester=code_cell、18/18 completed、0 Direct。
  required dump `limit=50,total=25,next=null`；log `limit=50,total=7,next=null`。成员 exec 产生 `fct-2`，
  `ver-1.1` 唯一引用该 fact，成员随后 `team_evidence(fct-2)` 返回 available、producer=`/root/worker`、
  tool=`exec`，observation 含冻结 finding。dump 中 7 个 Fact 只对应允许的 spawn/wait/send_message 与成员 exec；
  team_publish/route/history/evidence/route_update/update 均未铸 Fact。
- 正式 archive 保持 26 行、SHA-256
  `9da1be523637aec61e67598fc61e6cad4c3191da40828f6d6e67595c3fe8f884`；正式 phase-b ledger/lock 不存在。
- 归档 `harness_dirty=true` 只因当时未提交项为 WBS/plan/agent_log；源码与 eval 已提交，不削弱该非正式 smoke 的
  冻结产品和 harness 提交身份。独立后审确认真实 smoke 有效、无 P0/P1，并判定技术上已完成正式门前准备。

## 最终边界

M-5 未通过；正式门 1 未启动/未通过；正式门 2 未启动；未创建 `$120` 账本，未运行 Docker。
本轮设施、冻结身份、离线验证、真实验证性 smoke 与独立审查均已完成，任务停在未来单独启动正式门 1 之前。
未发生资源不足，因此未使用新增的中间产物清理授权。
