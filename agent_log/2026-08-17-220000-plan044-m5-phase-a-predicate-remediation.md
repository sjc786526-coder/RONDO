# Plan 044 / Multi M-5 阶段 A 门 1 窄整改

日期：2026-08-17 ｜ 分支：`worktree-044-multi-m5-real-workflow-and-nondegradation` ｜
基线审查：`76ea82d` ｜ 报告：`agent_log/2026-08-17-210000-plan044-m5-phase-a-independent-acceptance.md`

## 结论

审查 P1-1、P1-2 成立，已修。P2-3/P2-4/P2-5 一并落地。未进阶段 B。待独立复验。

## 改动

- 门 1 谓词改为先按 dump 顺序切 Event，再在**同一个 Event**上合取。反例：Root 在 e1 独角 + 成员 Version 挂 e2，失败。
- `root_resolved` 只认成员作者 Version。新增 `root_woken`：inspect log 对 Root 的 `signalled`，或 JSONL 里 TeamActivity 原文。mailbox 的 `Wait completed.` 不算。
- dump 从 `codex exec --json` 工具输出采集，不读 `TEAM_REPORT.md`。
- 成员模型：`agents.default_subagent_*` + `expose_spawn_agent_model_overrides=false`（比只设默认更钉死）。
- 门 2 锁写入归因边界：比较的是上游 V2+团队状态 对 上游默认 V1。

## 与审查建议的差异

- Event 归属不读测试夹具里的 `event_id`：真实 `DumpEntry::Version` 没有该字段，按 `TeamStore::dump_entries` 顺序分组。
- 成员模型不只补默认值：关掉 spawn schema 的 `model`/`reasoning_effort`，否则模型仍可覆盖。

## 验收

- `tests.test_multi_m5` 20/20；adapter 安全命令 1/1；`MultiProductFreezeTests` 10/10。
- 未跑 Rust、Docker、真实 API。未合并、未推送。
