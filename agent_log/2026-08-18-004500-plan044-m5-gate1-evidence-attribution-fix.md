# Plan 044 / Multi M-5 门 1 证据绑定修复

日期：2026-08-18 ｜ 分支：`worktree-044-multi-m5-real-workflow-and-nondegradation`
｜ 修复者：独立审查会话（用户指示直接修）｜ 上游报告：
`agent_log/2026-08-17-233000-plan044-m5-phase-a-remediation-rereview.md`（P1-3）

## 结论

复验发现的 P1-3 已修：门 1 证据现在按产出工具绑定，`exec_command` 回显伪造 JSON 不再能让门 1 通过。
一并落地上一轮 E4（dump 续页）。未进阶段 B，未花费任何费用，未跑 Docker 或真实 API。

## 修复

- `collect.py`：拆掉 `name in _INSPECT_NAMES or action in {"dump","log"}` 里的 `or` 兜底。
  dump/log 只认 `team_inspect` 的输出，唤醒信号只认 `wait_agent` 的输出。
  其它工具产出的"团队形状"负载记入 `unattributed`，永不参与判定。
- `predicates.py`：`CollaborationVerdict` 增加 `ignored_evidence`，把被忽略的来源暴露出来。
  它**不进** `reasons`，因此不会把一次合法通过翻成失败；作用是让失败可区分：
  是模型在伪造，还是 wire 形状变了需要改采集器。
- 指令模板第 7 步：要求跟进 `next_cursor` 直到为空（`MAX_OBSERVE_LIMIT = 50`），
  并明确"只有真实 `team_inspect` 输出算证据，不要用别的工具转述"。`instruction_sha256` 同步重算。
- 工作流锁 `evidence_source` 增加 `attribution: required` 并把上述规则写进 notes。

## 实测确认的 wire 形状（无 API，冻结二进制 + 本地 SSE stub）

修之前先确认"绑定工具名"不会把门 1 变成永远过不了，这几条是实测结论，不是推断：

- 这套配置走 Responses Lite：请求体 `tools` 为 `null`，工具声明放在 developer 的
  `additional_tools` 项里。因此"wire 上有没有 tools 数组"不能用来判断工具是否可用。
- 团队工具以 `name="team_inspect"` + `namespace="collaboration"` 的 function_call **直接调用即可执行**，
  CLI 写回的 `function_call_output` 正文就是真实 dump 负载
  （`{"action":"dump","instance":…,"revision":…,"entries":[…]}`）。**不带 namespace 会返回
  `unsupported call: team_inspect`。**
- `non_code_mode_only` 取 true 或 false 都能这样执行。差别只是 true（产品默认，`DirectModelOnly`）
  会把团队工具移出 code-mode 嵌套面（`code_mode_tool_names` 22 → 8），false（`Direct`）两边都挂。
  既然两种取值下证据都可归属，**本次不改门 1 运行配置**，维持执行者冻结的 false。
- `features.code_mode_host` 的开关不改变上述声明与执行形状。

## 验证

- `tests.test_multi_m5`：28/28（新增三项：真实 namespaced 调用被接受、`exec_command` 回显被拒并计入
  `ignored_evidence`、唤醒信号只认 `wait_agent`）。
- 两个反例脚本重跑：Root 独角戏 `passed=False`；伪造回显 `passed=False`（修前为 `True`）。
- 完整离线 `just eval-test`：854 项，仅 2 项既有 Local 加载失败
  （`test_l6_b10333_pair`、`test_local_m4_holdout_anchor`，干净 `main` 同样复现，与本任务无关）。
- `just eval-multi-m5-loopback`：通过，`loopback_tool_round_trip=true`。
- 未跑 Rust（`multidev/` 零改动）、未跑 Docker、未调用真实 API、未产生费用。

## 边界

- 仍未进入阶段 B。真实付费需要用户另行明确授权；在此之前即使做阶段 B，也只做离线前置准备。
- 门 1 runner 与门 2 交错执行面仍未实现，这是阶段 B 的前置工作。
