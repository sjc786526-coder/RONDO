# Plan 044 / M-5 真实 code-mode 冒烟验收审查

日期：2026-08-19
分支：`worktree-044-multi-m5-real-workflow-and-nondegradation`
代码范围：`5a2a72d..b0e5dfd`
证据范围：`cm1..cm4` 的 smoke ledger、归档、budget metadata、verdict 与 rollout trace

## 结论

**验收不通过。**

可以确认的正面结果有两个：

1. 真实模型通过 code cell 调用的 `collaboration.*` 工具能够被 rollout trace 看见并绑定，
   `team_inspect`、namespace 与 `spawn_member` 判据路径成立；
2. 四次账目相加为 `$31.523468`，其中 priced `$0.443468`、保守预留 `$31.08`，
   与逐 run 归档一致；正式 `$120` 账本未启动。

但新加的 `unpriced_stop_threshold` 把“是否允许流程继续”和“这次运行是否仍是有效产品证据”
混成了一件事。cm4 含 8 个明确的上游 terminal error，却被归档成无 stop 的 `agent_failed`；
同一机制进入正式 Gate 2 后，还会把带设施错误的结果算作有效观察。基于 cm4 得出的
“terra 不遵守协议、下一步应改载体/指令”结论因此不成立。

## Findings

### [P0] 允许请求继续时仍须把 run 标为 infra-tainted — `eval/rondo_eval/api_budget_proxy.py:632`

低于阈值的 `conservative_reservation` 只扣钱，不保存 stop/taint 原因。随后
`run_stop_reason()` 因 `stopped=false` 返回 `None`，Gate 1 会把该 run 判成
`completed` / `agent_failed`，Gate 2 会令它 `counts_as_effective=true`。

离线复现正式 ledger 中一次 `upstream_terminal_error`：

```text
settlement_kind=conservative_reservation
charged_usd=2.220000
stopped=false
stored_stop_reason=None
gate_visible_stop_reason=None
```

真实 cm4 正好命中：`conservative_exposure_usd=17.760000`，即 8 次完整预留，
ledger 却写 `stopped=false/stop_reason=null`，归档写 `agent_failed`。正式阈值为 4，
意味着每个正式 run 最多可带 3 次设施错误仍被当作产品观察；Gate 2 由此可能制造
“Codex 完成、Multi 未完成”的假退化。

阈值可以决定是否让流程继续收集诊断，但不能清除设施污染。应在每次保守结算时持久记录
`infra_tainted`、次数和首个原因；Gate 1 最终必须归 `infra_failed`，Gate 2 必须
`counts_as_effective=false`。只有请求是否继续，才由 threshold 决定。

### [P1] 撤回“真实模型不遵守协议”的当前结论 — `doc/WBS.md:102`

cm4 并不是干净的完整模型运行。30 个已结算请求里有 8 个 200 terminal error，
metadata 的错误码均为 `invalid_encrypted_content`；它们占全部 `$17.76` 保守预留。
rollout trace 同时显示所有成功的团队工具调用都来自 Root，成员没有产生任何工具调用。

因此“成员未 publish/evidence”至少与成员请求无法正常完成混杂，不能归因给 terra 的指令遵循。
错误虽然由 provider 返回，但触发原因可能是 relay 的 encrypted-content/session affinity，
也可能是 Multi 子线程构造或复用 encrypted content 的方式；现有证据不足以断言
“纯上游抖动”或“纯模型不听指令”。

WBS、Plan 和主日志应改为：**观测管线已验证；encrypted-content 子线程路径失败，产品/relay
归因未定；门 1 载体行为仍无干净观察。**

### [P1] `Direct` / `team_evidence` 风险仍未回答 — `doc/WBS.md:103`

独立解析 cm4 trace：

```text
18 root code_cell calls
1  root model call: namespace=None, tool=wait, status=failed
0  member tool calls
```

唯一 `requester=model` 的调用是 Root 上一个失败的无 namespace `wait`；所有
`collaboration.*` 调用仍是 code-cell nested dispatch。它既不是成员调用，也没有产生可用于
finding 的成功 observation，不能证明成员在 code-mode 下会获得可供 `team_evidence` 引用的
Direct fact。

因此 `multidev/codex-rs/core/src/team/evidence.rs` 的既有风险仍在：嵌套调用不铸 fact；
外层 code cell 是否能在成员历史中形成合适 observation，必须由一次**无 infra taint 的成员运行**
或针对外层 exec retention 的离线产品测试证明。

### [P1] 在正式运行前冻结新的失败与重试策略 — `eval/rondo_eval/multi_m5/budget.py:422`

正式批次现在使用 `UNPRICED_STOP_THRESHOLD=4`，Gate 1 又把 retry backoff 从 0 改为 2 秒，
但 workflow-v2 / nondegradation-v2 都没有这两个字段，ledger schema 和 archive 也不记录 threshold。
同一份 v2 锁、同一账本可以在代码更新后以不同策略重开，无法证明某一正式观察受哪套失败政策约束；
费用预测也没有纳入新合法的保守结算路径。

在正式门启动前应二选一：

- 最小修法：正式 v2 恢复“第一个 unpriced 即 infra stop”，threshold 仅保留给合同外诊断；
- 若正式门确需“允许继续但证据作废”，冻结 workflow/nondegradation v3，明确 continuation threshold、
  `any_unpriced_invalidates_observation=true`、retry backoff，并让 loader/readiness/archive 一致投影。

推荐第二种，但应与 provider 变更一起一次冻结，避免连续改锁。

### [P2] 清理当前文档里的相反入口说明 — `plan/044-multi-m5-real-workflow-and-nondegradation-execplan.md:316`

Plan 仍写 smoke 内置 `provider_probe`，但该 probe 已按上轮决定删除；WBS 同时写
“真实付费运行仍未开始”和“四次冒烟已执行”。这些旧句会直接误导下一执行者。
应分别改成“正式两道门未启动”和“smoke 不含独立 probe”。

## 独立验证

- 新 threshold、默认隔离、out-of-envelope 与 retry 定向测试：17/17 通过。
- `just eval-lock`：通过。
- 离线复现确认一次低于阈值的 upstream terminal error 对 Gate 不可见。
- cm4 trace 独立解析确认：18 个 Root code-cell 调用、1 个失败的 Root direct wait、0 个成员调用。
- 原始 ledger / archive 复核：
  - cm1 `$2.261041`
  - cm2 `$2.290706`
  - cm3 `$9.000642`
  - cm4 `$17.971079`
  - 合计 `$31.523468`
- 未调用真实 API、Docker、Cargo 或本地模型；未增加费用。

现有测试证明 cap 仍安全、默认 campaign 未放宽，但没有测试“低于阈值的 infra 结算不得成为
Gate 1 产品失败或 Gate 2 有效观察”，故不能推翻 P0。

## 代用户作出的决定与解决顺序

1. **现在不修改指令模板，也不换模型。** cm4 不是干净观察，不能据此重冻 instruction 或否定 terra。
2. **不再使用剩余 `$8.48` 继续跑同一 relay。** 14 次保守结算中，cm3/cm4 已分别出现 4/8 次；
   这不是值得继续用正式尝试赌博的偶发率。
3. **先修证据污染语义：**
   - threshold 只控制“继续/停止”；
   - 每个 unpriced/terminal error 都持久标记 infra taint；
   - Gate 1 tainted run 只能是 `infra_failed`；
   - Gate 2 tainted row 必须非有效；
   - 补一条 Gate 1 和一条 Gate 2 回归，直接覆盖“可继续但不可判产品”的场景。
4. **随后定位 `invalid_encrypted_content`：**
   - 离线把失败 request 与 Root/member thread、外层 exec 及 encrypted-content 来源绑定，
     不打印或归档 ciphertext；
   - 若 Multi 子线程发出的引用关系错误，修产品并补回归；
   - 若请求关系正确而 relay 不能稳定接受子线程继承内容，要求 relay 修复 session affinity，
     或换到兼容的 provider endpoint。不得通过剥离 encrypted content 来“修”，那会改变模型上下文。
5. **provider 可用后再冻结 v3。** 将 endpoint、retry/backoff、continuation threshold 与
   infra-taint 无效化规则一次写入新锁；v2 保留历史，不静默改写。
6. **只在新 provider/修复后的 relay 上做一次小额、全新身份的 clean smoke。**
   验收条件不是 `returncode=0`，而是：
   - `conservative_exposure_usd=0`
   - 无 terminal error / infra taint
   - 成员至少完成一次工具调用
   - trace 绑定无误
   只有这次仍不走协议，才进入“加强指令”的分支。
7. 若 clean smoke 仍失败，优先加强 instruction：给 Root 一个必须原样传给 member 的明确任务文本和
   可核对 checklist；继续使用 terra。换模型会同时改变 Gate 2 比较身份和费用，作为最后选项。
8. 正式 Gate 1 / Gate 2 继续禁止启动；正式 `$120` 授权和账本均不触碰。

## 当前状态

- 本轮验收：**不通过**。
- trace 观测管线：真实模型下的 code-cell collaboration dispatch 已验证。
- `team_evidence` Direct fact 路径：仍未验证。
- 指令 / terra 是否导致协议失败：证据不足，不能下结论。
- 当前首要阻断：infra-taint 被阈值隐藏，以及 `invalid_encrypted_content` 的产品/relay 归因。
- M-5：未通过；Gate 1 未通过；Gate 2 未启动；不存在“未见退化”结论。
