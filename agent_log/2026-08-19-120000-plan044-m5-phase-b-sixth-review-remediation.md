# Plan 044 / M-5 阶段 B：第六轮审查整改

日期：2026-08-19 ｜ 分支：`worktree-044-multi-m5-real-workflow-and-nondegradation`
范围：验收审查 7 项（3×P0、2×P1、2×P2）全部核实并修复。

## 结论口径

**M-5 仍未通过，门 1 未通过，不存在任何「未见退化」的结论。** 未拉 Docker、未跑 Cargo、
未加载本地模型；`$120` 正式账本仍未产生消费，文件仍不存在。

费用相关的时间线要分清：**七项整改期间未调用真实 API**；整改与验收通过之后，
经用户明确授权，在原 `$40` 额度内用全新 label 跑了**一次**真实冒烟，结果见文末专节
（`infra_failed`，实际按 token 计价约 `$0.04`）。`$40` 授权未扩张。

## 核实结果

审查 7 项**全部属实**。三项 P0 我都先离线复现再动手。

### P0-1 冒烟 probe 绕过 $40 上限

属实。`run_provider_probes()` 会在自己的输出目录另建一份 `PROBE_TOTAL_CAP_USD = $5` 的 Plan 013 账本
（`provider_probe.py:154-160`），而正式 smoke run 直到 probe 完成后才 `claim_run`。因此每换一个 label
都能在 `$40` 之外再花最多 `$5`，且 `$40` 耗尽后仍会先外发 probe。上一轮 P1-6 要求的"probe 纳入同一份
持久 cap"确实只做了一半。

**修法**：按审查者的决定**直接删掉 smoke 里的 pre-probe**，而不是改造通用 probe 去共享外部账本。
理由认同：完整 flow 本身就会证明 endpoint/model 可用，为它给通用 probe 加一条外部 ledger 注入通道
只会多一条接线；真要单独 probe，应作为独立、单独授权的动作，而不是藏在 `$40` 入口里。
现在这个入口能花的每一分钱都被"这里打开的那一个账本"框住。冻结 endpoint/模型/费率的校验仍在最前面。

### P0-2 归档把 terra 成员写成 sol

离线复现与审查报告一致：

```
locked_member=gpt-5.6-terra
archived_member=gpt-5.6-sol
```

上一轮给 `team_capability_config_projection()` 加了 `subagent_model` 参数，却没有让 `archive_record()`
及其调用点传下去，于是命令行跑 terra、归档必填字段写 sol。Gate 2 的 live row 还会在 `model_projection`
里写 terra，同一行自相矛盾；Gate 1 没有第二个字段可以纠正它。

**修法**：`archive_record()` 增加 `subagent_model` / `subagent_effort` 并透传到投影；Gate 1（取 workflow
锁）、Gate 2（取 nondegradation 锁）、loopback（取自身模型）三处调用点全部传入。并且**fail-closed**：
`product=rondo-multi` 却没有成员身份时直接 `ValueError`，不再静默回落到宿主默认——这条守卫立刻在两个
旧测试上触发，说明它确实拦得住这类遗漏。

### P0-3 Gate 2 记录写 v1 身份

离线复现一致：

```
loaded_lock=multi-m5-nondegradation-v2
archived_lock=multi-m5-nondegradation-v1
```

`_record_for()` 把 `lock_id` 硬编码成 v1。**修法**：改为取 `contract.lock_id`，由运行时实际加载的合同决定，
`_record_for` 增加必填 `contract` 参数。现在 v2 运行只可能产出 v2 行。

### P1-4 Gate 2 条件复跑 staging 冲突

属实。`staging_name` 只有 `batch + side + task_slug`，而 `PinnedTaskMaterializer` 按设计拒绝复用目录，
所以同题同侧第二次 materialization 稳定失败：

```
MaterializationError: staging destination already exists
```

含义很重：infra 重试进不去 Docker，**round 2/3 的条件复跑也进不去**——恰恰是判定稳定单向退化所需的三次
观察那条路径。

**修法**：`staging_name` 追加由 `docker_task_id`（各调用方已按 round/attempt 唯一）派生的 12 位 sha256 前缀。
用哈希而不是直接拼 id，避免长 id 撑爆路径长度，也避免调用方往 id 里放进不安全字符。
离线连续 prepare 同一 slot 的 attempt 1/2/3 现在三次都成功且落在三个不同目录。

### P1-5 停止线必须先于成功分支

属实。原顺序先判 `verdict.passed && returncode == 0`，再处理 stop。只要谓词和报告已经形成，之后同一 run
出现 `upstream_terminal_failed`、缺 usage 或容量耗尽，仍会归档成 `completed/passed=true`。

**修法**：把 budget / infra / unknown 的判定整体提到成功分支之前。谓词仍完整记在行上（近失手要能排障），
但已停止的 run 不会被改判为通过。新增回归直接驱动真实彩排并注入三种 stop reason，断言
`outcome` 分别是 `budget_stopped` / `infra_failed`、`passed=false`，且**此时七个谓词全为真**——
这正是修复前会误判通过的场景。

### P2-6 loader 漂移测试是空验收

属实且解释力很强。该测试读 v1 文件、再把变体交给只接受 v2 的 loader，因此每个 case 都在检查
`runs_when` / `verdict_effect` / 额外键**之前**就因 lock id 不符而抛错——绿灯，但什么都没验。
这也正好解释了为什么正式行写 v1 却没有测试报警。

**修法**：改读 `NONDEGRADATION_LOCK_ID`，并**先断言未修改的临时副本能成功加载**（控制组），
否则后面每一次拒绝都可能是副本本身造成的。补上 `runs_when`、`verdict_effect`、未知键三类变体，
以及"手改 `worst_legal_usd` 必被重算拒绝"。另加一条断言：归档行的 `lock_id` 必须等于 loader 的 `lock_id`。

### P2-7 权威文档旧事实

属实。`doc/WBS/multi-agent-trusted-evidence.md` 前文仍写"Multi 目前没有冻结的 runtime bundle"，
后文却写阶段 A 已冻结；Plan 044 当前状态前部仍把两份合同写成 v1，并保留累计费用 `$0`。已全部更正为
v2 与 bundle 已冻结的事实。费用一句改为：**正式 `$120` 账本仍零消费**，但"整个任务累计 $0"已不成立
（8-18 合同外冒烟发生过真实支出，指向勘误）。`doc/WBS-COMPLETED.md` 里的 v1 引用属形成时点历史，按规则保留。

## 我与审查建议不同的地方

只有一处，且是加严不是放宽：审查只要求"把成员身份传下去"，我额外让 `archive_record()` 在
Multi 行缺成员身份时**直接失败**。理由是这一类遗漏正是本轮 P0-2 的形态——参数加了但调用点没传，
静默回落让错误值看起来完全正常。守卫加上后立刻在两处旧测试暴露，证明它拦得住。

其余均按审查者代为作出的决定执行：删除 pre-probe（而非改造通用 probe）、不动 `ToolCallSource::Direct`
证据保留设计、不弱化 `team_evidence`、不扩张 `$40`、v2 为唯一当前合同、正式两道门继续禁止启动。

## 验证

- 门 1 离线彩排在冻结二进制上仍全绿：7/7 谓词，`lock_id=multi-m5-workflow-v2`，
  归档成员为 `gpt-5.6-terra`，`trace_error` 为空。
- 归档身份离线复核：`loaded=archived=multi-m5-nondegradation-v2`，Multi 行成员 terra，Codex 行无成员。
- staging：同题同侧连续三次 prepare 全部成功，三个不同目录。
- 停止语义：三种 stop reason 均不再产出 `completed`。
- 定向门禁 `tests.test_multi_m5`、`tests.test_multi_m5_exec`、`tests.test_multi_m5_trace_evidence`、
  `tests.test_terminal_bench`：142 → 144 用例全绿（新增 4 条回归）。
- 全量：936 用例 0 失败（仅剩两条既有 `No module named 'eval'` 加载错误）；`just eval-lock` 通过。
- 七项整改本身未调用真实 API、Docker、Cargo 或本地模型；随后的授权冒烟见文末专节。

## 下一步

按审查者决定：修复复验通过后，可在原 `$40` 授权总额内、用**全新 label** 跑一次真实 smoke，
回答"真实模型会不会产生 `ToolCallSource::Direct` 证据"这个门 1 的关键未知数。
在那之前不动产品语义，正式 Gate 1 / Gate 2 继续禁止启动。

**该冒烟已执行，见文末专节。** 关键未知数**仍未回答**（成员被 spawn 后流程即被上游中断），
因此正式 Gate 1 仍不具备启动条件。

---

## 首次真实 code-mode 冒烟（2026-08-19，用户授权后执行）

入口：`smoke --label cm1`，独立账本 `multi-m5-code-mode-smoke`（$40 上限），未附加 provider probe，
未触碰 `$120` 正式账本。**这不是门 1 尝试，也不是门 1 通过。**

**结果：`infra_failed`，原因 `upstream_terminal_error`。流程未走完。**

费用（新的分开记账正好在这里派上用场）：

| 项 | 值 |
|---|---|
| 账本实际扣减 | `$2.261041` |
| 其中**真实按 token 计价** | `$0.041041` |
| 其中**保守预留**（1 个请求无 usage） | `$2.220000` |
| 已结算请求 | 3（另 1 个未结算） |
| $40 余量 | `$37.738959` |

三个请求的实际 usage：20,523 / — / 20,677 input，122 / — / 41 output。真实消耗只有约 4 分钱；
`$2.22` 是那个拿不到 usage 的请求按预留保守扣的，不是真实花费。

### 有价值的正面结果：证据管线在真实模型上成立

rollout trace 里确实记到了真实模型发起的协作：

```
code_cell_started        1
tool_call_started        1   kind=spawn_agent  label=collaboration.spawn_agent
tool_call_ended          1
agent_result_observed    1
```

抓包对应 `custom_tool_call(name=exec)`，input 是
`const r = await tools.collaboration__spawn_agent({task_name:"worker", ...})`，返回
`{"task_name":"/root/worker"}`。也就是说：**真实模型用 code mode 调团队工具，而新的 trace 判据看得见它，
namespace 也确实是 `collaboration`** —— 第五轮那次口径重建的核心假设，在真实模型上得到验证。
`trace_error` 为空，绑定校验通过。

### 失败原因：纯上游，不是产品也不是判据

trace 里的三条错误说得很清楚：

```
inference_failed    | stream disconnected before completion: stream closed before response.completed
inference_cancelled | response stream dropped before provider terminal event
inference_failed    | exceeded retry limit, last status: 429 Too Many Requests
```

先是流被中途掐断，随后 429 打满重试。新的停止原因分类在这里表现正确：归为 `infra_failed` 而**不是**
`budget_stopped`（修复前会贴成预算停止，把人引向错误方向）。

### 由这次真实运行暴露并已修复的 harness 缺陷

门 1 与冒烟的预算代理都配了 `retry_backoff_seconds=0.0`。Root 与成员本来就并发，中转站对后到的那个
请求回 429；零退避意味着五次重试在几毫秒内打完，等于没有重试，然后就以上游失败收场。
已改为 `GATE1_RETRY_BACKOFF_SECONDS = 2.0`（代理按 2/4/8/16s 指数退避，并在超过 forward deadline 前提前
停止，整条阶梯装得进一个 180s forward 窗口）。门 1 只有三次尝试，这个缺陷会实打实吃掉尝试次数。

### 仍未回答的关键问题

门 1 最要紧的未知数——**真实模型会不会产生 `ToolCallSource::Direct` 证据**（决定 `team_evidence` 谓词
能否成立）——**这次没有回答**：成员刚被 spawn 出来，流程就被上游打断了，成员还没做任何工具调用。

七个谓词全 false 是"流程没跑完"的结果，不是"协作机制不成立"的结论。

---

## 冒烟第 2—4 次（cm2 / cm3 / cm4）与 $40 授权用尽

用户 2026-08-18 追加"不再限制次数、只有 $40 限额"后共跑了 cm2、cm3、cm4 三次。

### 账目（四次合计）

| run | 账本扣减 | 请求数 | 结果 |
|---|---|---|---|
| cm1 | `$2.261041` | 4 | `infra_failed` |
| cm2 | `$2.290706` | 4 | `infra_failed` |
| cm3 | `$9.000642` | 14 | `infra_failed` |
| cm4 | `$17.971079` | 30 | `agent_failed`（流程走完） |
| **合计** | **`$31.523468`** | | |

**其中真实按 token 计价只有 `$0.443468`**（约 3 元人民币），保守预留 `$31.08`。$40 余量 `$8.476532`，
不足再跑一次完整流程，故就此停止。

用户提供的中转站后台记录与我的账本逐条对上（cm1、cm2 两批），**无 token 的那次请求确实计费 ¥0**。
按审查 P0-4 与用户"按原样即可"，**未据此放松保守记账**：截图无法机器绑定到具体 response id，
且流可能在 token 已计费之后才断。

### 真正的阻断是我自己的账本，不是 provider

cm1/cm2 只跑 4 个请求就死，诊断出因果链：

1. 上游偶发地把流在 `response.completed` 之前掐断（中转站显示这类请求 0 token、¥0）；
2. 我的 `settle()` 保守扣一整笔预留，**并把整个 run 置为 stopped**；
3. 此后每个请求都被我的代理拒成 HTTP 429；
4. CLI 在 429 上耗尽重试后死亡，日志写着 `exceeded retry limit`。

**provider 只抖了一下，harness 把它放大成整轮报废。** 所有请求 `attempt_count=1`，说明代理的重试根本
没参与——那是 200 响应，不在 `unbilled_retry_statuses` 里。

**修法**：`PersistentBudgetLedger` 增加 `unpriced_stop_threshold`，**默认 1 = 完全保持既有行为**
（`test_api_budget_proxy` 全套通过，其它 campaign 一律不受影响）。M-5 正式批次取 4，合同外冒烟取 9。
记账**没有放松**：每个无 usage 的请求仍按整笔预留扣款；变的只是"一次抖动要不要终结整轮"。
`_require_unpriced_budget()` 机械校验 `threshold × 预留 < 对应 run cap`，最坏盲花仍被 run cap 框住，
batch cap 不动。计数从既有 request 日志派生，**不改磁盘 schema**。

效果立竿见影：cm1/cm2 4 个请求 → cm3 14 个 → cm4 **30 个请求跑完整个流程、`returncode=0`、未被停止**。

### 门 1 判据在真实模型上完全成立（本轮最有价值的结论）

cm3/cm4 的 trace 记到了真实模型经 code cell 发起的全部团队工具调用，`trace_error` 始终为空、绑定校验通过：

```
collaboration.spawn_agent      collaboration.wait_agent
collaboration.followup_task    collaboration.list_agents
collaboration.team_inspect     collaboration.send_message
```

**包括判据必需的 `collaboration.team_inspect`**，namespace 与第五轮据源码修正的值一致。
`spawn_member` 谓词在 cm3/cm4 **由真实模型证据判为 true**。

第五轮那次判据重建（放弃 `function_call` 口径、改读 rollout trace）到此在真实模型上得到完整验证，
不再只是彩排里的推断。

另有一条与 `team_evidence` 直接相关的观察：cm4 里出现了 `wait` 且 `requester=model`，
即**真实模型确实会发出 Direct 调用**，不是只用 code cell。所以"Direct 证据在 code mode 下不可能产生"
这个担忧**不成立**；但本轮仍未出现能铸成 fact 的 Direct 调用（模型没直接调 shell）。

### 真实模型没有遵守冻结的协作协议

cm4 完整跑完，30 个请求，7 个谓词只有 `spawn_member` 为真，且没有写出 `TEAM_REPORT.md`。
Root 的行为是"派活 + 等"循环：`spawn_agent → followup_task/wait_agent ×5 → list_agents →
team_inspect → send_message`，**从头到尾没有调用 `team_publish` / `team_route` / `team_update` /
`team_evidence`**；成员线程没有发起任何工具调用。

这不是设施失败，也不是判据看不见——判据看得很清楚，是模型没做那些动作。
指令模板规定了工具顺序，但 terra 没有照做。

**这对门 1 是一个实质性的负面信号**：按当前载体与指令，真实模型下门 1 大概率不通过，
而且不通过的原因是"模型不遵守规定的协议"，不是"团队机制不工作"。三次尝试很可能都会这样。

### 我停在这里的原因

$40 只剩 `$8.48`，不够再跑一次完整流程。且再跑同样的配置大概率得到同样结果——
问题已经从"设施能不能观测"转移到"载体/指令能不能让真实模型走完协议"，
那是需要你我先决策的事（改指令模板会动 `instruction_sha256`，属于改冻结合同），不是继续烧钱能解决的。

**M-5 未通过，门 1 未通过，不存在"未见退化"结论。正式 `$120` 账本仍未产生任何消费。**
