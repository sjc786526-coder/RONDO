# Plan 044 / Multi M-5 阶段 B：进展与移交审查日志

日期：2026-08-19
分支：`worktree-044-multi-m5-real-workflow-and-nondegradation`
起点：`163e497` → 当前：`83a0a87`（4 个提交）
`main` = `origin/main` = `45efac6`，**未合并、未推送**，主工作区受跟踪文件干净

> 本文是给后续审查者/接手者的单一入口。三批工作按时间顺序，每批含「问题 → 改法 → 验收」，
> 末尾是**尚未解决的问题**与**建议接手顺序**。

---

## 0. 当前状态速览

| 项 | 状态 |
|---|---|
| 门 1（协作工作流） | **未运行**。3 次尝试全部未消耗 |
| 门 2（不退化） | **未运行**。Docker 未拉取 |
| M-5 `$120` 账本 | **$0**，`eval-data/budgets/multi-m5-phase-b.json` 不存在 |
| 合同外冒烟账本 | $4.253 计量 / **约 $0.46 实际**（独立批次，见 §3） |
| 模型 | `gpt-5.6-terra`（由 M-5 两把锁自钉，宿主别名仍是 `sol`） |
| 全量 `just eval-test` | 914 通过，无新增失败 |
| 阻断 | 1 项待用户/审查者决定（§4.1），2 项建议处理（§4.2、§4.3） |

**已确认可用**：terra 在 CCTQ 中转站已解封（探测通过，上游全部 200）。

---

## 1. 第一批：把退化诊断从「文档声明」变成真实可执行（`03b4469`、`93c88e1`）

### 问题

不退化锁承诺「一旦某题判为稳定单向退化，先在同题上跑一次
`diagnostic_v2_on_team_state_off` 再归因」。但这条承诺没有任何实现支撑：
`load.py` 只是在锁文本里 grep 这个字符串，全仓没有任何代码能构造该槽位，
也没有任何方式让 Multi 以「V2 开、team_state 关」的配置运行。

真跑出退化时，「归因到团队层」只能靠断言。按 CLAUDE.md「skip 或未运行不得表述为通过」，
这是必须在花钱前补上的最小闭环。

### 改法

一条 `team_state` 标志贯通「命令行覆盖 → 归档行 → 账本」，默认值保持既有行为：

- `contracts.py`：新增 `TEAM_CAPABILITY_MULTI_DIAGNOSTIC_TOML`（`enabled=true` 保留、
  `team_state_enabled=false`）；两个投影函数加 `team_state` 关键字参数。其余 `-c` 覆盖
  （含钉死的成员模型）完全不变，保证只差团队层这一个变量。
- `adapters.py`：非 Multi 侧携带该标志直接构造失败；严格解析 Harbor 的 JSON 字符串形式
  （`"false"` 不会被真值化成开启）。agent-kwargs 只在诊断时多输出一项，既有 campaign
  投影逐字节不变。
- `schedule.py` / `gate2.py`：`diagnostic_slots()` 从**已判定的 verdicts** 派生，
  所以「不得预跑」由构造顺序保证而非纪律；`round_index=4` 落在三次观察之外；
  诊断行 `counts_as_effective=false`、不占 `max_effective_runs`、不改判定，
  但共享 $120、infra 尝试与全部停止线。
- `budget.py`：账本槽位 `60+12+3` → `+10`（每题一个）。槽位只是计数护栏，$120 未动；
  不扩的话最坏路径下「要解释退化的那次运行」反而开不了。
- 锁：新增 `attribution.diagnostic` 可执行块，loader 逐字段校验（含类型），缺失或漂移即 fail-closed。

### 验收

9 条定向回归：无退化时诊断不存在（不预跑）、退化时恰好一行且 V2 开 / team_state 关、
不计有效且不改判定、仅 Multi 侧且每题一个、诊断请求只差团队层一个变量、
诊断期间触发容量停止线立即停批、锁字段被篡改或删除即 fail-closed。

---

## 2. 第二批：模型由 sol 换为 terra（`d79b679`）

### 换之前先排除的三个致命点

- 冻结上游 Codex v0.147.0 的 `models-manager/models.json` **已含** `gpt-5.6-terra` ——
  对照侧二进制能跑，门 2 的比较不会瓦解。
- 门 2 不下发 `model_catalog_json`（走 `None`）——不涉及 catalog 重冻结。
- 门 1 指令模板不含模型名——`instruction_sha256` 不变。

terra 与 sol 在本 harness 关心的每个字段上一致：`multi_agent_version=v2`（M-5 要测的正是这层）、
`tool_mode=code_mode_only`、`context_window=272000`、支持 `medium`。唯一差别是默认 effort
（sol=low、terra=medium），而运行时显式钉了 `medium`，无影响。

### 价格（官方页，2026-08-18 只读核对）

| | input | cached | output |
|---|---|---|---|
| sol | $5 | $0.5 | $30 |
| terra | **$2** | **$0.2** | **$12** |

同日复核 sol 仍为 5/0.5/30（与锁里 08-17 快照一致），说明读数可靠。terra 是 sol 的 **40%**。
顺带发现 `rondo.local.toml` 里 terra 的 08-11 快照（2.5/0.25/15）已过时，一并更正。

费用预测：点估计 $40 → **$16**，最坏合法 $96 → **$38.40**，**$120 硬上限不变**。
余量从 1.25 倍变成约 3 倍 —— 这不只是省钱：预算掐断本来是门 2 的真实失败模式
（打满即停批 = 证据不完整 = 不通过），该风险大幅下降。

### 疑难点：全局别名差点污染单智能体方向

第一版直接把 `rondo.local.toml` 的 `main_model` 翻成 terra，全量测试立刻多出一条失败：

```
test_campaign_lock_freezes_unique_full_slot_space_and_profile
BaselineError: selected provider profile drifted from the campaign lock
```

`paid_eval.main_model` 是**机器级全局别名**，同机所有已冻结 campaign 的 provider 身份都由它推导。
翻掉它等于把 P2/B7 历史基线（单智能体方向，sol）的身份一起改了。

改法：`paid_provider_projection()` 加 `model_id=` 关键字，按 model_id 反查 `paid_eval.models`
别名，映射缺失或不唯一即 `ConfigError` fail-closed（不允许回落到宿主别名——那个别名带的费率
决定了 $120 能买多少 token）。M-5 两个付费入口从**自己的锁**取模型；宿主别名保持 `sol`。

副产品：M-5 的模型选择从机器配置移进了任务合同，两个冻结 campaign 可在同一台机器上用不同模型。

> **口径提醒**：这只保住了「历史基线还能跑」。M-5 的 terra 结果与 Local 的 sol 结果之间
> 那条跨方向对读**仍然不成立**——那是换模型本身的代价。好在 M-5 按设计本就不跟 Local 比。

### 验收

3 条隔离回归；基线 campaign 测试恢复通过；门 1 离线彩排**重跑 4 次全绿**（argv 变了，
sol 时代的 5 次全绿已不覆盖当前命令行）；loopback 通过且归档显示 terra；`ready=true`。

---

## 3. 第三批：合同外冒烟测试（`83a0a87`，用户单独授权）

### 设施

新增 `python -m rondo_eval.multi_m5 terra-smoke`：先探测，再跑一次完整流程。
**刻意与合同完全隔离**——独立账本批次 `multi-m5-terra-smoke`、独立归档
`terra-smoke-records.jsonl`、独立 `lock_id`、`max_runs=1`、cap $25。
既不会被误读成门 1 证据，也不会吃 $120。3 条隔离回归钉住。

> cap 取 $25 而非授权上限：上限是停止线，不是消费目标。一次流程点估计约 $3.20。

### 冒烟一：查出阻断 A

Root 跑了 24 个请求、退出码 0，但七项谓词全 false、`TEAM_REPORT.md` 未生成。

成员状态为 `/root/worker → errored: {"error":{"code":"request_rejected"}}`。
起初怀疑中转站拒绝子智能体，但抓包显示 24 条全部同一 session、上游全部 200 ——
**成员的请求根本没发出去**。根因在我们自己的代理：

```
api_budget_proxy.py:1485   "concurrent main requests are disabled"
```

Root 有在途预留时，第二个 `role=main` 请求被本地拒成 HTTP 400。这是单智能体时代的假设，
而 Multi 的前提恰恰是 Root 与成员并发。

**若直接进门 1，这会必然烧光全部三次尝试，且失败原因与产品无关。**

**改法**：`LoopbackResponsesProxy` 增加 `allow_concurrent_main`（默认 `False`，
其它 campaign 行为不变），只在 M-5 三个代理构造点显式开启。放开的是顺序约束，不是记账——
并发的两个请求各自持有预留、共同受同一 cap 约束。3 条回归：默认仍拒绝、
开启后两笔预留都在账、三个构造点确实开启。

### 冒烟二：修复生效，但暴露阻断 B

成员不再被拒（`request_rejected` 消失），请求数 18 → 21。但谓词仍全 false，
且第 21 次上游返回 `response.failed`，运行以 `upstream_terminal_failed` 停止。

### 费用与一条重要的外部证据

| | 账本计量 | 实际 |
|---|---|---|
| 冒烟一 | $0.199 | $0.199（18 次全部正常结算） |
| 冒烟二 | $4.054 | **约 $0.26**（21 次里 20 次正常） |
| 合计 | **$4.253** | **约 $0.46** |

差额来自第 21 次：上游 `response.failed` 且响应不带 usage，代理无法得知真实消耗，
按 `conservative_reservation` 记了整笔 **$4.00** 预留。

**用户提供的中转站后台记录证实该次请求 tokens 为空、费用 ¥0**
（`gpt-5.6-terra`、流式、首字 10.2s、耗时 10.0s、Tokens `—`、费用 0）。
即：失败请求确实一分钱没花，$4.00 纯粹是账本的悲观假象。

---

## 4. 尚未解决的问题

### 4.1 阻断 B（**需决定，门 1 的拦路虎**）：判据认错了 wire 形状

eval 固定 `features.code_mode_host=true`，因此模型看到的团队工具在 code-mode 里，
实际调用是 JS：

```js
await tools.collaboration__spawn_agent({task_name:"worker", ...});
await tools.collaboration__wait_agent({timeout_ms:60000});
await tools.collaboration__followup_task({target:"worker", ...});
await tools.collaboration__list_agents({});
```

线上表现为 `custom_tool_call`（`name="exec"`，工具名嵌在 JS 源码里），返回是
`custom_tool_call_output`。而决策 020 冻结的采集口径是
`evidence_source.kind = "responses_function_call_outputs"`，只认
`function_call` + `name=team_inspect`。

**抓包实测**：全程 `tools` 字段为 `None`、`tools_count=0`、顶层 `function_call` 数为 **0**。

阶段 A 曾「实测确认 wire 形状」，但那次是**直接注入**一个 function_call 验证工具可执行，
并未验证真实模型会不会那样调。结论对，前提错。

**影响**：门 1 按当前冻结判据，在 `code_mode_host=true` 下**不可能通过**——
模型协作得再好，判据也看不见。冒烟里模型其实表现不错：spawn、wait、followup、list_agents 都调了。

**候选方案**（未实施，涉及修改冻结合同，需授权）：

- **A（本人倾向）**：扩展采集口径，让判据同时识别 code-mode 的 `custom_tool_call` /
  `custom_tool_call_output`。理由：模型行为是对的，是判据瞎了；改的是**观测手段**，不是**判定标准**。
  需重新冻结 workflow 锁的 `evidence_source` 并作废受影响的旧证据。
- **B**：关掉 `code_mode_host`，逼团队工具走原生 function_call 路径。但这改的是运行配置，
  与 eval 既有约定（决策 014）冲突，且会改变被测产品的工具面。
- **C**：其它方向，由审查者判断。

> **给接手者的关键提醒**：若走 A，**必须同时把门 1 离线彩排的 stub 改成发出 code-mode 形状**。
> 当前 stub 走的是 function_call 路径，所以彩排 4 次全绿却对真实失效模式完全无感——
> 这正是这次踩坑的成因。只改采集不改 stub，等于把同一个错误再犯一次。

### 4.2 建议处理：失败请求被保守记账吃掉预算

已证实上游 `response.failed` 可以是**零 token、零费用**的，但代理仍按整笔预留
（门 1 是 $4.00）结算。在 $120 账本上，几次这样的瞬时失败就能吃掉大几十美元
**从未真实花出去的**预算，进而把门 2 推向「预算掐断 → 证据不完整 → 不通过」。

建议：对 `terminal_response_status == "failed"` 且 usage 缺失的情形，
区分「无 usage 因而未知」与「明确失败且上游申明零消耗」，或将保守金额下调到与
失败请求的现实成本相称。**注意**：这是安全方向的放松，需谨慎论证，不可为了跑通而弱化。

### 4.3 小问题：停止原因被贴错标签

`gate1.py` 里只要 `stop_reason is not None` 就记 `outcome = "budget_stopped"`，
于是 `upstream_terminal_failed` 被贴成「预算停止」。不影响判定，但会误导排障。

### 4.4 观察项（证据不足，勿下结论）

冒烟二的 `response.failed` 出现在并发成员活跃时，首字 10.2s。
**仅一次，不足以判断**是中转站的并发限制、瞬时抖动，还是别的原因。
接手者若再遇到同类失败，值得关注是否与并发相关。

---

## 5. 建议接手顺序

1. 先定 §4.1 的方案（A/B/C）。这是门 1 唯一的硬拦路虎，不解决跑门 1 就是浪费尝试次数。
2. 若走 A：同步改 stub（见 §4.1 提醒），重新冻结 `evidence_source`，重跑离线彩排，
   再用**合同外冒烟**验证一次真实模型下判据能否看见协作——确认后才进门 1。
3. 处理 §4.2，避免门 2 被虚假预算掐断。§4.3 顺手修。
4. 门 1 通过后再进门 2（Docker 十个 digest 仍未拉取）。

---

## 6. 边界与合规

- M-5 的 `$120` 账本**一分未动**，两道门均未运行，门 1 三次尝试全部保留。
- 冒烟花费走独立批次，实际约 $0.46；已产生的费用如实累计，未重开账本规避。
- 未拉取任何 Docker 镜像；未加载本地模型；未训练；未推送远端。
- `.env.local` 仅做存在性/权限/变量非空的静默检查，未打开内容。
- 仅清理过本任务自建的探测产物目录，未触碰任何来源不明的对象。
- 结论口径未放宽：至今**不得**表述为 M-5 通过、门 1 通过或未见退化。

---

## 勘误（2026-08-19，第五轮审查整改后追加）

本文件保留为形成时点的历史记录，以下两节的结论已被取代，详见
`agent_log/2026-08-19-060000-plan044-m5-phase-b-fifth-review-remediation.md`。

1. **门 1 采集口径**：本文记为"待授权决定"。已决定并落地——改读冻结二进制自身的 rollout trace
   （`CODEX_ROLLOUT_TRACE_ROOT`），不解析 JS、也不采信 `custom_tool_call_output`，并冻结
   `multi-m5-workflow-v2`。彩排 stub 已同步改为 code-mode 形状。

2. **冒烟账本与费用**：本文记的 "$4.253 / 21 条 metadata" 与留存账本的 "3 条 / $4.054" 对不上。
   原因是两次冒烟共用同一固定 run id 且 `max_runs=1`，第二次成功外发意味着旧账本曾被重建或替换。
   **`eval-data/budgets/multi-m5-terra-smoke.json` 与
   `eval-data/multi-m5/archives/terra-smoke-records.jsonl` 不能作为完整费用记录使用。**
   其中 $4.00 是 `response.failed` 无 usage 时的保守预留，中转站后台记录显示该请求实际 tokens 为空、费用 ¥0。
   历史产物不改写、不删除；新的冒烟改用独立路径与全新身份。

3. 本文"门 1 当前不可能通过"的判断**成立且已被本轮确认**，现已修复。
