# Plan 044 / M-5 阶段 B：第五轮独立审查整改

日期：2026-08-19 ｜ 分支：`worktree-044-multi-m5-real-workflow-and-nondegradation`
范围：审查报告 9 项（5×P0、4×P1）全部核实并修复；另发现并记录 1 项审查未覆盖的结构性风险。

## 结论口径（先说这个）

**M-5 仍未通过，门 1 未通过，不存在任何「未见退化」的结论。** 本轮没有花掉 $120 账本里的任何一分钱，
该账本文件仍不存在。本轮未拉取 Docker 镜像、未加载本地模型、未训练、未推送远端；`.env.local` 只做存在性与
权限的静默检查，未打开内容。

## 核实结果

审查报告 9 项**全部属实**，均已复现后修复。其中两项是结构性阻断，会让门在真实运行下必然失败或错误通过。

### P0-1 门 1 证据口径在 code-mode 下不可用

用 2026-08-18 冒烟留下的真实抓包复核：模型发的是 `custom_tool_call(name=exec)`，input 是
`const r = await tools.collaboration__spawn_agent({...}); text(JSON.stringify(r));`，
请求体里 `tools` 字段为 `None`、顶层 `function_call` 数为 0。冻结判据只认
`function_call` + `name=team_inspect`，**结构上不可能看见任何协作**。

阶段 A 那次「实测确认 wire 形状」用的是直接注入 function_call，结论对，但那不是真实模型的调用方式。

**修法**：采用审查建议的 rollout-trace 口径，但落点比建议更保守——完全不解析 JS、也不采信
`custom_tool_call_output`（两者都由模型作者控制）。新增 `multi_m5/trace.py` 读冻结二进制既有的
trace bundle（`CODEX_ROLLOUT_TRACE_ROOT`，产品已有能力，**未改产品代码**）：

- 证据只来自 Rust dispatch 侧写下的 `ToolCallStarted/ToolCallEnded`——注册表看到的工具名、namespace、
  参数，以及 handler 返回给 JS 的值。
- 每条 dispatch 必须绑定回抓包里模型真实发出的 code cell（`model_visible_call_id` 对上，
  `source_js` 是该 cell input 的子串），否则拒绝。这挡住「拿另一次运行的 bundle 来充数」。
- bundle 缺失/重复、seq 重复、cell id 在同一线程内重复、dispatch 没有结束事件、payload 路径逃逸——一律
  fail-closed，并记为 `infra_failed` 而不是 `agent_failed`（证据管线坏了不是产品失败，不该吃掉一次尝试）。

冻结 `multi-m5-workflow-v2`；v1 归档不得充当 v2 证据。**彩排 stub 同步改成真实 code-mode 形状**——这是
第四轮交接特别提醒的一点，只改采集不改 stub 等于把同一个错误再犯一遍。

配 20 条对抗回归：脚本只打印伪造 dump、把调用放进 `if(false)` 死分支、换错 namespace、别的工具回显团队形状
负载、失败的 dispatch、跨 run 重放、source 不匹配、孤儿 cell、重复 seq、payload 越界、caller dump 走私。

### P0-2 门 2 实际 adapter 仍跑 sol

复现属实：预算代理取锁里的 terra，`make_run_spec` 却仍走宿主 `paid_eval.main_model` 别名（sol），
adapter argv 里是 `relay/gpt-5.6-sol`。真跑会被 terra 代理本地拒掉，两侧若都被 Harbor 记成 `agent_failed`，
当前判定仍可能得出 `passed=true`。

**修法**：`TerminalBenchRequest` 新增 `pinned_model_id` / `pinned_subagent_model` / `pinned_subagent_effort`，
贯通 `make_run_spec → adapter argv → proxy`；未设置时保持历史投影不变，所以既有单智能体 campaign 不受影响。
Docker 启动前用 `require_pinned_model` 逐字段比对 spec / adapter / argv / proxy，不一致直接 `Gate2Error`
（harness 错误，不是产品观察）。就绪自检离线构造两侧 prepared run 做同样比对。

顺带修掉一个同源问题：上一轮把全局 `AGENT_DEFAULT_SUBAGENT_MODEL` 整体从 sol 翻成 terra，
这会静默改写本机**每个** Multi campaign 的成员身份——和当初 `paid_eval.main_model` 的错误一模一样。
已恢复为 sol，M-5 从自己的锁显式传入。

### P0-3 $120 不是严格上限

算出来核实：通用 Usage 合同（1,050,000 / 128,000 token）下 terra 单请求最大合法费用 = **$7.554**，
而预留只有 $4/$2。`settle` 在 `charged > reserved` 时仍记全额，账本可越过 cap。审查数字复现一致。

**修法**：冻结 M-5 专用 token 信封（输入 272,000 = terra 上下文窗口；输出 128,000 = 通用合同上界），
预留由信封 × 价目表**机械推导**为 $2.22，并由 loader 校验锁里声明值一致。信封在**账本 settle 处**强制
（不是各个 proxy 调用点），超出即按无效 usage 走保守结算，因此 `charged ≤ reserved` 恒成立，
reserve 时的批次校验就是真上限。

每 run 上限改为由最大并发推导：Root + 3 成员（产品默认 `max_concurrent_threads_per_session=4`）+ Guardian
= 5 × 预留 = $11.10，加各门的消费额度 → 门 1 $23.10、门 2 $15.10。审查指出的「门 2 $8 会拒掉第 4 个
合法 main 请求」因此一并解决。`allow_concurrent_main` 布尔改为经校验的整数 `max_concurrent_main`
（顺带消掉字符串 `"false"` 会开启的问题），代理据此拒绝第 5 路并发。

### P0-4 失败记账与停止原因

按审查决策**不放松**保守记账：`response.failed` 无 usage 仍按整笔预留结算。中转站截图只能证明那一个请求
未计费，不能泛化为协议规则。缓解来自别处——预留额已从 $4.00 降到 $2.22，且新增 `exposure_summary`
把 `priced_usd` / `conservative_exposure_usd` / 实际扣减分开报告，不再把预留描述成真实消费。

停止原因分类修好了：新增 `stop_reason_class`，只有容量耗尽、合法 usage 超预留、请求数上限算 `budget`；
上游失败、缺 usage、网络、deadline 归 `infra`；**未知原因 fail-closed 抛错**，不猜。
门 1 的 `stop_reason is not None → budget_stopped` 和门 2 的同类逻辑都已按此改写。

### P0-5 run id 可被重复消费

属实。门 1/门 2/冒烟都用 `ensure_run`（允许已存在）。已全部改为 `claim_run`，重跑 CLI 会在外发前失败。
未实现完整恢复协议，因此中断的批次诚实判为不完整，不做重放。

### P1-6 冒烟边界

属实：`$5` probe 在打开 `$25` 账本**之前**跑，且冻结 endpoint 校验发生在 probe 外发之后，实际入口上界是 $30。
已改为先校验冻结 endpoint/模型/费率，再在同一账本内跑 probe。冒烟入口重命名为 `smoke`，
强制 `--label <全新 id>`（先于授权检查），既有产物存在时直接拒绝启动。

**历史产物勘误（不改写、不删除既有文件）**：`eval-data/budgets/multi-m5-terra-smoke.json` 与
`eval-data/multi-m5/archives/terra-smoke-records.jsonl` 是 2026-08-18 两次冒烟的产物。两次共用同一个固定
run id 且 `max_runs=1`，因此第二次成功外发意味着旧账本曾被重建或替换；metadata 累计 21 条约 $4.253，
而留存的账本只有第二次的 3 条约 $4.054，两者对不上。**这两份产物不能作为完整费用记录使用。**
按中转站后台记录，其中一次 `response.failed` 实际 tokens 为空、费用 ¥0，账本里的 $4.00 是保守预留而非真实
消费。新的冒烟改用独立路径（`multi-m5-code-mode-smoke.json` / `code-mode-smoke-records.jsonl`）与全新身份，
不与历史产物混用。

### P1-7 诊断锁与费用预测

属实：loader 不校验 `runs_when`、`verdict_effect`，也不拒绝多余键（实测把它改成"判定前运行并把 verdict 改成
pass"仍被接受）。已补齐全键集校验并拒绝未知键。费用预测改为由**同一个程序**从锁里的 basis 重算并与声明值比对：
点估计 $10.40、最坏合法 $43.08（含最多 10 次诊断），loader 拒绝对不上的锁。冻结
`multi-m5-nondegradation-v2`。

### P1-8 门 1 三次尝试

属实：原实现遇 `agent_failed` 第一次就返回。已改为——通过即停；预算/授权类硬停止立即停；
其余（含证据失败、产品未通过）继续到三次。语义写进 v2 锁的 `attempts.semantics` 并由 loader 校验。

### P1-9 文档漂移

已按职责更新 `doc/WBS.md`、`doc/WBS/multi-agent-trusted-evidence.md`、Plan 044 §6，
并在 plan 里把作废的「wire 形状已实测确认」结论标注为历史。全量测试口径按实测写成
「932 用例、0 失败，另有 2 条既有加载错误」，不写成全绿。

## 审查未覆盖、本轮新发现的风险

**团队证据 fact 只在直接调用时留存。** `multidev/codex-rs/core/src/team/evidence.rs` 的
`note_completed_tool_result` 明确跳过非 `ToolCallSource::Direct` 的调用，注释说明嵌套步骤的输出会被折进
cell 结果、不单独保留。含义是：**若真实模型把所有工具调用都放进 code cell，就不会产生任何 fact，
冻结的 `team_evidence` 谓词无法成立。**

这是产品的明确设计，不是 bug。团队工具同时开放直接与嵌套两个暴露面（`ToolExposure::Direct`），
所以模型直接调用 shell 是合法行为，彩排按此建模后七个谓词全绿。但**真实模型是否会这样做，只能由付费冒烟
回答**，本轮不做任何假定。这是进正式门 1 前最需要验证的一点。

## 验证

- 门 1 离线彩排在冻结二进制上跑通：7/7 谓词全绿，16 个请求，证据**全部**来自 rollout trace，`trace_error` 为空。
  过程中该判据真实抓出三个问题并逐个修掉：成员因模型不匹配被捕获代理静默拒掉、Root 与成员的 runtime cell id
  跨线程冲突、团队工具的真实 namespace 是 `collaboration` 而非源码里 `ToolName::plain` 字面暗示的默认
  namespace（后者已据实修正锁与采集器——这一条正说明彩排跑的是真路径）。
- 定向门禁：`tests.test_multi_m5`、`tests.test_multi_m5_exec`、`tests.test_multi_m5_trace_evidence`、
  `tests.test_terminal_bench` 全绿。
- 全量：932 用例、0 失败。仅剩 `test_l6_b10333_pair`、`test_local_m4_holdout_anchor` 两条
  `ModuleNotFoundError: No module named 'eval'` 加载错误，在干净树上同样存在，非本次引入。

## 授权状态

- 用户 2026-08-18 追加授权：**$40 真实 API 冒烟，不限次数**，可自行迭代直到成功或预算耗尽。
  已落地为独立冒烟账本（独立 batch id / lock id / 归档文件），与 $120 完全隔离。
- 用户同时提出「失败无 usage 可按 $1 计」，并说明「若改合同麻烦则按原样」。**本轮选择按原样**：
  审查 P0-4 明确要求保留保守结算，且预留额已降到 $2.22，$40 额度下约有 18 次空转余量，
  不值得为此放松安全线。
- 正式门 1、门 2 与 Docker 仍未授权，未执行。
