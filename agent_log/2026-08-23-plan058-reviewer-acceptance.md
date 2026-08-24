# Plan 058 reviewer acceptance

## 结论

- 验收状态：**不通过**。
- 任务目标：**尚未完成，但可在不重跑正式 campaign 的前提下窄修闭环**。
- Plan 058 `formal-v6` 的 20/20、预算、C2 分类和 `retain` 历史结论本身有效；当前阻塞位于正式运行后的最终产品分支与少量交付收尾，不应作废、改写或重跑正式结果。

## Findings

### P1：repeat guidance 实际泄漏到普通非 root agent

最终日志和 ExecPlan 分别声称启用态“只给 main agent”以及“只在 RONDO Local main”接入，但
`mydev/codex-rs/core/src/tools/spec_plan.rs:877-906` 的 `add_shell_tools()` 只检查 feature 开关。
`add_core_tool_sources()` 仅在 `:817-847` 对 Guardian 特判；普通 `ThreadSpawn`、Review、Compact、
MemoryConsolidation 等非 root session 仍会进入 `add_shell_tools()`。这些 agent 又从
`mydev/codex-rs/core/src/agent/control/spawn.rs:477-489` 继承同一 config，因此也会收到 guidance。

这扩大了未被 formal-v6 验证的 requester 范围，违反本任务冻结的 main-only 产品边界。现有测试只覆盖
Guardian 例外，没有覆盖普通非 root agent。应使用已有
`SessionSource::is_non_root_agent()`（`mydev/codex-rs/protocol/src/protocol.rs:2900-2904`）或等价的架构内判定，
把 guidance 收紧到 root agent，并补普通 ThreadSpawn/内部 agent 的回归。修复不得影响 Guardian、legacy shell、
feature-off 或工具执行语义。

### P2：缺少 agent-logic 的最小 integration regression

当前只在 `spec_plan_tests.rs` 检查直连 `exec_command` spec。`mydev/AGENTS.md:113-119` 要求改变 agent logic 的
feature 在 `core/tests/suite` 增加 integration test；CodeModeOnly 把嵌套 tool 描述重新组装进 model-visible exec
prompt 的路径也没有锁定。应补一个聚焦请求体/工具计划回归，覆盖 root feature off/on、非 root 不接入，以及实际
支持的 Code Mode 暴露路径。无需新增测试平台，也无需跑全 workspace。

### P2：Phase A tracked 来源字段混淆两种 lock

`eval/results/observations/plan058-direction1-c2-phase-a-2026-08-22.json:5-7` 的 source 指向 Plan 056
`formal-v6`，但 `lock_sha256` 填的是 v28 task lock `a9567c...`。Plan 056 formal-v6 campaign lock 实际为
`263cc3...`，且其公共结果已明确区分 campaign lock 与 v28 lock。该歧义不推翻已核对的 `1/8/0` 分类，但应把字段
改为清楚的 `campaign_lock_sha256=263cc3...` 与 `v28_lock_sha256=a9567c...`，并同步直接相关测试/引用。

### P2：资源和 ExecPlan 当前状态尚未完全收尾

- `git worktree list` 仍注册四个 Plan 058 clean detached measurement worktree：两个位于
  `.claude/worktrees/`，两个位于 `eval-data/work/`，合计约 701 MB。正式 campaign、binary、manifest、预算和证据
  已另行保留。执行者应先机械确认无交付引用，再用精确的 `git worktree` 入口清理；若确有恢复用途，则必须在最终
  日志说明用途和结束条件，而不能把它们当成无说明残留。
- ExecPlan `当前验收状态` 中仍保留多处已经完成的“待 diagnostic/提交”表述，与同文件的完成状态冲突。应改成
  历史时点叙述或删去过期待办，保持 plan 作为最终任务合同的当前状态一致。

## 已代用户作出的决策

1. **保留 formal-v6 为有效正式结果，不重跑真实 API、Docker、题目或 round。** 20 条正式记录、冻结源码/lock、
   预算和结果已闭环；上述产品修复只是把未正式覆盖的非 root recipient 排除，是非材料收窄，不改变正式 main 行为。
2. **feature 在复验通过前继续保持 UnderDevelopment、默认关闭。** 不撤销 formal 的 `retain` 历史结论，但当前 HEAD
   不能作为已验收产品交付。
3. **整改只做上述窄修和交付收尾。** 不新增审计/可信平台，不重建正式测评，不运行全 workspace；Rust 只尝试最小
   相关 integration/unit 门禁并继续使用 canonical build lock/watchdog，若环境仍在 Cargo 前 fail-closed，保留证据、
   不绕过资源门禁。

## 复核证据

- 工作树在写入本报告前 clean，HEAD 为 `46fe38f`；main clean，Plan 058 与当前 main 从共同基线起没有重叠修改路径，
  三方 merge-tree 未发现冲突。未合并、未推送、未归档。
- `formal-v6` status 为 finalized、20/20 published、225 upstream attempts、1 次 transport retry、
  `4.985650 USD`、reservation 0。Plan 058 16 个 closed identity 合计 `20.379152 USD`，未超过 50 USD。
- 20 条 record 的 Terminal-Bench、API metadata、native trace、Guardian evidence、agent receipt 和 source digest
  均通过只读重验证；从 retained state、预算、records 和 refined classification 重生成公共结果，与 tracked JSON
  完全相同，规范化 SHA-256 为
  `40e894bb51caf70e1062717d2f0dce07e6de91a8bb70c909eeb72b59be864fcc`。
- raw C2 `7 / 4 slots / 3 tasks / 9,693 ms` 与私有记录一致；七次抽查均有状态变化、失败恢复或修改后复测依据，
  refined `0/7/0` 合理。唯一第二次物理执行是已分类的 pure transport，同一逻辑槽恢复，不是有效失败重跑。
- 本轮复跑六个相关 Python 模块，共 `262/262` 通过；`git diff --check` 与 Git connectivity 检查通过。未运行
  Cargo、Docker、真实 API、全 workspace、CI、PR、本地模型或训练；没有读取 `.env.local`。

## 复验门

执行者完成 P1、三个 P2 及相应最小回归后，提交精炼执行摘要并交回同一审查者复验。复验重点只检查作用面、
model-visible tool path、Phase A 字段、计划/资源收尾和局部回归，不扩大正式实验或可信设施。
