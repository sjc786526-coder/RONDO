# Plan 044 / Multi M-5：退化诊断闭环（付费前最后一项准备）

日期：2026-08-18
分支：`worktree-044-multi-m5-real-workflow-and-nondegradation`
起点：`163e497` → 结果：`03b4469`
真实 API / 付费 / Docker：**未执行，累计费用 $0**

## 背景

进入阶段 B 前复核发现：不退化锁承诺「一旦判为稳定单向退化，先在同题上跑一次
`diagnostic_v2_on_team_state_off` 再归因」，但这条承诺没有任何实现支撑 ——
`load.py` 只是在锁文本里 grep 这个字符串，全仓没有任何代码路径能构造该槽位、
也没有任何方式让 Multi 以「V2 开、team_state 关」的配置跑起来。

后果是：真跑出退化时，"归因到团队层" 只能靠断言，锁里那句话等于无法兑现。
按 CLAUDE.md「skip 或未运行不得表述为通过」，这属于必须在花钱前补上的最小闭环。

## 改动

一条 `team_state` 标志贯通「命令行覆盖 → 归档行 → 账本」，默认值保持既有行为：

- `contracts.py`：新增 `TEAM_CAPABILITY_MULTI_DIAGNOSTIC_TOML`
  （`enabled=true` 保持，`team_state_enabled=false`）。`team_capability_override_items`
  与 `team_capability_config_projection` 加 `team_state` 关键字参数。
  其余 `-c` 覆盖（含钉死的成员模型）完全不变，保证只差团队层这一个变量。
- `adapters.py`：非 Multi 侧携带该标志直接构造失败（上游 `--strict-config` 根本不认这个键，
  Local 也没有团队层）；Harbor 会把 kwargs 从 CLI 字符串重建，故严格解析 `"true"/"false"`，
  避免真值化把 `"false"` 变成开启。命令校验器同步按诊断态断言，不再写死 `team_state_enabled=true`。
  agent-kwargs 只在诊断时才多输出一项，既有 campaign 的投影保持逐字节不变。
- `runner.py`：`TerminalBenchRequest.team_state_enabled`，默认 `True`。
- `schedule.py` / `gate2.py`：`diagnostic_slots()` 从**已判定的 verdicts** 派生，
  所以「不得预跑」由构造顺序保证而不是靠纪律；round_index=4 落在三次观察之外。
  诊断行 `counts_as_effective=false`、不占 `max_effective_runs`、不改判定，
  但共享 $120、infra 尝试与 Docker/请求全部停止线。
- `budget.py`：账本槽位 `60+12+3` → `+10`（每题最多一个诊断）。
  槽位只是计数护栏，$120 硬上限未动；不扩的话最坏路径下"要解释退化的那次运行"反而开不了。
- 锁：新增 `attribution.diagnostic` 可执行块，loader 逐字段校验（含类型），缺失或漂移即 fail-closed。

## 疑难点

- **诊断不能算进分母**。它回答的是"为什么退化"，不是"是否退化"。
  若让它计入有效观察，一次 team_state 关掉后的成功会稀释三次观察规则。
  故 `billable`（是否计费/记账）与 `counts`（是否算有效观察）拆成两个概念。
- **`"false"` 的真值化**是这次最容易漏的一处：Harbor 从 CLI 重建 kwargs 一律是字符串，
  `if value:` 会把关掉团队层的诊断悄悄跑成正常 Multi 运行，且归档还会声称团队层是开的。

## 验收

- 新增定向回归 9 条：无退化时诊断不存在（不预跑）、退化时恰好一行且 V2 开 / team_state 关、
  不计有效且不改判定、诊断槽仅 Multi 侧且每题一个、诊断请求只差团队层一个变量、
  诊断期间触发容量停止线立即停批、锁字段被篡改或删除即 fail-closed。
- `tests.test_multi_m5` + `tests.test_multi_m5_exec` + `tests.test_terminal_bench`：113 通过。
- 全量 `just eval-test`：**905 通过 / 无新增失败**。其中 2 条
  `ModuleNotFoundError: No module named 'eval'` 加载错误（`test_l6_b10333_pair`、
  `test_local_m4_holdout_anchor`）在干净树上同样复现（896 用例、同样 2 条），属既有问题。
- `just eval-lock` 通过；`just eval-multi-m5-gate2-fake` 通过（`diagnostic_slots=0`，无退化时不触发）。
- 门禁必须先清 `HTTP_PROXY/HTTPS_PROXY/ALL_PROXY`，否则环回假上游被宿主代理劫持。

## 状态

阶段 B 离线准备至此全部完成。两道门均未运行，费用 $0，等待用户放行后再执行门 1、门 2。
